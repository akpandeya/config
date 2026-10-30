#!/usr/bin/env python3
"""Save an offline HTML explanation outside Git and open it in the local browser.

Input JSON: {"kind": "review"?, "title": "...", "summary": "...", "sections": [
  {"heading": "...", "severity": "blocker|should-fix|nit|question"?,
   "location": "path:line" | {"text": "...", "url": "https://..."}?,
   "paragraphs": ["..."], "steps": ["..."],
   "flow": ["Input", "Validation", "Result"], "code": "...",
   "comments": ["pasteable suggested comment", ...]}
  or
  {"heading": "...", "blocks": [
    {"type": "text", "text": "..."},
    {"type": "callout", "title": "...", "text": "..."},
    {"type": "comparison",
     "left": {"label": "Expected", "value": "...", "text": "..."},
     "right": {"label": "Actual", "value": "...", "text": "..."}},
    {"type": "diagram", "source": "flowchart TD\\nA-->B",
     "caption": "...", "text_alt": "..."},
    {"type": "details", "summary": "...", "blocks": [...]},
    {"type": "comments", "items": ["pasteable suggested comment"]},
    {"type": "table", "columns": ["Name"] | [{"label": "Total", "align": "left|right|center"}],
     "rows": [["a", "b"], ...], "caption": "..."},
    {"type": "chart", "kind": "bar|line", "labels": ["W1", ...],
     "series": [{"name": "...", "values": [1, ...]}, ...],
     "title": "...", "xLabel": "...", "yLabel": "...",
     "caption": "...", "text_alt": "..."},
    {"type": "dbml", "source": "Table users { ... } Ref: ...",
     "caption": "...", "text_alt": "..."}}],
  "metadata": {"Revision": "abc123" | {"text": "base abc123", "url": "https://..."}},
  "sources": [{"label": "...", "url": "https://...", "date": "accessed 2026-10-27"?}]}
All content is plain text, not HTML; optional fields may be omitted and unknown
keys are rejected before anything is written. A section must use either ordered
blocks or legacy content fields, never both. Bare public https URLs in text
are auto-linked; http:// or credentialed URLs stay plain text. Metadata values
may be plain text (auto-linked) or a {"text", "url"} object rendered as a
hyperlink. A section "location" renders as a small muted line under the
heading. Comments render as copy-to-clipboard blocks.
Per-claim citations: text, summaries, captions and table cells may cite a
source with [[n]] (1-based index into "sources"); each marker renders as a
superscript link to the numbered source entry. An out-of-range citation, a
citation with no sources, or a [[n]] pasted into a copyable comment or code
block (kept literal) is handled explicitly: invalid ones fail the render,
comments and code stay literal. Chart specs are rendered locally to sanitized
static SVG (bar and line only; no engine dependency). DBML is parsed as a
strict subset (Table/Ref statements with pk, unique, not null, null,
increment, default and note constraints only; enums, table groups, projects,
stubs, table/ref settings and quoted or parameterized types are rejected)
and converted to a Mermaid ER diagram rendered by the same pipeline.
With "kind": "review",
every section whose heading starts with "Finding" must carry severity, location
and at least one comment, some heading must contain "Verdict", findings get an
index with anchor links after the summary, and leftover template placeholders
(<sha>, <number>, <owner>, <repo>) are rejected in the template's fill-in slots
(summary, headings, metadata, location, sources) — content fields may quote
them. The page stamps its own UTC generation time; colors follow the system
light/dark theme.
Mermaid diagrams are rendered locally to sanitized static SVG before the
destination is replaced. Their source remains available in the page, and
renderer/tooling/syntax/safety failures are reported without overwriting an
existing artifact.
"""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET


SCRIPT_DIR = Path(__file__).resolve().parent
OVERLAY_PATH = SCRIPT_DIR / "artifact-overlay.js"


def load_overlay():
    """Overlay JS to embed in generated artifacts; missing file fails closed."""
    try:
        return OVERLAY_PATH.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"cannot read overlay script {OVERLAY_PATH}: {error}") from error


def slug(value):
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip(".-")
    return value[:100] or "repository"


def repository_key(repo):
    common = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    common_path = (repo / common).resolve()
    origin = subprocess.run(
        ["git", "-C", str(repo), "config", "--get", "remote.origin.url"],
        capture_output=True, text=True,
    )
    if origin.returncode not in (0, 1):
        raise ValueError("Cannot read the repository origin")
    url = origin.stdout.strip()
    if "://" in url:
        parsed = urlsplit(url)
        host = parsed.hostname
        if host and parsed.port:
            host += f":{parsed.port}"
        identity = f"{host}/{parsed.path.lstrip('/')}" if host else str(common_path)
    elif re.match(r"(?:[^/@]+@)?[^/:]+:", url):
        host, path = url.split(":", 1)
        identity = f"{host.rsplit('@', 1)[-1]}/{path}"
    else:
        identity = str(common_path)
    identity = identity.removesuffix(".git")
    digest = hashlib.sha256(identity.encode()).hexdigest()[:12]
    local_name = common_path.parent.name if common_path.name == ".git" else common_path.name
    name = identity if url and identity != str(common_path) else local_name
    return f"{slug(name)}-{digest}"


def require_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonempty text")
    return value


def text_list(value, field):
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list of text")
    return [require_text(item, field) for item in value]


def check_keys(mapping, allowed, field):
    unknown = sorted(set(mapping) - set(allowed))
    if unknown:
        raise ValueError(f'{field} has unknown key(s): {", ".join(unknown)}')


def is_public_https_url(url):
    """The one URL rule shared by sources, metadata links and the auto-linker."""
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and bool(parsed.hostname)
                and not parsed.username and not parsed.password
                and not any(ord(char) < 32 for char in url))
    except ValueError:
        return False


def public_https_url(url, field):
    if not is_public_https_url(url):
        raise ValueError(f"{field} must be an HTTPS URL without credentials")
    return url


URL_PATTERN = re.compile(r"https?://[^\s<>\"']+[^\s<>\"'.,;:!?)\]}]")
CITATION_PATTERN = re.compile(r"\[\[(\d{1,3})\]\]")


def autolink(text, field):
    """Escape text for HTML and auto-link bare public https URLs inside it.

    Candidates are matched in the raw text and validated with the same rule as
    source URLs: invalid-scheme or credentialed candidates stay plain escaped
    text, and quoting around a URL cannot leak into the href.
    """
    parts = []
    position = 0
    for match in URL_PATTERN.finditer(text):
        url = match.group(0)
        if not is_public_https_url(url):
            continue
        parts.append(html.escape(text[position:match.start()], quote=True))
        escaped_url = html.escape(url, quote=True)
        parts.append(f'<a href="{escaped_url}" rel="noreferrer">{escaped_url}</a>')
        position = match.end()
    parts.append(html.escape(text[position:], quote=True))
    return "".join(parts)


def rich(value, field, citations=None):
    """Escape text, auto-link https URLs and resolve [[n]] source citations.

    Citation markers only become links when a collector list is passed, which
    render() always does; the markers are then validated against the source
    list before anything is written. Without a collector (comments, metadata,
    code) the markers stay literal text, so an unvalidated [[n]] can never
    become a link.
    """
    text = require_text(value, field)
    if citations is None:
        return autolink(text, field)
    parts = []
    position = 0
    for match in CITATION_PATTERN.finditer(text):
        parts.append(autolink(text[position:match.start()], field))
        number = int(match.group(1))
        citations.append((number, field))
        parts.append(f"\x00cite:{number}\x00")
        position = match.end()
    parts.append(autolink(text[position:], field))
    return "".join(parts)


def text_url_link(value, field):
    check_keys(value, {"text", "url"}, field)
    text = require_text(value.get("text"), f"{field} text")
    url = public_https_url(require_text(value.get("url"), f"{field} url"), f"{field} url")
    return f'<a href="{html.escape(url, quote=True)}" rel="noreferrer">{html.escape(text)}</a>'


def metadata_value(value, field):
    if isinstance(value, dict):
        return text_url_link(value, field)
    return rich(value, field)


def location_value(value, field):
    if isinstance(value, dict):
        return text_url_link(value, field)
    return html.escape(require_text(value, field))


COPY_SCRIPT = """
document.querySelectorAll('.copy').forEach(function (button) {
  var fallback = function () {
    var pre = button.closest('.comment').querySelector('pre');
    var selection = window.getSelection();
    selection.removeAllRanges();
    selection.selectAllChildren(pre);
    var copied = false;
    try { copied = document.execCommand('copy'); } catch (error) {}
    selection.removeAllRanges();
    if (copied) {
      done();
    } else {
      button.textContent = 'Copy failed — select manually';
    }
  };
  var done = function () {
    button.textContent = 'Copied';
    setTimeout(function () { button.textContent = 'Copy'; }, 1500);
  };
  button.addEventListener('click', function () {
    var pre = button.closest('.comment').querySelector('pre');
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(pre.textContent).then(done, fallback);
    } else {
      fallback();
    }
  });
});
"""


def flow_svg(labels, marker_id="arrow"):
    labels = text_list(labels, "flow")
    if not labels:
        return ""
    rows = [textwrap.wrap(label, 48) for label in labels]
    heights = [max(64, len(lines) * 22 + 28) for lines in rows]
    height = sum(heights) + 32 * (len(rows) - 1)
    parts = [f'<svg class="legacy-flow" viewBox="0 0 520 {height}" role="img" aria-label="Flow diagram">'
             f'<defs><marker id="{marker_id}" markerWidth="8" markerHeight="8" refX="4" '
             'refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#2563eb"/></marker></defs>']
    y = 0
    for index, (lines, box_height) in enumerate(zip(rows, heights)):
        if index:
            parts.append(f'<path d="M260,{y - 30} V{y - 8}" stroke="#2563eb" '
                         f'stroke-width="2" marker-end="url(#{marker_id})"/>')
        parts.append(f'<rect x="1" y="{y + 1}" width="518" height="{box_height - 2}" '
                     'rx="8" fill="#eff6ff" stroke="#93c5fd"/>')
        for line_index, line in enumerate(lines):
            parts.append(f'<text x="260" y="{y + 27 + line_index * 22}" text-anchor="middle">'
                         f"{html.escape(line)}</text>")
        y += box_height + 32
    parts.append("</svg>")
    return "".join(parts)


CHART_SERIES = tuple(f"var(--chart-{index})" for index in range(1, 6))


def format_number(value):
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:g}"


def nice_ticks(low, high):
    """Axis ticks on a 1/2/2.5/5 x 10^k grid covering [low, high]."""
    span = high - low
    if span <= 0:
        return [low, low + 1]
    raw_step = span / 5
    magnitude = 10 ** math.floor(math.log10(raw_step))
    step = magnitude * 10
    for multiplier in (1, 2, 2.5, 5, 10):
        if magnitude * multiplier >= raw_step:
            step = magnitude * multiplier
            break
    first = math.floor(low / step) * step
    count = int(math.floor((high - first) / step + 1e-9)) + 1
    return [round(first + index * step, 10) for index in range(count + 1)]


def chart_series(value, field, label_count):
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a nonempty list of series")
    parsed = []
    for index, series in enumerate(value):
        if not isinstance(series, dict):
            raise ValueError(f"{field}[{index}] must be an object")
        check_keys(series, {"name", "values"}, f"{field}[{index}]")
        name = require_text(series.get("name"), f"{field}[{index}] name")
        values = series.get("values")
        if (not isinstance(values, list) or len(values) != label_count
                or not all(isinstance(item, (int, float)) and not isinstance(item, bool)
                           for item in values)):
            raise ValueError(
                f'{field}[{index}] values must be a list of {label_count} numbers '
                f"matching the labels")
        parsed.append((name, [float(item) for item in values]))
    return parsed


def chart_svg(block, diagram_id):
    """Render a bar or line chart as a sanitized static SVG, engine-free."""
    kind = block["kind"]
    labels = text_list(block["labels"], "chart labels")
    series = chart_series(block["series"], "chart series", len(labels))
    title = block.get("title")
    x_label = block.get("xLabel")
    y_label = block.get("yLabel")
    width, height = 640, 380
    left, right, top, bottom = 72, 20, 58, 56
    plot_w, plot_h = width - left - right, height - top - bottom
    all_values = [value for _, values in series for value in values]
    low = min([0.0] + all_values)
    high = max([0.0] + all_values)
    ticks = nice_ticks(low, high)
    lo, hi = ticks[0], ticks[-1]
    if hi <= lo:
        hi = lo + 1

    def y_px(value):
        return top + plot_h - (value - lo) / (hi - lo) * plot_h

    def esc(text):
        return html.escape(str(text), quote=True)

    def series_color(index):
        return CHART_SERIES[index % len(CHART_SERIES)]

    def text_element(x, y, content, size=11, fill="var(--chart-text)", anchor="middle",
                     weight=None, transform=None):
        weight_attribute = f' font-weight="{weight}"' if weight else ""
        transform_attribute = f' transform="{transform}"' if transform else ""
        return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
                f'font-size="{size}" style="fill: {fill}"{weight_attribute} '
                f'font-family="system-ui, sans-serif"{transform_attribute}>{esc(content)}</text>')

    parts = [f'<svg xmlns="{SVG_NAMESPACE}" viewBox="0 0 {width} {height}" role="img">']
    for tick in ticks:
        y = y_px(tick)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" '
                     'style="stroke: var(--chart-grid); stroke-width: 1"/>')
        parts.append(text_element(left - 8, y + 4, format_number(tick), anchor="end"))
    parts.append(f'<line x1="{left}" y1="{y_px(0):.1f}" x2="{left + plot_w}" y2="{y_px(0):.1f}" '
                 'style="stroke: var(--chart-baseline); stroke-width: 1"/>')
    slot = plot_w / len(labels)
    for index, label in enumerate(labels):
        center = left + slot * (index + 0.5)
        for line_index, line in enumerate(textwrap.wrap(label, 14)[:2] or [""]):
            parts.append(text_element(center, y_px(0) + 16 + line_index * 13, line))
    if len(series) > 1:
        estimates = [12 + 6 + 7 * len(name) for name, _ in series]
        x = (width - sum(estimates) - 12 * (len(estimates) - 1)) / 2
        for series_index, (name, _) in enumerate(series):
            color = series_color(series_index)
            parts.append(f'<rect x="{x:.1f}" y="36" width="12" height="12" rx="2" '
                         f'style="fill: {color}"/>')
            parts.append(text_element(x + 18, 46, name, size=12, anchor="start"))
            x += estimates[series_index] + 12
    if kind == "bar":
        group = slot * 0.6
        bar_w = group / len(series)
        for series_index, (name, values) in enumerate(series):
            color = series_color(series_index)
            for value_index, value in enumerate(values):
                x = left + slot * value_index + (slot - group) / 2 + series_index * bar_w
                y_value, y_base = y_px(value), y_px(0)
                parts.append(
                    f'<rect x="{x:.1f}" y="{min(y_value, y_base):.1f}" '
                    f'width="{bar_w * 0.86:.1f}" height="{max(1, abs(y_base - y_value)):.1f}" '
                    f'rx="2" style="fill: {color}"/>')
    else:
        for series_index, (name, values) in enumerate(series):
            color = series_color(series_index)
            points = " ".join(
                f"{left + slot * (index + 0.5):.1f},{y_px(value):.1f}"
                for index, value in enumerate(values))
            parts.append(f'<polyline points="{points}" fill="none" '
                         f'style="stroke: {color}; stroke-width: 2"/>')
            for index, value in enumerate(values):
                parts.append(f'<circle cx="{left + slot * (index + 0.5):.1f}" '
                             f'cy="{y_px(value):.1f}" r="3.5" style="fill: {color}"/>')
    if title:
        parts.append(text_element(width / 2, 20, title, size=14,
                                  fill="var(--chart-title)", weight="600"))
    if x_label:
        parts.append(text_element(left + plot_w / 2, height - 8, x_label))
    if y_label:
        y_mid = top + plot_h / 2
        parts.append(text_element(16, y_mid, y_label, transform=f"rotate(-90 16 {y_mid:.1f})"))
    parts.append("</svg>")
    return sanitize_mermaid_svg("".join(parts), block["caption"], block["text_alt"],
                                diagram_id, origin="Chart")


def strip_dbml_comment(line):
    quote = None
    index = 0
    while index < len(line) - 1:
        char = line[index]
        if quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif line.startswith("//", index):
            return line[:index]
        index += 1
    return line


def split_dbml_constraints(text):
    parts, current, quote = [], [], None
    for char in text:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
        elif char in "'`":
            quote = char
            current.append(char)
        elif char == ",":
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


DBML_HEADER = re.compile(
    r"^Table\s+(?:(?P<schema>[\w]+)\.)?(?P<name>[\w]+|\"[^\"]+\")"
    r"(?:\s+as\s+(?P<alias>[\w]+))?\s*(?P<settings>\[[^\]]*\])?\s*\{$")
DBML_REF = re.compile(
    r"^Ref:\s*(?:(?P<a_schema>[\w]+)\.)?(?P<a>[\w]+)\.(?P<a_col>[\w]+)\s*"
    r"(?P<op><>|>|<|-)\s*"
    r"(?:(?P<b_schema>[\w]+)\.)?(?P<b>[\w]+)\.(?P<b_col>[\w]+)\s*(?P<settings>\[[^\]]*\])?$")
DBML_COLUMN = re.compile(r"^(?P<name>[\w]+)\s+(?P<type>[\w]+)\s*(?:\[(?P<constraints>[^\]]*)\])?$")
DBML_CARDINALITY = {">": ("}o", "||"), "<": ("||", "o{"), "-": ("||", "||"), "<>": ("}o", "o{")}


def dbml_to_mermaid(source, field):
    """Convert a strict DBML subset to a Mermaid ER diagram source.

    Supported: Table (with optional schema qualifier and alias) columns with
    pk/primary key, unique, not null, null, increment, default and note
    constraints, plus one-line `Ref: a.col OP b.col` statements. Everything
    else fails explicitly rather than being guessed at.
    """
    tables, order, refs, current = {}, [], [], None
    for line_number, raw in enumerate(source.splitlines(), start=1):
        location = f"{field} line {line_number}"
        line = strip_dbml_comment(raw).strip()
        if not line:
            continue
        if current is None:
            header = DBML_HEADER.match(line)
            if header:
                if header.group("settings"):
                    raise ValueError(f"{location}: Table settings are not supported")
                name = header.group("name").strip('"')
                if name in tables:
                    raise ValueError(f"{location}: duplicate Table {name}")
                display = f"{header.group('schema')}.{name}" if header.group("schema") else name
                tables[name] = {"display": display, "columns": []}
                order.append(name)
                current = name
                continue
            ref = DBML_REF.match(line)
            if ref:
                if ref.group("settings"):
                    raise ValueError(f"{location}: Ref settings are not supported")
                refs.append((ref.group("a"), ref.group("a_col"), ref.group("op"),
                             ref.group("b"), ref.group("b_col"), location))
                continue
            keyword = line.split(None, 1)[0].rstrip("{").upper()
            if keyword in {"ENUM", "TABLEGROUP", "PROJECT", "STUB", "REF"}:
                raise ValueError(f"{location}: {keyword} blocks are not supported")
            raise ValueError(f"{location}: unsupported DBML statement")
        if line == "}":
            current = None
            continue
        if line.upper().startswith("NOTE"):
            raise ValueError(f"{location}: Table-level Note is not supported")
        column = DBML_COLUMN.match(line)
        if not column:
            raise ValueError(f"{location}: unsupported column syntax (quoted names, "
                             "parameterized types like numeric(10,2) and inline notes "
                             "are not supported)")
        comment_parts, keys = [], []
        for token in split_dbml_constraints(column.group("constraints") or ""):
            token = token.strip()
            if not token:
                continue
            lowered = token.lower()
            if lowered in {"pk", "primary key"}:
                keys.append("PK")
            elif lowered == "unique":
                keys.append("UK")
            elif lowered == "not null":
                comment_parts.append("not null")
            elif lowered in {"null", "increment"}:
                continue
            elif lowered.startswith("note:"):
                note = token.split(":", 1)[1].strip()
                if len(note) < 2 or not (note.startswith("'") and note.endswith("'")):
                    raise ValueError(f"{location}: note must be a single-quoted string")
                comment_parts.append(note[1:-1])
            elif lowered.startswith("default:"):
                default = token.split(":", 1)[1].strip().strip("'`")
                comment_parts.append(f"default {default}")
            else:
                raise ValueError(f'{location}: unsupported column constraint "{token}"')
        tables[current]["columns"].append(
            (column.group("type"), column.group("name"), keys, " ".join(comment_parts)))
    if current is not None:
        raise ValueError(f"{field}: unclosed Table block")
    if not tables:
        raise ValueError(f"{field}: no Table statements found")
    for table_a, column_a, _, table_b, column_b, location in refs:
        for table, column in ((table_a, column_a), (table_b, column_b)):
            if table not in tables:
                raise ValueError(f"{location}: Ref references unknown table {table}")
            if not any(name == column for _, name, _, _ in tables[table]["columns"]):
                raise ValueError(f"{location}: Ref references unknown column {table}.{column}")
    lines = ["erDiagram"]
    aliases = {}
    for index, name in enumerate(order):
        alias = f"t{index}"
        aliases[name] = alias
        columns = tables[name]["columns"]
        if columns:
            lines.append(f"  {alias}[{tables[name]['display']}] {{")
            for column_type, column_name, keys, comment in columns:
                suffix = (" " + ", ".join(keys)) if keys else ""
                suffix += f' "{comment}"' if comment else ""
                lines.append(f"    {column_type} {column_name}{suffix}")
            lines.append("  }")
        else:
            lines.append(f"  {alias}[{tables[name]['display']}]")
    for a, a_col, op, b, _, _ in refs:
        left, right = DBML_CARDINALITY[op]
        lines.append(f"  {aliases[a]} {left}--{right} {aliases[b]} : {a_col}")
    return "\n".join(lines)


def table_columns(value, field):
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a nonempty list")
    parsed = []
    for index, column in enumerate(value):
        if isinstance(column, str):
            parsed.append((require_text(column, f"{field}[{index}]"), "left"))
        elif isinstance(column, dict):
            check_keys(column, {"label", "align"}, f"{field}[{index}]")
            label = require_text(column.get("label"), f"{field}[{index}] label")
            align = column.get("align", "left")
            if align not in {"left", "right", "center"}:
                raise ValueError(f'{field}[{index}] align must be "left", "right" or "center"')
            parsed.append((label, align))
        else:
            raise ValueError(f"{field}[{index}] must be text or an object")
    return parsed


def table_rows(value, field, column_count):
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list of rows")
    parsed = []
    for index, row in enumerate(value):
        if not isinstance(row, list) or len(row) != column_count:
            raise ValueError(f"{field}[{index}] must be a list of {column_count} cells")
        parsed.append([
            require_text(cell, f"{field}[{index}] cell {cell_index}")
            for cell_index, cell in enumerate(row)
        ])
    return parsed


TOP_LEVEL_KEYS = {"kind", "title", "summary", "sections", "metadata", "sources"}
LEGACY_CONTENT_KEYS = {"paragraphs", "steps", "flow", "code", "comments"}
SECTION_KEYS = {"heading", "severity", "location", "blocks", *LEGACY_CONTENT_KEYS}
SOURCE_KEYS = {"label", "url", "date"}
SEVERITIES = ("blocker", "should-fix", "nit", "question")
PLACEHOLDERS = ("<sha>", "<number>", "<owner>", "<repo>")
BLOCK_TYPES = {"text", "steps", "code", "comments", "callout", "comparison", "diagram", "details",
               "table", "chart", "dbml"}
MERMAID_DIRECTORY = Path(__file__).resolve().parent / "mermaid"
MERMAID_CLI = MERMAID_DIRECTORY / "node_modules/.bin/mmdc"
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NAMESPACE)
SAFE_SVG_ELEMENTS = {
    "svg", "g", "defs", "style", "path", "rect", "circle", "ellipse", "line",
    "polyline", "polygon", "text", "tspan", "marker", "clipPath", "filter",
    "feDropShadow", "linearGradient", "radialGradient", "stop", "symbol",
}
SAFE_SVG_ATTRIBUTES = {
    "id", "class", "style", "viewBox", "width", "height", "x", "y", "x1", "x2",
    "y1", "y2", "dx", "dy", "cx", "cy", "r", "rx", "ry", "d", "points",
    "transform", "fill", "fill-rule", "fill-opacity", "stroke", "stroke-width",
    "stroke-dasharray", "stroke-dashoffset", "stroke-linecap", "stroke-linejoin",
    "stroke-opacity", "opacity", "text-anchor", "dominant-baseline",
    "alignment-baseline", "font-family", "font-size", "font-style", "font-weight",
    "marker-start", "marker-mid", "marker-end", "markerWidth", "markerHeight",
    "markerUnits", "refX", "refY", "orient", "offset", "stop-color",
    "stop-opacity", "gradientUnits", "gradientTransform", "spreadMethod",
    "filter", "clip-path", "clip-rule", "stdDeviation",
    "flood-color", "flood-opacity", "role", "aria-label", "aria-labelledby",
    "aria-describedby", "aria-roledescription", "aria-hidden", "name", "data-et", "data-from",
    "data-id", "data-look", "data-to", "data-type",
}
UNSAFE_SVG_TEXT = re.compile(
    r"(?:javascript:|data:|https?://|file:|@import|expression\s*\(|<script|<iframe)",
    re.IGNORECASE,
)
SAFE_FRAGMENT_URL = re.compile(r"url\(\s*#[a-zA-Z_][\w:.-]*\s*\)")


def reject_placeholders(value, field):
    """Reject leftover template placeholders in one fill-in slot.

    Only slots the review template fills with <...> values are scanned
    (summary, headings, metadata, location, sources). Content fields —
    paragraphs, steps, code, comments — may legitimately quote the
    placeholders, e.g. in a review of this tooling itself.
    """
    if isinstance(value, str):
        for pattern in PLACEHOLDERS:
            if pattern in value:
                raise ValueError(f"leftover template placeholder {pattern} in {field}")
    elif isinstance(value, dict):
        reject_placeholders(value.get("text"), field)
        reject_placeholders(value.get("url"), field)


def severity_badge(severity):
    if severity is None:
        return ""
    return f' <span class="severity severity-{severity}">{html.escape(severity)}</span>'


def id_anchor(review, is_finding, finding_count):
    if review and is_finding:
        return f' id="finding-{finding_count}"'
    return ""


def comment_html(comment):
    return (
        '<div class="comment"><div class="comment-head"><span>Suggested comment</span>'
        '<button type="button" class="copy">Copy</button></div>'
        f"<pre>{html.escape(comment)}</pre></div>"
    )


def local_name(value):
    return value.rsplit("}", 1)[-1]


def namespace_svg_ids(root, prefix):
    ids = {}
    for element in root.iter():
        old_id = element.attrib.get("id")
        if old_id:
            ids[old_id] = f"{prefix}-{old_id}"
            element.set("id", ids[old_id])
    for element in root.iter():
        for attribute, value in list(element.attrib.items()):
            for old_id, new_id in ids.items():
                value = value.replace(f"url(#{old_id})", f"url(#{new_id})")
                if value == old_id:
                    value = new_id
                value = re.sub(
                    rf"(?<![\w-])#{re.escape(old_id)}(?![\w-])",
                    f"#{new_id}",
                    value,
                )
            element.set(attribute, value)
        if local_name(element.tag) == "style" and element.text:
            style = element.text
            for old_id, new_id in ids.items():
                style = style.replace(f"url(#{old_id})", f"url(#{new_id})")
                style = re.sub(
                    rf"(?<![\w-])#{re.escape(old_id)}(?![\w-])",
                    f"#{new_id}",
                    style,
                )
            element.text = style


def validate_svg_value(value, field, origin="Mermaid"):
    without_fragments = SAFE_FRAGMENT_URL.sub("", value)
    if "url(" in without_fragments.lower() or UNSAFE_SVG_TEXT.search(without_fragments):
        raise ValueError(f"{origin} SVG contains an unsafe external reference in {field}")


def sanitize_mermaid_svg(svg, caption, text_alt, diagram_id, origin="Mermaid",
                         extra_class=None, aria_hidden=False):
    if "<!DOCTYPE" in svg.upper() or "<!ENTITY" in svg.upper():
        raise ValueError(f"{origin} SVG contains unsupported document declarations")
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as error:
        raise ValueError(f"{origin} produced malformed SVG: {error}") from error
    if root.tag != f"{{{SVG_NAMESPACE}}}svg":
        raise ValueError(f"{origin} output is not an SVG document")
    elements = list(root.iter())
    if len(elements) < 2:
        raise ValueError(f"{origin} produced an empty SVG")
    for element in elements:
        tag = local_name(element.tag)
        if tag not in SAFE_SVG_ELEMENTS:
            raise ValueError(f"{origin} SVG contains unsupported element <{tag}>")
        for attribute, value in element.attrib.items():
            name = local_name(attribute)
            if (name.lower().startswith("on")
                    or (name not in SAFE_SVG_ATTRIBUTES
                        and not re.fullmatch(r"data-[a-zA-Z0-9_-]+", name))):
                raise ValueError(f'{origin} SVG contains unsupported attribute "{name}"')
            validate_svg_value(value, f'attribute "{name}"', origin)
        if tag == "style" and element.text:
            validate_svg_value(element.text, "style content")
    namespace_svg_ids(root, diagram_id)
    title_id = f"{diagram_id}-title"
    description_id = f"{diagram_id}-description"
    title = ET.Element(f"{{{SVG_NAMESPACE}}}title", {"id": title_id})
    title.text = caption
    description = ET.Element(f"{{{SVG_NAMESPACE}}}desc", {"id": description_id})
    description.text = text_alt
    root.insert(0, description)
    root.insert(0, title)
    root.set("role", "img")
    root.set("aria-labelledby", f"{title_id} {description_id}")
    root_class = (root.attrib.get("class", "") + " mermaid-svg").strip()
    if extra_class:
        root_class = f"{root_class} {extra_class}"
    root.set("class", root_class)
    if aria_hidden:
        root.set("aria-hidden", "true")
    root.attrib.pop("aria-roledescription", None)
    return ET.tostring(root, encoding="unicode")


def render_mermaid(source, caption, text_alt, diagram_id, theme="neutral",
                   extra_class=None, aria_hidden=False):
    if re.search(r"%%\s*\{", source) or source.lstrip("\ufeff \t\r\n").startswith("---"):
        raise ValueError(
            "Mermaid directives and frontmatter are not supported; renderer configuration is fixed"
        )
    if not MERMAID_CLI.is_file() or not os.access(MERMAID_CLI, os.X_OK):
        raise ValueError(
            "Mermaid CLI is not installed. Run `npm ci --prefix scripts/mermaid` "
            "from the config repository, then approve the pinned Puppeteer install script if npm requests it"
        )
    config = {
        "securityLevel": "strict",
        "startOnLoad": False,
        "htmlLabels": False,
        "fontFamily": "system-ui",
        "theme": theme,
    }
    puppeteer = {
        "args": [
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-domain-reliability",
            "--proxy-server=http://127.0.0.1:9",
            "--proxy-bypass-list=<-loopback>",
        ],
    }
    with tempfile.TemporaryDirectory(prefix="agent-explainer-mermaid-") as temporary:
        work = Path(temporary)
        source_path = work / "diagram.mmd"
        output_path = work / "diagram.svg"
        config_path = work / "mermaid.json"
        puppeteer_path = work / "puppeteer.json"
        source_path.write_text(source, encoding="utf-8")
        config_path.write_text(json.dumps(config), encoding="utf-8")
        puppeteer_path.write_text(json.dumps(puppeteer), encoding="utf-8")
        command = [
            str(MERMAID_CLI), "--quiet", "--input", str(source_path),
            "--output", str(output_path), "--configFile", str(config_path),
            "--puppeteerConfigFile", str(puppeteer_path),
            "--backgroundColor", "transparent", "--no-font-embed",
            "--svgId", diagram_id,
        ]
        try:
            result = subprocess.run(
                command, cwd=MERMAID_DIRECTORY, capture_output=True, text=True,
                timeout=45, check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise ValueError("Mermaid rendering timed out") from error
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            detail = detail.splitlines()[-1] if detail else "unknown renderer error"
            raise ValueError(f"Mermaid rendering failed: {detail}")
        if not output_path.is_file():
            raise ValueError("Mermaid renderer succeeded without producing SVG output")
        return sanitize_mermaid_svg(
            output_path.read_text(encoding="utf-8"), caption, text_alt, diagram_id,
            extra_class=extra_class, aria_hidden=aria_hidden,
        )


def diagram_pair(block, field, diagram_id, mermaid_renderer):
    """Render one diagram twice: neutral theme for light, dark theme for dark.

    Both sanitized variants are embedded; the page CSS shows the one matching
    the system theme (print forces light). The dark copy is aria-hidden so
    assistive technology sees the diagram once.
    """
    caption = block["caption"]
    text_alt = block["text_alt"]
    source = block["source"]
    light = mermaid_renderer(source, caption, text_alt, diagram_id,
                             extra_class="diagram-light")
    dark = mermaid_renderer(
        source, caption, text_alt, f"{diagram_id}-dark",
        theme="dark", extra_class="diagram-dark", aria_hidden=True,
    )
    return light, dark


def comparison_side(value, field):
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    check_keys(value, {"label", "value", "text"}, field)
    label = require_text(value.get("label"), f"{field} label")
    primary = require_text(value.get("value"), f"{field} value")
    explanation = value.get("text")
    if explanation is not None:
        explanation = require_text(explanation, f"{field} text")
    return label, primary, explanation


def validate_block(block, field, allow_details=True):
    if not isinstance(block, dict):
        raise ValueError(f"{field} must be an object")
    block_type = require_text(block.get("type"), f"{field} type")
    if block_type not in BLOCK_TYPES:
        raise ValueError(f'{field} type must be one of {", ".join(sorted(BLOCK_TYPES))}')
    allowed = {
        "text": {"type", "text"},
        "steps": {"type", "items"},
        "code": {"type", "code"},
        "comments": {"type", "items"},
        "callout": {"type", "title", "text"},
        "comparison": {"type", "left", "right", "caption"},
        "diagram": {"type", "source", "caption", "text_alt"},
        "details": {"type", "summary", "blocks"},
        "table": {"type", "columns", "rows", "caption"},
        "chart": {"type", "kind", "labels", "series", "title", "xLabel", "yLabel",
                  "caption", "text_alt"},
        "dbml": {"type", "source", "caption", "text_alt"},
    }[block_type]
    check_keys(block, allowed, field)
    if block_type == "text":
        require_text(block.get("text"), f"{field} text")
    elif block_type in {"steps", "comments"}:
        if not text_list(block.get("items"), f"{field} items"):
            raise ValueError(f"{field} items must not be empty")
    elif block_type == "code":
        require_text(block.get("code"), f"{field} code")
    elif block_type == "callout":
        require_text(block.get("title"), f"{field} title")
        require_text(block.get("text"), f"{field} text")
    elif block_type == "comparison":
        comparison_side(block.get("left"), f"{field} left")
        comparison_side(block.get("right"), f"{field} right")
        if "caption" in block:
            require_text(block["caption"], f"{field} caption")
    elif block_type == "diagram":
        require_text(block.get("source"), f"{field} source")
        require_text(block.get("caption"), f"{field} caption")
        require_text(block.get("text_alt"), f"{field} text_alt")
    elif block_type == "table":
        columns = table_columns(block.get("columns"), f"{field} columns")
        table_rows(block.get("rows"), f"{field} rows", len(columns))
        if "caption" in block:
            require_text(block["caption"], f"{field} caption")
    elif block_type == "chart":
        if block.get("kind") not in {"bar", "line"}:
            raise ValueError(f'{field} kind must be "bar" or "line"')
        labels = text_list(block.get("labels"), f"{field} labels")
        if not labels:
            raise ValueError(f"{field} labels must not be empty")
        chart_series(block.get("series"), f"{field} series", len(labels))
        for optional in ("title", "xLabel", "yLabel"):
            if block.get(optional) is not None:
                require_text(block[optional], f"{field} {optional}")
        require_text(block.get("caption"), f"{field} caption")
        require_text(block.get("text_alt"), f"{field} text_alt")
    elif block_type == "dbml":
        require_text(block.get("source"), f"{field} source")
        require_text(block.get("caption"), f"{field} caption")
        require_text(block.get("text_alt"), f"{field} text_alt")
    elif block_type == "details":
        if not allow_details:
            raise ValueError("details blocks cannot be nested")
        require_text(block.get("summary"), f"{field} summary")
        nested = block.get("blocks")
        if not isinstance(nested, list) or not nested:
            raise ValueError(f"{field} blocks must be a nonempty list")
        for index, child in enumerate(nested):
            validate_block(child, f"{field} blocks[{index}]", allow_details=False)
            if child["type"] in {"diagram", "chart", "dbml"}:
                raise ValueError(f"{child['type']} blocks cannot be nested inside details")
    return block_type


def render_block(block, field, diagram_id, mermaid_renderer, citations):
    block_type = validate_block(block, field)
    if block_type == "text":
        return f"<p>{rich(block['text'], f'{field} text', citations)}</p>"
    if block_type == "steps":
        return "<ol>" + "".join(
            f"<li>{rich(item, f'{field} item', citations)}</li>" for item in block["items"]
        ) + "</ol>"
    if block_type == "code":
        return f"<pre><code>{html.escape(block['code'])}</code></pre>"
    if block_type == "comments":
        return "".join(comment_html(comment) for comment in block["items"])
    if block_type == "callout":
        return (
            '<aside class="callout"><strong>'
            f"{html.escape(block['title'])}</strong>"
            f"<p>{rich(block['text'], f'{field} text', citations)}</p></aside>"
        )
    if block_type == "comparison":
        left = comparison_side(block["left"], f"{field} left")
        right = comparison_side(block["right"], f"{field} right")

        def side_html(side, side_class):
            label, primary, explanation = side
            detail = f"<p>{rich(explanation, field, citations)}</p>" if explanation else ""
            return (
                f'<div class="comparison-side {side_class}">'
                f'<div class="comparison-label">{html.escape(label)}</div>'
                f'<div class="comparison-value">{rich(primary, field, citations)}</div>{detail}</div>'
            )

        caption = (
            f'<p class="caption">{rich(block["caption"], f"{field} caption", citations)}</p>'
            if "caption" in block else ""
        )
        return (
            '<div class="comparison">'
            f'{side_html(left, "comparison-left")}{side_html(right, "comparison-right")}'
            f"</div>{caption}"
        )
    if block_type == "diagram":
        light_svg, dark_svg = diagram_pair(block, field, diagram_id, mermaid_renderer)
        return (
            '<figure class="diagram">'
            f"{light_svg}{dark_svg}"
            f"<figcaption>{rich(block['caption'], f'{field} caption', citations)}</figcaption>"
            '<details class="diagram-source"><summary>Mermaid source</summary>'
            f"<pre><code>{html.escape(block['source'])}</code></pre></details></figure>"
        )
    if block_type == "table":
        columns = table_columns(block["columns"], f"{field} columns")
        rows = table_rows(block["rows"], f"{field} rows", len(columns))
        head = "".join(
            f'<th style="text-align:{align}">'
            f"{rich(label, f'{field} column', citations)}</th>"
            for label, align in columns
        )
        body_rows = "".join(
            "<tr>" + "".join(
                f'<td style="text-align:{align}">'
                f"{rich(cell, f'{field} cell', citations)}</td>"
                for cell, (_, align) in zip(row, columns)
            ) + "</tr>"
            for row in rows
        )
        caption = (
            f'<p class="caption">{rich(block["caption"], f"{field} caption", citations)}</p>'
            if "caption" in block else ""
        )
        return (f'<table class="data-table"><thead><tr>{head}</tr></thead>'
                f"<tbody>{body_rows}</tbody></table>{caption}")
    if block_type == "chart":
        svg = chart_svg(block, diagram_id)
        spec = json.dumps(
            {key: value for key, value in block.items() if key != "type"},
            indent=2, ensure_ascii=False,
        )
        return (
            '<figure class="diagram">'
            f'{svg}<figcaption>{rich(block["caption"], f"{field} caption", citations)}</figcaption>'
            '<details class="diagram-source"><summary>Chart data</summary>'
            f"<pre><code>{html.escape(spec)}</code></pre></details></figure>"
        )
    if block_type == "dbml":
        mermaid_source = dbml_to_mermaid(block["source"], f"{field} source")
        dbml_block = {**block, "source": mermaid_source}
        light_svg, dark_svg = diagram_pair(dbml_block, field, diagram_id, mermaid_renderer)
        return (
            '<figure class="diagram">'
            f"{light_svg}{dark_svg}"
            f'<figcaption>{rich(block["caption"], f"{field} caption", citations)}</figcaption>'
            '<details class="diagram-source"><summary>DBML source</summary>'
            f"<pre><code>{html.escape(block['source'])}</code></pre></details></figure>"
        )
    nested = "".join(
        render_block(
            child, f"{field} blocks[{index}]", f"{diagram_id}-{index}", mermaid_renderer,
            citations,
        )
        for index, child in enumerate(block["blocks"])
    )
    return (
        f'<details class="supporting"><summary>{html.escape(block["summary"])}</summary>'
        f'<div class="details-body">{nested}</div></details>'
    )


def direct_comments(section):
    if "blocks" in section:
        return [
            comment
            for block in section["blocks"]
            if isinstance(block, dict) and block.get("type") == "comments"
            for comment in block.get("items", [])
        ]
    return text_list(section.get("comments", []), "comments")


def render(data, mermaid_renderer=None, overlay=True, generator="agent-explainer"):
    if mermaid_renderer is None:
        mermaid_renderer = render_mermaid
    if not isinstance(data, dict):
        raise ValueError("Input must be a JSON object")
    check_keys(data, TOP_LEVEL_KEYS, "input")
    kind = data.get("kind")
    if kind is not None and kind != "review":
        raise ValueError('kind must be "review" when present')
    review = kind == "review"
    citations = []
    title = html.escape(require_text(data.get("title"), "title"))
    summary_text = require_text(data.get("summary"), "summary")
    if review:
        reject_placeholders(summary_text, "summary")
    summary = rich(summary_text, "summary", citations)
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object of text fields")
    meta_parts = []
    for key, value in metadata.items():
        key_text = require_text(key, "metadata key")
        if review:
            reject_placeholders(value, f'metadata "{key_text}"')
        meta_parts.append(f"{html.escape(key_text)}: {metadata_value(value, 'metadata value')}")
    meta = " · ".join(meta_parts)
    sections = data.get("sections", [])
    if not isinstance(sections, list):
        raise ValueError("sections must be a list")
    body = []
    findings = []
    for section_index, section in enumerate(sections):
        if not isinstance(section, dict):
            raise ValueError("Each section must be an object")
        check_keys(section, SECTION_KEYS, "section")
        heading_text = require_text(section.get("heading"), "section heading")
        if review:
            reject_placeholders(heading_text, "section heading")
        heading = html.escape(heading_text)
        if "blocks" in section and LEGACY_CONTENT_KEYS.intersection(section):
            mixed = ", ".join(sorted(LEGACY_CONTENT_KEYS.intersection(section)))
            raise ValueError(
                f'section "{heading_text}" cannot mix blocks with legacy content field(s): {mixed}'
            )
        blocks = section.get("blocks")
        if blocks is not None:
            if not isinstance(blocks, list):
                raise ValueError("section blocks must be a list")
            for block_index, block in enumerate(blocks):
                validate_block(block, f"section blocks[{block_index}]")
        severity = section.get("severity")
        if severity is not None and severity not in SEVERITIES:
            raise ValueError(f'severity must be one of {", ".join(SEVERITIES)}')
        is_finding = heading_text.startswith("Finding")
        if review and is_finding:
            if severity is None:
                raise ValueError(f'Finding section "{heading_text}" must have a severity')
            if "location" not in section:
                raise ValueError(f'Finding section "{heading_text}" must have a location')
            if not direct_comments(section):
                raise ValueError(f'Finding section "{heading_text}" must have at least one comment')
            findings.append(heading_text)
        body.append(f'<section{id_anchor(review, is_finding, len(findings))}>'
                    f"<h2>{heading}{severity_badge(severity)}</h2>")
        if "location" in section:
            if review:
                reject_placeholders(section["location"], "section location")
            body.append(f'<p class="location">{location_value(section["location"], "section location")}</p>')
        if blocks is not None:
            for block_index, block in enumerate(blocks):
                body.append(render_block(
                    block, f"section blocks[{block_index}]",
                    f"diagram-{section_index}-{block_index}", mermaid_renderer, citations,
                ))
        else:
            for paragraph in text_list(section.get("paragraphs", []), "paragraphs"):
                body.append(f"<p>{rich(paragraph, 'paragraph', citations)}</p>")
            steps = text_list(section.get("steps", []), "steps")
            if steps:
                body.append("<ol>" + "".join(
                    f"<li>{rich(step, 'step', citations)}</li>" for step in steps
                ) + "</ol>")
            body.append(flow_svg(section.get("flow", []), f"arrow-{section_index}"))
            if "code" in section:
                body.append(
                    "<pre><code>" + html.escape(require_text(section["code"], "code"))
                    + "</code></pre>"
                )
            for comment in text_list(section.get("comments", []), "comments"):
                body.append(comment_html(comment))
        body.append("</section>")
    if review and not any("Verdict" in section["heading"] for section in sections):
        raise ValueError('a review needs a section whose heading contains "Verdict"')
    index = ""
    if findings:
        items = "".join(
            f'<li><a href="#finding-{number}">{html.escape(heading)}</a></li>'
            for number, heading in enumerate(findings, start=1)
        )
        index = f'<nav class="index" aria-label="Findings index"><strong>Findings</strong><ol>{items}</ol></nav>'
    sources = data.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("sources must be a list")
    if citations and not sources:
        raise ValueError("citations ([[n]]) require at least one source")
    if sources:
        body.append("<section><h2>Sources</h2><ul>")
        for source_number, source in enumerate(sources, start=1):
            if not isinstance(source, dict):
                raise ValueError("Each source must be an object")
            check_keys(source, SOURCE_KEYS, "source")
            if review:
                reject_placeholders(source.get("label"), "source label")
                reject_placeholders(source.get("url"), "source URL")
            url = public_https_url(require_text(source.get("url"), "source URL"), "source URL")
            label = html.escape(require_text(source.get("label"), "source label"))
            date = source.get("date")
            date_html = ""
            if date is not None:
                date = require_text(date, "source date")
                date_html = f' <span class="caption">({html.escape(date)})</span>'
            body.append(f'<li id="source-{source_number}"><a href="{html.escape(url, quote=True)}" '
                        f'rel="noreferrer">{label}</a>{date_html}</li>')
        body.append("</ul></section>")
    for number, field_name in citations:
        if not 1 <= number <= len(sources):
            raise ValueError(
                f"citation [[{number}]] in {field_name} does not match any source (1..{len(sources)})")
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    script_hash = base64.b64encode(hashlib.sha256(COPY_SCRIPT.encode("utf-8")).digest()).decode("ascii")
    overlay_tag = ""
    if overlay:
        overlay_source = load_overlay()
        overlay_hash = base64.b64encode(hashlib.sha256(overlay_source.encode("utf-8")).digest()).decode("ascii")
        csp = (
            f"default-src 'none'; style-src 'unsafe-inline'; "
            f"script-src 'sha256-{script_hash}' 'sha256-{overlay_hash}'; "
            f"connect-src http://127.0.0.1:8787 http://localhost:8787; "
            f"base-uri 'none'; form-action 'none'"
        )
        overlay_tag = f"<script>{overlay_source}</script>"
    else:
        csp = (
            f"default-src 'none'; style-src 'unsafe-inline'; "
            f"script-src 'sha256-{script_hash}'; base-uri 'none'; form-action 'none'"
        )
    generator_text = html.escape(require_text(generator, "generator"))
    html_output = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<meta name="referrer" content="no-referrer"><meta name="agent-generator" content="{generator_text}"><title>{title}</title>
<style>
*{{box-sizing:border-box}}
:root{{color-scheme:light dark;--bg:#f6f7fb;--fg:#1b2340;--muted:#5a6478;--border:#d9deea;--pre-bg:#e9edf5;--accent:#4f46e5;--link:#4338ca;--box-bg:#eef2ff;--box-border:#c7d2fe;--btn-bg:#ffffff;--btn-border:#9aa4bb;--btn-fg:#1b2340;--good:#15803d;--good-bg:#ecfdf5;--bad:#b91c1c;--bad-bg:#fef2f2;--diagram-bg:#ffffff;--chart-grid:#e5e9f2;--chart-baseline:#9aa4bb;--chart-text:#5a6478;--chart-title:#1b2340;--chart-1:#4f46e5;--chart-2:#0d9488;--chart-3:#d97706;--chart-4:#e11d48;--chart-5:#7c3aed}}
@media(prefers-color-scheme:dark){{:root{{--bg:#0d1322;--fg:#e3e8f4;--muted:#97a2b8;--border:#2c3650;--pre-bg:#1a2336;--accent:#818cf8;--link:#a5b4fc;--box-bg:#1a2336;--box-border:#3b4763;--btn-bg:#1a2336;--btn-border:#5a6478;--btn-fg:#e3e8f4;--good:#6ee7a0;--good-bg:#0f2a1d;--bad:#fca5a5;--bad-bg:#3b171b;--diagram-bg:#141c30;--chart-grid:#2c3650;--chart-baseline:#5a6478;--chart-text:#97a2b8;--chart-title:#e3e8f4;--chart-1:#818cf8;--chart-2:#2dd4bf;--chart-3:#fbbf24;--chart-4:#fb7185;--chart-5:#a78bfa}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:17px/1.65 system-ui,sans-serif}}
main{{max-width:900px;margin:auto;padding:36px 24px 72px}} h1{{font-size:2rem;line-height:1.2}}
h2{{font-size:1.3rem;line-height:1.3}} .summary{{font-size:1.15rem}} .meta{{color:var(--muted);font-size:.9rem}}
.location{{color:var(--muted);font-size:.85rem}}
section{{margin-top:30px;border-top:1px solid var(--border);padding-top:12px}} p,li{{overflow-wrap:anywhere}}
li{{margin:.4em 0}} pre{{overflow:auto;padding:18px;background:var(--pre-bg);border-radius:8px;font-size:.85rem}}
.legacy-flow{{display:block;width:100%;max-width:520px;margin:24px auto}}
.legacy-flow text{{font:16px system-ui,sans-serif;fill:var(--fg)}}
.legacy-flow rect{{fill:var(--box-bg);stroke:var(--box-border)}} .legacy-flow > path{{stroke:var(--accent)}} .legacy-flow marker path{{fill:var(--accent)}}
a{{color:var(--link)}}
.callout{{margin:18px 0;padding:14px 16px;border-left:3px solid var(--accent);border-radius:0 8px 8px 0;background:var(--box-bg)}}
.callout strong{{display:block;margin-bottom:4px}} .callout p{{margin:0}}
.comparison{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:18px 0}}
.comparison-side{{padding:15px;border:1px solid;border-radius:9px}}
.comparison-left{{color:var(--good);background:var(--good-bg)}} .comparison-right{{color:var(--bad);background:var(--bad-bg)}}
.comparison-label{{font-size:.75rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase}}
.comparison-value{{margin:.25rem 0;font-size:1.18rem;font-weight:750}} .comparison-side p{{margin:.25rem 0 0}}
.caption,figcaption{{color:var(--muted);font-size:.85rem}}
figure.diagram{{margin:22px 0}} .diagram .mermaid-svg{{display:block;width:100%;height:auto;max-width:100%;margin:0 auto;padding:12px;border:1px solid var(--border);border-radius:9px;background:var(--diagram-bg)!important}}
figure.diagram .diagram-dark{{display:none}}
@media(prefers-color-scheme:dark){{figure.diagram .diagram-light{{display:none}}figure.diagram .diagram-dark{{display:block}}}}
figure.diagram figcaption{{margin-top:8px}}
details{{margin:14px 0;border-top:1px solid var(--border);padding-top:10px}}
summary{{cursor:pointer;font-weight:650}} details[open] summary{{margin-bottom:10px}}
.details-body{{font-size:.94rem}} .diagram-source pre{{white-space:pre-wrap;overflow-wrap:anywhere}}
summary:focus-visible,a:focus-visible,.copy:focus-visible{{outline:3px solid var(--accent);outline-offset:3px}}
.severity{{font-size:.72rem;font-weight:600;border:1px solid;border-radius:999px;padding:.1em .6em;white-space:nowrap}}
.severity-blocker{{color:#b91c1c;border-color:#fca5a5;background:#fef2f2}}
.severity-should-fix{{color:#b45309;border-color:#fcd34d;background:#fffbeb}}
.severity-nit{{color:#475569;border-color:#cbd5e1;background:#f1f5f9}}
.severity-question{{color:#6d28d9;border-color:#c4b5fd;background:#f5f3ff}}
@media(prefers-color-scheme:dark){{.severity-blocker{{color:#fca5a5;border-color:#991b1b;background:#450a0a}}.severity-should-fix{{color:#fcd34d;border-color:#92400e;background:#451a03}}.severity-nit{{color:#94a3b8;border-color:#475569;background:#1e293b}}.severity-question{{color:#c4b5fd;border-color:#5b21b6;background:#2e1065}}}}
.index{{margin-top:24px;padding:10px 18px;border:1px solid var(--border);border-radius:8px;background:var(--box-bg);font-size:.95rem}}
.index ol{{margin:.3em 0 0}}
.comment{{margin:14px 0;border:1px solid var(--border);border-radius:8px;overflow:hidden}}
.comment-head{{display:flex;justify-content:space-between;align-items:center;padding:6px 12px;background:var(--box-bg);font-size:.8rem;color:var(--muted)}}
.copy{{border:1px solid var(--btn-border);background:var(--btn-bg);color:var(--btn-fg);border-radius:6px;padding:2px 12px;font-size:.8rem;cursor:pointer}}
.copy:hover{{border-color:var(--accent);color:var(--accent)}}
.comment pre{{border-radius:0;margin:0;white-space:pre-wrap;overflow-wrap:anywhere}}
.data-table{{border-collapse:collapse;width:100%;margin:18px 0;font-size:.92rem}}
.data-table th,.data-table td{{border:1px solid var(--border);padding:7px 10px;vertical-align:top}}
.data-table th{{background:var(--box-bg);font-weight:650}}
sup.cite a{{color:var(--accent);text-decoration:none;font-weight:600}} sup.cite a:hover{{text-decoration:underline}}
@media(max-width:600px){{main{{padding:20px 16px}}h1{{font-size:1.6rem}}.comparison{{grid-template-columns:1fr}}}}
@media print{{:root{{color-scheme:light;--bg:#f6f7fb;--fg:#1b2340;--muted:#5a6478;--border:#d9deea;--pre-bg:#e9edf5;--accent:#4f46e5;--link:#4338ca;--box-bg:#eef2ff;--box-border:#c7d2fe;--btn-bg:#ffffff;--btn-border:#9aa4bb;--btn-fg:#1b2340;--good:#15803d;--good-bg:#ecfdf5;--bad:#b91c1c;--bad-bg:#fef2f2;--diagram-bg:#ffffff;--chart-grid:#e5e9f2;--chart-baseline:#9aa4bb;--chart-text:#5a6478;--chart-title:#1b2340;--chart-1:#4f46e5;--chart-2:#0d9488;--chart-3:#d97706;--chart-4:#e11d48;--chart-5:#7c3aed}}.severity-blocker{{color:#b91c1c;border-color:#fca5a5;background:#fef2f2}}.severity-should-fix{{color:#b45309;border-color:#fcd34d;background:#fffbeb}}.severity-nit{{color:#475569;border-color:#cbd5e1;background:#f1f5f9}}.severity-question{{color:#6d28d9;border-color:#c4b5fd;background:#f5f3ff}}body{{background:white}}main{{padding:0}}pre{{white-space:pre-wrap}}.copy{{display:none}}details:not([open])>:not(summary){{display:block!important}}figure.diagram .diagram-dark{{display:none!important}}figure.diagram,.comparison,.callout,.data-table{{break-inside:avoid}}}}
</style></head><body><main><h1>{title}</h1><p class="meta">{meta}</p>
<p class="meta generated">Generated {generated} by agent-explainer.py</p>
<p class="summary">{summary}</p>{index}{''.join(body)}
<script>{COPY_SCRIPT}</script>{overlay_tag}</main></body></html>
"""
    for number in sorted({number for number, _ in citations}):
        html_output = html_output.replace(
            f"\x00cite:{number}\x00",
            f'<sup class="cite"><a href="#source-{number}">[{number}]</a></sup>')
    if "\x00" in html_output:
        raise ValueError("internal citation placeholder survived rendering")
    return html_output


def save(repo, topic, data, home, mermaid_renderer=None, overlay=True, generator="agent-explainer"):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}", topic):
        raise ValueError("topic must be a stable slug of letters, numbers, underscores or hyphens")
    content = render(data, mermaid_renderer, overlay=overlay, generator=generator)
    root = home / ".local/share/agent-explainers"
    directory = root / repository_key(repo)
    if directory.resolve().is_relative_to(repo.resolve()):
        raise ValueError("Artifact destination is inside the repository; refusing to write")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = directory / f"{topic}.html"
    if destination.is_symlink():
        raise ValueError("Artifact destination is a symlink; refusing to replace it")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return destination


def open_page(path):
    command = ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
    subprocess.run(command, check=True, capture_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--topic", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--no-overlay", action="store_true",
                        help="omit the comment feedback overlay from the generated artifact")
    parser.add_argument("--generator", default="agent-explainer",
                        help="harness recorded in the agent-generator meta tag")
    args = parser.parse_args()
    try:
        path = save(args.repo.resolve(), args.topic, json.loads(args.input.read_text()), Path.home(),
                    overlay=not args.no_overlay, generator=args.generator)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Explanation not saved: {error}", file=sys.stderr)
        return 1
    print(f"Saved explanation: {path}")
    if not args.no_open:
        try:
            open_page(path)
        except (OSError, subprocess.CalledProcessError):
            print(f"Could not open the browser. Open this saved file manually: {path}", file=sys.stderr)
            return 1
        print("Opened the local explanation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

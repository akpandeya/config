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
    {"type": "comments", "items": ["pasteable suggested comment"]}]}],
  "metadata": {"Revision": "abc123" | {"text": "base abc123", "url": "https://..."}},
  "sources": [{"label": "...", "url": "https://..."}]}
All content is plain text, not HTML; optional fields may be omitted and unknown
keys are rejected before anything is written. A section must use either ordered
blocks or legacy content fields, never both. Bare public https URLs in text
are auto-linked; http:// or credentialed URLs stay plain text. Metadata values
may be plain text (auto-linked) or a {"text", "url"} object rendered as a
hyperlink. A section "location" renders as a small muted line under the
heading. Comments render as copy-to-clipboard blocks. With "kind": "review",
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
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET


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


def rich(value, field):
    """Escape text for HTML and auto-link bare public https URLs inside it.

    Candidates are matched in the raw text and validated with the same rule as
    source URLs: invalid-scheme or credentialed candidates stay plain escaped
    text, and quoting around a URL cannot leak into the href.
    """
    text = require_text(value, field)
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


TOP_LEVEL_KEYS = {"kind", "title", "summary", "sections", "metadata", "sources"}
LEGACY_CONTENT_KEYS = {"paragraphs", "steps", "flow", "code", "comments"}
SECTION_KEYS = {"heading", "severity", "location", "blocks", *LEGACY_CONTENT_KEYS}
SOURCE_KEYS = {"label", "url"}
SEVERITIES = ("blocker", "should-fix", "nit", "question")
PLACEHOLDERS = ("<sha>", "<number>", "<owner>", "<repo>")
BLOCK_TYPES = {"text", "steps", "code", "comments", "callout", "comparison", "diagram", "details"}
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
    "aria-describedby", "aria-roledescription", "name", "data-et", "data-from",
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


def validate_svg_value(value, field):
    without_fragments = SAFE_FRAGMENT_URL.sub("", value)
    if "url(" in without_fragments.lower() or UNSAFE_SVG_TEXT.search(without_fragments):
        raise ValueError(f"Mermaid SVG contains an unsafe external reference in {field}")


def sanitize_mermaid_svg(svg, caption, text_alt, diagram_id):
    if "<!DOCTYPE" in svg.upper() or "<!ENTITY" in svg.upper():
        raise ValueError("Mermaid SVG contains unsupported document declarations")
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as error:
        raise ValueError(f"Mermaid produced malformed SVG: {error}") from error
    if root.tag != f"{{{SVG_NAMESPACE}}}svg":
        raise ValueError("Mermaid output is not an SVG document")
    elements = list(root.iter())
    if len(elements) < 2:
        raise ValueError("Mermaid produced an empty SVG")
    for element in elements:
        tag = local_name(element.tag)
        if tag not in SAFE_SVG_ELEMENTS:
            raise ValueError(f"Mermaid SVG contains unsupported element <{tag}>")
        for attribute, value in element.attrib.items():
            name = local_name(attribute)
            if (name.lower().startswith("on")
                    or (name not in SAFE_SVG_ATTRIBUTES
                        and not re.fullmatch(r"data-[a-zA-Z0-9_-]+", name))):
                raise ValueError(f'Mermaid SVG contains unsupported attribute "{name}"')
            validate_svg_value(value, f'attribute "{name}"')
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
    root.set("class", (root.attrib.get("class", "") + " mermaid-svg").strip())
    root.attrib.pop("aria-roledescription", None)
    return ET.tostring(root, encoding="unicode")


def render_mermaid(source, caption, text_alt, diagram_id):
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
        "theme": "neutral",
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
        )


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
    elif block_type == "details":
        if not allow_details:
            raise ValueError("details blocks cannot be nested")
        require_text(block.get("summary"), f"{field} summary")
        nested = block.get("blocks")
        if not isinstance(nested, list) or not nested:
            raise ValueError(f"{field} blocks must be a nonempty list")
        for index, child in enumerate(nested):
            validate_block(child, f"{field} blocks[{index}]", allow_details=False)
            if child["type"] == "diagram":
                raise ValueError("diagram blocks cannot be nested inside details")
    return block_type


def render_block(block, field, diagram_id, mermaid_renderer):
    block_type = validate_block(block, field)
    if block_type == "text":
        return f"<p>{rich(block['text'], f'{field} text')}</p>"
    if block_type == "steps":
        return "<ol>" + "".join(
            f"<li>{rich(item, f'{field} item')}</li>" for item in block["items"]
        ) + "</ol>"
    if block_type == "code":
        return f"<pre><code>{html.escape(block['code'])}</code></pre>"
    if block_type == "comments":
        return "".join(comment_html(comment) for comment in block["items"])
    if block_type == "callout":
        return (
            '<aside class="callout"><strong>'
            f"{html.escape(block['title'])}</strong>"
            f"<p>{rich(block['text'], f'{field} text')}</p></aside>"
        )
    if block_type == "comparison":
        left = comparison_side(block["left"], f"{field} left")
        right = comparison_side(block["right"], f"{field} right")

        def side_html(side, side_class):
            label, primary, explanation = side
            detail = f"<p>{rich(explanation, field)}</p>" if explanation else ""
            return (
                f'<div class="comparison-side {side_class}">'
                f'<div class="comparison-label">{html.escape(label)}</div>'
                f'<div class="comparison-value">{rich(primary, field)}</div>{detail}</div>'
            )

        caption = (
            f'<p class="caption">{rich(block["caption"], f"{field} caption")}</p>'
            if "caption" in block else ""
        )
        return (
            '<div class="comparison">'
            f'{side_html(left, "comparison-left")}{side_html(right, "comparison-right")}'
            f"</div>{caption}"
        )
    if block_type == "diagram":
        svg = mermaid_renderer(
            block["source"], block["caption"], block["text_alt"], diagram_id,
        )
        return (
            '<figure class="diagram">'
            f"{svg}<figcaption>{rich(block['caption'], f'{field} caption')}</figcaption>"
            '<details class="diagram-source"><summary>Mermaid source</summary>'
            f"<pre><code>{html.escape(block['source'])}</code></pre></details></figure>"
        )
    nested = "".join(
        render_block(
            child, f"{field} blocks[{index}]", f"{diagram_id}-{index}", mermaid_renderer,
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


def render(data, mermaid_renderer=None):
    if mermaid_renderer is None:
        mermaid_renderer = render_mermaid
    if not isinstance(data, dict):
        raise ValueError("Input must be a JSON object")
    check_keys(data, TOP_LEVEL_KEYS, "input")
    kind = data.get("kind")
    if kind is not None and kind != "review":
        raise ValueError('kind must be "review" when present')
    review = kind == "review"
    title = html.escape(require_text(data.get("title"), "title"))
    summary_text = require_text(data.get("summary"), "summary")
    if review:
        reject_placeholders(summary_text, "summary")
    summary = rich(summary_text, "summary")
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
                    f"diagram-{section_index}-{block_index}", mermaid_renderer,
                ))
        else:
            for paragraph in text_list(section.get("paragraphs", []), "paragraphs"):
                body.append(f"<p>{rich(paragraph, 'paragraph')}</p>")
            steps = text_list(section.get("steps", []), "steps")
            if steps:
                body.append("<ol>" + "".join(
                    f"<li>{rich(step, 'step')}</li>" for step in steps
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
    if sources:
        body.append("<section><h2>Sources</h2><ul>")
        for source in sources:
            if not isinstance(source, dict):
                raise ValueError("Each source must be an object")
            check_keys(source, SOURCE_KEYS, "source")
            if review:
                reject_placeholders(source.get("label"), "source label")
                reject_placeholders(source.get("url"), "source URL")
            url = public_https_url(require_text(source.get("url"), "source URL"), "source URL")
            label = html.escape(require_text(source.get("label"), "source label"))
            body.append(f'<li><a href="{html.escape(url, quote=True)}" rel="noreferrer">{label}</a></li>')
        body.append("</ul></section>")
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    script_hash = base64.b64encode(hashlib.sha256(COPY_SCRIPT.encode("utf-8")).digest()).decode("ascii")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'sha256-{script_hash}'; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer"><title>{title}</title>
<style>
*{{box-sizing:border-box}}
:root{{color-scheme:light dark;--bg:#f8fafc;--fg:#172033;--muted:#475569;--border:#cbd5e1;--pre-bg:#e2e8f0;--accent:#2563eb;--link:#1d4ed8;--box-bg:#eff6ff;--box-border:#93c5fd;--btn-bg:#ffffff;--btn-border:#94a3b8;--btn-fg:#172033;--good:#166534;--good-bg:#f0fdf4;--bad:#991b1b;--bad-bg:#fef2f2;--diagram-bg:#fff}}
@media(prefers-color-scheme:dark){{:root{{--bg:#0f172a;--fg:#e2e8f0;--muted:#94a3b8;--border:#334155;--pre-bg:#1e293b;--accent:#38bdf8;--link:#7dd3fc;--box-bg:#1e293b;--box-border:#475569;--btn-bg:#1e293b;--btn-border:#64748b;--btn-fg:#e2e8f0;--good:#86efac;--good-bg:#142d22;--bad:#fca5a5;--bad-bg:#3b171b;--diagram-bg:#fff}}}}
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
figure.diagram{{margin:22px 0}} .diagram .mermaid-svg{{display:block;width:100%;height:auto;max-width:100%;margin:0 auto;padding:12px;border:1px solid var(--border);border-radius:9px;background:var(--diagram-bg)!important;color-scheme:light}}
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
@media(max-width:600px){{main{{padding:20px 16px}}h1{{font-size:1.6rem}}.comparison{{grid-template-columns:1fr}}}}
@media print{{:root{{color-scheme:light;--bg:#f8fafc;--fg:#172033;--muted:#475569;--border:#cbd5e1;--pre-bg:#e2e8f0;--accent:#2563eb;--link:#1d4ed8;--box-bg:#eff6ff;--box-border:#93c5fd;--btn-bg:#ffffff;--btn-border:#94a3b8;--btn-fg:#172033;--good:#166534;--good-bg:#f0fdf4;--bad:#991b1b;--bad-bg:#fef2f2;--diagram-bg:#fff}}.severity-blocker{{color:#b91c1c;border-color:#fca5a5;background:#fef2f2}}.severity-should-fix{{color:#b45309;border-color:#fcd34d;background:#fffbeb}}.severity-nit{{color:#475569;border-color:#cbd5e1;background:#f1f5f9}}.severity-question{{color:#6d28d9;border-color:#c4b5fd;background:#f5f3ff}}body{{background:white}}main{{padding:0}}pre{{white-space:pre-wrap}}.copy{{display:none}}details:not([open])>:not(summary){{display:block!important}}figure.diagram,.comparison,.callout{{break-inside:avoid}}}}
</style></head><body><main><h1>{title}</h1><p class="meta">{meta}</p>
<p class="meta generated">Generated {generated} by agent-explainer.py</p>
<p class="summary">{summary}</p>{index}{''.join(body)}
<script>{COPY_SCRIPT}</script></main></body></html>
"""


def save(repo, topic, data, home, mermaid_renderer=None):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}", topic):
        raise ValueError("topic must be a stable slug of letters, numbers, underscores or hyphens")
    content = render(data, mermaid_renderer)
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
    args = parser.parse_args()
    try:
        path = save(args.repo.resolve(), args.topic, json.loads(args.input.read_text()), Path.home())
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

#!/usr/bin/env python3
"""Save an offline HTML explanation outside Git and open it in the local browser.

Input JSON: {"kind": "review"?, "title": "...", "summary": "...", "sections": [
  {"heading": "...", "severity": "blocker|should-fix|nit|question"?,
   "location": "path:line" | {"text": "...", "url": "https://..."}?,
   "paragraphs": ["..."], "steps": ["..."],
   "flow": ["Input", "Validation", "Result"], "code": "...",
   "comments": ["pasteable suggested comment", ...]}],
  "metadata": {"Revision": "abc123" | {"text": "base abc123", "url": "https://..."}},
  "sources": [{"label": "...", "url": "https://..."}]}
All content is plain text, not HTML; optional fields may be omitted and unknown
keys are rejected before anything is written. Bare public https URLs in text
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
    parts = [f'<svg viewBox="0 0 520 {height}" role="img" aria-label="Flow diagram">'
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
SECTION_KEYS = {"heading", "severity", "location", "paragraphs", "steps", "flow", "code", "comments"}
SOURCE_KEYS = {"label", "url"}
SEVERITIES = ("blocker", "should-fix", "nit", "question")
PLACEHOLDERS = ("<sha>", "<number>", "<owner>", "<repo>")


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


def render(data):
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
        severity = section.get("severity")
        if severity is not None and severity not in SEVERITIES:
            raise ValueError(f'severity must be one of {", ".join(SEVERITIES)}')
        is_finding = heading_text.startswith("Finding")
        if review and is_finding:
            if severity is None:
                raise ValueError(f'Finding section "{heading_text}" must have a severity')
            if "location" not in section:
                raise ValueError(f'Finding section "{heading_text}" must have a location')
            if not text_list(section.get("comments", []), "comments"):
                raise ValueError(f'Finding section "{heading_text}" must have at least one comment')
            findings.append(heading_text)
        body.append(f'<section{id_anchor(review, is_finding, len(findings))}>'
                    f"<h2>{heading}{severity_badge(severity)}</h2>")
        if "location" in section:
            if review:
                reject_placeholders(section["location"], "section location")
            body.append(f'<p class="location">{location_value(section["location"], "section location")}</p>')
        for paragraph in text_list(section.get("paragraphs", []), "paragraphs"):
            body.append(f"<p>{rich(paragraph, 'paragraph')}</p>")
        steps = text_list(section.get("steps", []), "steps")
        if steps:
            body.append("<ol>" + "".join(f"<li>{rich(step, 'step')}</li>" for step in steps) + "</ol>")
        body.append(flow_svg(section.get("flow", []), f"arrow-{section_index}"))
        if "code" in section:
            body.append("<pre><code>" + html.escape(require_text(section["code"], "code")) + "</code></pre>")
        for comment in text_list(section.get("comments", []), "comments"):
            body.append(
                '<div class="comment"><div class="comment-head"><span>Suggested comment</span>'
                '<button type="button" class="copy">Copy</button></div>'
                f"<pre>{html.escape(comment)}</pre></div>"
            )
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
:root{{color-scheme:light dark;--bg:#f8fafc;--fg:#172033;--muted:#475569;--border:#cbd5e1;--pre-bg:#e2e8f0;--accent:#2563eb;--link:#1d4ed8;--box-bg:#eff6ff;--box-border:#93c5fd;--btn-bg:#ffffff;--btn-border:#94a3b8;--btn-fg:#172033}}
@media(prefers-color-scheme:dark){{:root{{--bg:#0f172a;--fg:#e2e8f0;--muted:#94a3b8;--border:#334155;--pre-bg:#1e293b;--accent:#38bdf8;--link:#7dd3fc;--box-bg:#1e293b;--box-border:#475569;--btn-bg:#1e293b;--btn-border:#64748b;--btn-fg:#e2e8f0}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:17px/1.65 system-ui,sans-serif}}
main{{max-width:900px;margin:auto;padding:36px 24px 72px}} h1{{font-size:2rem;line-height:1.2}}
h2{{font-size:1.3rem;line-height:1.3}} .summary{{font-size:1.15rem}} .meta{{color:var(--muted);font-size:.9rem}}
.location{{color:var(--muted);font-size:.85rem}}
section{{margin-top:30px;border-top:1px solid var(--border);padding-top:12px}} p,li{{overflow-wrap:anywhere}}
li{{margin:.4em 0}} pre{{overflow:auto;padding:18px;background:var(--pre-bg);border-radius:8px;font-size:.85rem}}
svg{{display:block;width:100%;max-width:520px;margin:24px auto}}
svg text{{font:16px system-ui,sans-serif;fill:var(--fg)}}
svg rect{{fill:var(--box-bg);stroke:var(--box-border)}} svg > path{{stroke:var(--accent)}} svg marker path{{fill:var(--accent)}}
a{{color:var(--link)}}
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
@media(max-width:600px){{main{{padding:20px 16px}}h1{{font-size:1.6rem}}}}
@media print{{:root{{color-scheme:light;--bg:#f8fafc;--fg:#172033;--muted:#475569;--border:#cbd5e1;--pre-bg:#e2e8f0;--accent:#2563eb;--link:#1d4ed8;--box-bg:#eff6ff;--box-border:#93c5fd;--btn-bg:#ffffff;--btn-border:#94a3b8;--btn-fg:#172033}}.severity-blocker{{color:#b91c1c;border-color:#fca5a5;background:#fef2f2}}.severity-should-fix{{color:#b45309;border-color:#fcd34d;background:#fffbeb}}.severity-nit{{color:#475569;border-color:#cbd5e1;background:#f1f5f9}}.severity-question{{color:#6d28d9;border-color:#c4b5fd;background:#f5f3ff}}body{{background:white}}main{{padding:0}}pre{{white-space:pre-wrap}}.copy{{display:none}}}}
</style></head><body><main><h1>{title}</h1><p class="meta">{meta}</p>
<p class="meta generated">Generated {generated} by agent-explainer.py</p>
<p class="summary">{summary}</p>{index}{''.join(body)}
<script>{COPY_SCRIPT}</script></main></body></html>
"""


def save(repo, topic, data, home):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}", topic):
        raise ValueError("topic must be a stable slug of letters, numbers, underscores or hyphens")
    content = render(data)
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

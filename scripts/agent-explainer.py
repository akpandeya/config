#!/usr/bin/env python3
"""Save an offline HTML explanation outside Git and open it in the local browser.

Input JSON: {"title": "...", "summary": "...", "sections": [
  {"heading": "...", "paragraphs": ["..."], "steps": ["..."],
   "flow": ["Input", "Validation", "Result"], "code": "..."}],
  "metadata": {"Revision": "abc123"}, "sources": [{"label": "...", "url": "https://..."}]}
All content is plain text, not HTML. Optional section fields may be omitted.
"""

import argparse
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


def render(data):
    if not isinstance(data, dict):
        raise ValueError("Input must be a JSON object")
    title = html.escape(require_text(data.get("title"), "title"))
    summary = html.escape(require_text(data.get("summary"), "summary"))
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object of text fields")
    meta = " · ".join(
        f"{html.escape(require_text(key, 'metadata key'))}: "
        f"{html.escape(require_text(value, 'metadata value'))}"
        for key, value in metadata.items()
    )
    sections = data.get("sections", [])
    if not isinstance(sections, list):
        raise ValueError("sections must be a list")
    body = []
    for section_index, section in enumerate(sections):
        if not isinstance(section, dict):
            raise ValueError("Each section must be an object")
        heading = html.escape(require_text(section.get("heading"), "section heading"))
        body.append(f"<section><h2>{heading}</h2>")
        for paragraph in text_list(section.get("paragraphs", []), "paragraphs"):
            body.append(f"<p>{html.escape(paragraph)}</p>")
        steps = text_list(section.get("steps", []), "steps")
        if steps:
            body.append("<ol>" + "".join(f"<li>{html.escape(step)}</li>" for step in steps) + "</ol>")
        body.append(flow_svg(section.get("flow", []), f"arrow-{section_index}"))
        if "code" in section:
            body.append("<pre><code>" + html.escape(require_text(section["code"], "code")) + "</code></pre>")
        body.append("</section>")
    sources = data.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("sources must be a list")
    if sources:
        body.append("<section><h2>Sources</h2><ul>")
        for source in sources:
            if not isinstance(source, dict):
                raise ValueError("Each source must be an object")
            url = require_text(source.get("url"), "source URL")
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                    or any(ord(char) < 32 for char in url)):
                raise ValueError("Source URLs must be HTTPS URLs without credentials")
            label = html.escape(require_text(source.get("label"), "source label"))
            body.append(f'<li><a href="{html.escape(url, quote=True)}" rel="noreferrer">{label}</a></li>')
        body.append("</ul></section>")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer"><title>{title}</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;background:#f8fafc;color:#172033;font:17px/1.65 system-ui,sans-serif}}
main{{max-width:900px;margin:auto;padding:36px 24px 72px}} h1{{font-size:2rem;line-height:1.2}}
h2{{font-size:1.3rem;line-height:1.3}} .summary{{font-size:1.15rem}} .meta{{color:#475569;font-size:.9rem}}
section{{margin-top:30px;border-top:1px solid #cbd5e1;padding-top:12px}} p,li{{overflow-wrap:anywhere}}
li{{margin:.4em 0}} pre{{overflow:auto;padding:18px;background:#e2e8f0;border-radius:8px;font-size:.85rem}}
svg{{display:block;width:100%;max-width:520px;margin:24px auto}} svg text{{font:16px system-ui,sans-serif;fill:#172033}}
a{{color:#1d4ed8}} @media(max-width:600px){{main{{padding:20px 16px}}h1{{font-size:1.6rem}}}}
@media print{{body{{background:white}}main{{padding:0}}pre{{white-space:pre-wrap}}}}
</style></head><body><main><h1>{title}</h1><p class="meta">{meta}</p>
<p class="summary">{summary}</p>{''.join(body)}</main></body></html>
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
        with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as stream:
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

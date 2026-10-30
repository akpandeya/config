#!/usr/bin/env python3
"""Serve artifact HTML with a comment overlay injected, and store feedback as JSON.

Serves an artifacts directory (default ~/.local/share/agent-explainers) on
127.0.0.1:8787:

- Any served ``.html`` gets the comment overlay (scripts/artifact-overlay.js)
  injected before ``</body>``; files already containing the ``agent-overlay:v1``
  marker are left untouched. A Content-Security-Policy meta tag, if present, is
  extended with the overlay script hash and a localhost-only ``connect-src``.
- ``POST /api/comments``     append comments to ``<artifact>.feedback.json``
- ``GET  /api/feedback?artifact=<path>``   comments for one artifact
- ``GET  /api/feedback/pending``          artifacts with open comments
- ``DELETE /api/comments?artifact=<path>&id=<id>``  remove one comment

The feedback JSON file next to each artifact is the source of truth: agents can
also just read it from disk without touching the server. Binds 127.0.0.1 only —
exposure to other devices goes through a tunnel (see issue #19), never the LAN.
"""

import argparse
import json
import os
import re
import sys
import tempfile
import threading
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

SCRIPT_DIR = Path(__file__).resolve().parent
OVERLAY_PATH = SCRIPT_DIR / "artifact-overlay.js"
MARKER = "agent-overlay:v1"
MAX_BODY = 256 * 1024
MAX_TEXT = 2000
MAX_SELECTOR = 500
MAX_QUOTE = 300
META_GENERATOR = re.compile(
    r'<meta\s+name=["\']agent-generator["\']\s+content=["\']([^"\']*)["\']\s*/?>',
    re.IGNORECASE,
)
CSP_META_TAG = re.compile(
    r'<meta\s[^>]*http-equiv=["\']Content-Security-Policy["\'][^>]*>',
    re.IGNORECASE,
)
CSP_META_CONTENT = re.compile(r'(?<![\w-])content=["\']([^"\']*)["\']', re.IGNORECASE)
WRITE_LOCK = threading.Lock()


def overlay_source():
    try:
        return OVERLAY_PATH.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"cannot read overlay script {OVERLAY_PATH}: {error}") from error


def script_hash(source):
    import base64
    import hashlib

    digest = hashlib.sha256(source.encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def extend_csp(policy, overlay_hash):
    """Add the overlay hash and localhost connect-src to a CSP header value."""
    extra_connect = "'self' http://127.0.0.1:8787 http://localhost:8787"
    parts = [part.strip() for part in policy.split(";") if part.strip()]
    out = []
    saw_connect = False
    saw_script = False
    for part in parts:
        name, *values = part.split()
        if name == "script-src":
            saw_script = True
            token = f"'sha256-{overlay_hash}'"
            if token not in values:
                values.append(token)
        elif name == "connect-src":
            saw_connect = True
            for token in extra_connect.split():
                if token not in values:
                    values.append(token)
        out.append(" ".join([name] + values))
    if not saw_script and any(part.startswith("default-src") for part in parts):
        out.append(f"script-src 'sha256-{overlay_hash}'")
    if not saw_connect:
        out.append(f"connect-src {extra_connect}")
    return "; ".join(out)


def rewrite_csp_meta(match, overlay_hash):
    """Extend the CSP inside one matched meta tag, regardless of attribute order."""
    tag = match.group(0)
    content = CSP_META_CONTENT.search(tag)
    if not content:
        return tag
    start, end = content.span(1)
    return tag[:start] + extend_csp(content.group(1), overlay_hash) + tag[end:]


def inject_overlay(html_text, overlay, overlay_hash):
    """Return html_text with the overlay script injected, or unchanged if marked."""
    if MARKER in html_text:
        return html_text, False
    tag = f"<script>{overlay}</script>"
    lower = html_text.lower()
    if "</body>" in lower:
        index = lower.rindex("</body>")
        text = html_text[:index] + tag + html_text[index:]
    elif "</html>" in lower:
        index = lower.rindex("</html>")
        text = html_text[:index] + tag + html_text[index:]
    else:
        text = html_text + tag
    text = CSP_META_TAG.sub(
        lambda match: rewrite_csp_meta(match, overlay_hash), text, count=1
    )
    return text, True


def safe_artifact_path(root, artifact):
    """Map a requested artifact identity to an existing .html inside root, or None.

    Accepts the served path ("/<repo-key>/<topic>.html"), a bare relative path, or
    (for file:// viewing) an absolute filesystem path matched by its suffix.
    """
    if not isinstance(artifact, str) or not artifact.strip():
        return None
    root = root.resolve()
    candidate = artifact
    if candidate.startswith("file://"):
        candidate = candidate[len("file://"):]
    candidate = candidate.split("?", 1)[0].split("#", 1)[0]
    relative = candidate.lstrip("/")
    if ".." in Path(relative).parts:
        return None
    resolved = (root / relative).resolve()
    if resolved != root and root not in resolved.parents:
        return None
    if resolved.is_file() and resolved.suffix == ".html":
        return resolved
    # file:// fallback: match a served artifact by directory name + file name.
    parts = Path(candidate).parts
    if len(parts) >= 2 and Path(parts[-1]).suffix == ".html":
        directory_name, file_name = parts[-2], parts[-1]
        matches = [
            p for p in root.glob("*/*.html")
            if p.name == file_name and p.parent.name == directory_name
        ]
        if len(matches) == 1:
            return matches[0]
    return None


def feedback_path(artifact_path):
    return artifact_path.with_name(artifact_path.stem + ".feedback.json")


def read_feedback(artifact_path):
    path = feedback_path(artifact_path)
    if not path.is_file():
        generator = None
        try:
            match = META_GENERATOR.search(artifact_path.read_text(encoding="utf-8", errors="replace")[:8192])
            generator = match.group(1) or None if match else None
        except OSError:
            pass
        return {"version": 1, "artifact": artifact_path.name, "generator": generator, "comments": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"feedback file is not valid JSON: {path}") from error
    if not isinstance(data, dict) or not isinstance(data.get("comments", []), list):
        raise ValueError(f"feedback file has an unexpected shape: {path}")
    return data


def write_feedback(artifact_path, data):
    path = feedback_path(artifact_path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
        ) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def clean_comment(raw):
    if not isinstance(raw, dict):
        raise ValueError("each comment must be an object")
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("comment text must be nonempty text")
    comment = {
        "id": str(raw.get("id") or ""),
        "text": text.strip()[:MAX_TEXT],
        "status": "open",
    }
    for field, limit in (("selector", MAX_SELECTOR), ("quote", MAX_QUOTE)):
        value = raw.get(field)
        if value is not None:
            if not isinstance(value, str):
                raise ValueError(f"comment {field} must be a string")
            comment[field] = value[:limit]
    created = raw.get("created_at")
    if created is not None:
        if not isinstance(created, str) or len(created) > 64:
            raise ValueError("comment created_at must be a short timestamp string")
        comment["created_at"] = created
    return comment


def append_comments(artifact_path, raw_comments):
    with WRITE_LOCK:
        data = read_feedback(artifact_path)
        existing = data.setdefault("comments", [])
        numeric = [
            int(c["id"]) for c in existing
            if isinstance(c, dict) and str(c.get("id", "")).isdigit()
        ]
        next_id = max(numeric, default=0) + 1
        stored = []
        for raw in raw_comments:
            comment = clean_comment(raw)
            comment["id"] = str(next_id)
            next_id += 1
            existing.append(comment)
            stored.append(comment)
        write_feedback(artifact_path, data)
    return stored


def delete_comment(artifact_path, comment_id):
    with WRITE_LOCK:
        data = read_feedback(artifact_path)
        comments = data.get("comments", [])
        kept = [c for c in comments if str(c.get("id")) != str(comment_id)]
        if len(kept) == len(comments):
            return False
        data["comments"] = kept
        write_feedback(artifact_path, data)
    return True


class FeedbackHandler(SimpleHTTPRequestHandler):
    root = None  # set via server config below

    # ---------- helpers ----------

    def api_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Cache-Control", "no-store")

    def json_response(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.api_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def query(self):
        return parse_qs(urlsplit(self.path).query)

    def trusted_host(self):
        """Reject DNS-rebinding requests whose Host header names a non-loopback host.

        Binding 127.0.0.1 stops the LAN but not a rebinding page in the user's
        browser, whose requests are same-origin to the attacker's domain and
        carry that domain in Host. Remote exposure (issue #19) must extend
        this allowlist when the server becomes reachable by name.
        """
        host = (self.headers.get("Host") or "").strip().lower()
        if not host:
            return True  # HTTP/1.0 clients may omit Host; the socket is already local
        if host.startswith("["):
            name = host[1:host.index("]")] if "]" in host else host
        elif host.count(":") <= 1:
            name = host.partition(":")[0]
        else:
            name = host  # bare IPv6 address such as ::1
        return name in {"127.0.0.1", "localhost", "::1"}

    # ---------- GET ----------

    def do_GET(self):
        if not self.trusted_host():
            self.json_response(403, {"error": "Host header is not a loopback name"})
            return
        path = urlsplit(self.path).path
        if path.startswith("/api/"):
            try:
                self.handle_api_get(path)
            except ValueError as error:
                self.json_response(400, {"error": str(error)})
            except OSError as error:
                self.json_response(500, {"error": str(error)})
            return
        if path.lower().endswith(".html"):
            try:
                self.serve_injected_html()
            except (OSError, ValueError) as error:
                self.json_response(500, {"error": str(error)})
            return
        super().do_GET()

    def serve_injected_html(self):
        local = Path(self.translate_path(urlsplit(self.path).path))
        resolved = local.resolve()
        root = self.root.resolve()
        if resolved != root and root not in resolved.parents:
            self.json_response(403, {"error": "path escapes the artifacts root"})
            return
        if not resolved.is_file():
            self.send_error(404)
            return
        overlay = self.overlay
        text, _ = inject_overlay(
            resolved.read_text(encoding="utf-8", errors="replace"), overlay, self.overlay_hash
        )
        body = text.encode("utf-8")
        self.send_response(200)
        self.api_headers()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_api_get(self, path):
        if path == "/api/feedback":
            artifact = (self.query().get("artifact") or [""])[0]
            resolved = safe_artifact_path(self.root, artifact)
            if resolved is None:
                self.json_response(404, {"error": f"no such artifact: {artifact}"})
                return
            self.json_response(200, read_feedback(resolved))
        elif path == "/api/feedback/pending":
            self.json_response(200, {"pending": pending_artifacts(self.root)})
        else:
            self.json_response(404, {"error": f"unknown API path: {path}"})

    # ---------- POST / DELETE / OPTIONS ----------

    def do_POST(self):
        if not self.trusted_host():
            self.json_response(403, {"error": "Host header is not a loopback name"})
            return
        if urlsplit(self.path).path != "/api/comments":
            self.json_response(404, {"error": "only /api/comments accepts POST"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.json_response(400, {"error": "invalid Content-Length header"})
            return
        if length <= 0 or length > MAX_BODY:
            self.json_response(413, {"error": f"body must be 1..{MAX_BODY} bytes"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            self.json_response(400, {"error": f"invalid JSON body: {error}"})
            return
        if not isinstance(payload, dict):
            self.json_response(400, {"error": "body must be a JSON object"})
            return
        resolved = safe_artifact_path(self.root, payload.get("artifact", ""))
        if resolved is None:
            self.json_response(404, {"error": f"no such artifact: {payload.get('artifact')}"})
            return
        raw_comments = payload.get("comments")
        if not isinstance(raw_comments, list) or not raw_comments:
            self.json_response(400, {"error": "comments must be a nonempty array"})
            return
        try:
            stored = append_comments(resolved, raw_comments)
        except ValueError as error:
            self.json_response(400, {"error": str(error)})
            return
        self.json_response(201, {"artifact": resolved.name, "comments": stored})

    def do_DELETE(self):
        if not self.trusted_host():
            self.json_response(403, {"error": "Host header is not a loopback name"})
            return
        if urlsplit(self.path).path != "/api/comments":
            self.json_response(404, {"error": "only /api/comments accepts DELETE"})
            return
        query = self.query()
        resolved = safe_artifact_path(self.root, (query.get("artifact") or [""])[0])
        if resolved is None:
            self.json_response(404, {"error": "no such artifact"})
            return
        comment_id = (query.get("id") or [""])[0]
        try:
            removed = delete_comment(resolved, comment_id)
        except ValueError as error:
            self.json_response(400, {"error": str(error)})
            return
        if not removed:
            self.json_response(404, {"error": f"no such comment: {comment_id}"})
            return
        self.json_response(200, read_feedback(resolved))

    def do_OPTIONS(self):
        if not self.trusted_host():
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        self.api_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        sys.stderr.write("[artifact-server] %s\n" % (format % args))


def pending_artifacts(root):
    """Artifacts with at least one open comment, newest update first."""
    entries = []
    for path in sorted(root.rglob("*.feedback.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        comments = data.get("comments") if isinstance(data, dict) else None
        if not isinstance(comments, list):
            continue
        open_count = sum(1 for c in comments if isinstance(c, dict) and c.get("status", "open") == "open")
        if not open_count:
            continue
        html_name = path.name.replace(".feedback.json", ".html")
        html_path = path.with_name(html_name)
        try:
            updated = datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
        except OSError:
            continue  # feedback file vanished while scanning
        entries.append({
            "artifact": str(html_path.relative_to(root)),
            "generator": data.get("generator"),
            "open": open_count,
            "total": len(comments),
            "updated": updated,
        })
    entries.sort(key=lambda entry: entry["updated"], reverse=True)
    return entries


def build_server(root, host, port):
    overlay = overlay_source()
    FeedbackHandler.root = root
    FeedbackHandler.overlay = overlay
    FeedbackHandler.overlay_hash = script_hash(overlay)
    handler = partial(FeedbackHandler, directory=str(root))
    return ThreadingHTTPServer((host, port), handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path.home() / ".local/share/agent-explainers",
        help="artifacts directory to serve (default: ~/.local/share/agent-explainers)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        print(f"Artifacts directory does not exist: {root}", file=sys.stderr)
        return 1
    try:
        httpd = build_server(root, args.host, args.port)
    except (OSError, ValueError) as error:
        print(f"Could not start artifact server: {error}", file=sys.stderr)
        return 1
    print(f"Serving {root} at http://{args.host}:{args.port} (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

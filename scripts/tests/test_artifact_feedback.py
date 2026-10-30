"""Tests for the artifact feedback loop: overlay, feedback server, explainer embed."""

import base64
import json
import re
import sys
import tempfile
import threading
import unittest
import importlib.util
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent_explainer = load("explainer", ROOT / "scripts/agent-explainer.py")
artifact_server = load("artifact_server", ROOT / "scripts/artifact-server.py")

OVERLAY = (ROOT / "scripts/artifact-overlay.js").read_text(encoding="utf-8")
SAMPLE_INPUT = {
    "title": "Demo artifact",
    "summary": "A small design artifact for feedback tests.",
    "sections": [{"heading": "How it works", "paragraphs": ["First step.", "Second step."]}],
}


def get_json(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def request_json(url, method="GET", payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8") or "{}")


class OverlayInjectionTest(unittest.TestCase):
    def test_injects_before_body_and_extends_csp(self):
        page = (
            '<!doctype html><html><head><meta http-equiv="Content-Security-Policy" '
            "content=\"default-src 'none'; style-src 'unsafe-inline'; script-src 'sha256-AAA='; "
            "base-uri 'none'\"></head><body><p>hi</p></body></html>"
        )
        result, changed = artifact_server.inject_overlay(page, OVERLAY, "BBBB=")
        self.assertTrue(changed)
        self.assertIn("agent-overlay:v1", result)
        self.assertIn("<script>" + OVERLAY + "</script></body>", result)
        self.assertIn("'sha256-BBBB='", result)
        self.assertIn("connect-src 'self' http://127.0.0.1:8787", result)
        self.assertIn("sha256-AAA=", result)  # original hash preserved

    def test_marker_prevents_double_injection(self):
        page = f"<html><body><script>{OVERLAY}</script><!-- agent-overlay:v1 --></body></html>"
        result, changed = artifact_server.inject_overlay(page, OVERLAY, "BBBB=")
        self.assertFalse(changed)
        self.assertEqual(result, page)

    def test_page_without_body_still_gets_overlay(self):
        page = "<html><p>loose page</p></html>"
        result, changed = artifact_server.inject_overlay(page, OVERLAY, "BBBB=")
        self.assertTrue(changed)
        self.assertIn("</script></html>", result)

    def test_csp_without_script_src_gains_one_when_default_src_present(self):
        result, _ = artifact_server.inject_overlay(
            '<html><head><meta http-equiv="Content-Security-Policy" '
            "content=\"default-src 'none'\"></head><body></body></html>",
            OVERLAY, "BBBB=")
        self.assertIn("script-src 'sha256-BBBB='", result)

    def test_csp_meta_with_content_before_http_equiv_is_extended(self):
        result, changed = artifact_server.inject_overlay(
            '<html><head><meta content="default-src \'none\'" '
            'http-equiv="Content-Security-Policy"></head><body></body></html>',
            OVERLAY, "BBBB=")
        self.assertTrue(changed)
        self.assertIn("script-src 'sha256-BBBB='", result)


class SafeArtifactPathTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.dir = self.root / "some-repo-abc123"
        self.dir.mkdir()
        self.page = self.dir / "topic.html"
        self.page.write_text("<html><body></body></html>", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_relative_path_resolves(self):
        self.assertEqual(artifact_server.safe_artifact_path(self.root, "/some-repo-abc123/topic.html"),
                         self.page.resolve())

    def test_traversal_rejected(self):
        self.assertIsNone(artifact_server.safe_artifact_path(self.root, "../outside.html"))
        self.assertIsNone(artifact_server.safe_artifact_path(self.root, "a/../../etc/passwd.html"))

    def test_missing_or_non_html_rejected(self):
        self.assertIsNone(artifact_server.safe_artifact_path(self.root, "some-repo-abc123/nope.html"))
        (self.dir / "notes.txt").write_text("x", encoding="utf-8")
        self.assertIsNone(artifact_server.safe_artifact_path(self.root, "some-repo-abc123/notes.txt"))

    def test_absolute_filesystem_path_matched_by_suffix(self):
        self.assertEqual(artifact_server.safe_artifact_path(self.root, str(self.page)), self.page.resolve())

    def test_file_url_matches_own_directory(self):
        self.assertEqual(
            artifact_server.safe_artifact_path(self.root, f"file://{self.page.resolve()}"),
            self.page.resolve())

    def test_suffix_fallback_requires_matching_directory(self):
        # A file:// path naming a directory that does not exist under root must
        # not silently attach to a same-named file in a different directory.
        self.assertIsNone(
            artifact_server.safe_artifact_path(self.root, "/totally-different/topic.html"))


class FeedbackStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.page = self.root / "repo/topic.html"
        self.page.parent.mkdir(parents=True)
        self.page.write_text('<meta name="agent-generator" content="agent-explainer">', encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_append_assigns_ids_and_reads_back(self):
        stored = artifact_server.append_comments(self.page, [{"text": "Fix wording"}])
        self.assertEqual(stored[0]["id"], "1")
        self.assertEqual(stored[0]["status"], "open")
        second = artifact_server.append_comments(self.page, [{"text": "Another"}])
        self.assertEqual(second[0]["id"], "2")
        data = artifact_server.read_feedback(self.page)
        self.assertEqual(data["generator"], "agent-explainer")
        self.assertEqual([c["id"] for c in data["comments"]], ["1", "2"])
        self.assertEqual(self.page.with_name("topic.feedback.json").stat().st_mode & 0o777, 0o600)

    def test_rejects_empty_text(self):
        with self.assertRaises(ValueError):
            artifact_server.append_comments(self.page, [{"text": "   "}])

    def test_delete_removes_only_matching_id(self):
        artifact_server.append_comments(self.page, [{"text": "one"}, {"text": "two"}])
        self.assertTrue(artifact_server.delete_comment(self.page, "1"))
        self.assertFalse(artifact_server.delete_comment(self.page, "1"))
        self.assertEqual([c["id"] for c in artifact_server.read_feedback(self.page)["comments"]], ["2"])

    def test_append_tolerates_malformed_existing_entries(self):
        artifact_server.append_comments(self.page, [{"text": "one"}])
        path = self.page.with_name("topic.feedback.json")
        data = json.loads(path.read_text())
        data["comments"].insert(0, "garbage")
        path.write_text(json.dumps(data), encoding="utf-8")
        stored = artifact_server.append_comments(self.page, [{"text": "two"}])
        self.assertEqual(stored[0]["id"], "2")


class ServerHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.page = cls.root / "repo/demo.html"
        cls.page.parent.mkdir(parents=True)
        cls.page.write_text(
            '<html><head><meta http-equiv="Content-Security-Policy" '
            "content=\"default-src 'none'; script-src 'sha256-AAA='\"></head>"
            "<body><p>body text</p></body></html>", encoding="utf-8")
        cls.httpd = artifact_server.build_server(cls.root, "127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls._tmp.cleanup()

    def fetch_html(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as response:
            return response.read().decode("utf-8")

    def _reset_feedback(self):
        feedback = self.page.parent / "demo.feedback.json"
        if feedback.exists():
            feedback.unlink()

    def test_html_gets_overlay_and_csp_once(self):
        first = self.fetch_html("/repo/demo.html")
        self.assertIn("agent-overlay:v1", first)
        csp = re.search(r'Content-Security-Policy" content="([^"]*)"', first).group(1)
        self.assertIn("sha256-", csp)
        self.assertIn("connect-src 'self'", csp)
        self.assertEqual(first.count("<script>"), 1)  # only the injected overlay
        self.assertIn("</script></body>", first)
        second = self.fetch_html("/repo/demo.html")
        self.assertEqual(first, second)  # no double injection

    def test_post_then_get_roundtrip(self):
        self._reset_feedback()
        status, body = request_json(
            f"{self.base}/api/comments", method="POST",
            payload={"artifact": "repo/demo.html", "comments": [
                {"text": "Reword this", "selector": "main > p", "quote": "body text"}]})
        self.assertEqual(status, 201)
        self.assertEqual(body["comments"][0]["status"], "open")
        status, data = get_json(f"{self.base}/api/feedback?artifact=repo/demo.html")
        self.assertEqual(status, 200)
        self.assertIn("Reword this", [c["text"] for c in data["comments"]])
        stored = json.loads((self.page.parent / "demo.feedback.json").read_text())
        self.assertEqual(stored["version"], 1)

    def test_post_rejects_bad_input(self):
        self._reset_feedback()
        status, _ = request_json(f"{self.base}/api/comments", method="POST",
                                 payload={"artifact": "repo/demo.html", "comments": [{"text": "  "}]})
        self.assertEqual(status, 400)
        status, _ = request_json(f"{self.base}/api/comments", method="POST",
                                 payload={"artifact": "repo/missing.html", "comments": [{"text": "x"}]})
        self.assertEqual(status, 404)
        status, _ = request_json(f"{self.base}/api/comments", method="POST",
                                 payload={"artifact": "../escape.html", "comments": [{"text": "x"}]})
        self.assertEqual(status, 404)

    def test_delete_removes_comment(self):
        self._reset_feedback()
        request_json(f"{self.base}/api/comments", method="POST",
                     payload={"artifact": "repo/demo.html", "comments": [{"text": "temp"}]})
        status, data = get_json(f"{self.base}/api/feedback?artifact=repo/demo.html")
        comment_id = data["comments"][0]["id"]
        status, _ = request_json(
            f"{self.base}/api/comments?artifact=repo/demo.html&id={comment_id}", method="DELETE")
        self.assertEqual(status, 200)
        status, _ = request_json(
            f"{self.base}/api/comments?artifact=repo/demo.html&id={comment_id}", method="DELETE")
        self.assertEqual(status, 404)

    def test_corrupt_feedback_file_fails_closed(self):
        self._reset_feedback()
        (self.page.parent / "demo.feedback.json").write_text("{not json", encoding="utf-8")
        status, _ = request_json(f"{self.base}/api/feedback?artifact=repo/demo.html")
        self.assertEqual(status, 400)
        status, _ = request_json(f"{self.base}/api/comments", method="POST",
                                 payload={"artifact": "repo/demo.html", "comments": [{"text": "x"}]})
        self.assertEqual(status, 400)

    def test_foreign_host_header_rejected(self):
        request = urllib.request.Request(
            f"{self.base}/api/feedback/pending",
            headers={"Host": "rebound.example:8787"})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
        self.assertEqual(status, 403)

    def test_pending_lists_and_clears(self):
        self._reset_feedback()
        request_json(f"{self.base}/api/comments", method="POST",
                     payload={"artifact": "repo/demo.html", "comments": [{"text": "pending check"}]})
        status, data = get_json(f"{self.base}/api/feedback/pending")
        self.assertEqual(status, 200)
        entry = next(e for e in data["pending"] if e["artifact"] == "repo/demo.html")
        self.assertGreaterEqual(entry["open"], 1)
        feedback = json.loads((self.page.parent / "demo.feedback.json").read_text())
        for comment in feedback["comments"]:
            comment["status"] = "resolved"
        (self.page.parent / "demo.feedback.json").write_text(json.dumps(feedback))
        status, data = get_json(f"{self.base}/api/feedback/pending")
        self.assertFalse([e for e in data["pending"] if e["artifact"] == "repo/demo.html"])


class ExplainerEmbedTest(unittest.TestCase):
    def render(self, **kwargs):
        return agent_explainer.render(dict(SAMPLE_INPUT), **kwargs)

    def test_overlay_embedded_by_default_with_csp(self):
        page = self.render()
        self.assertIn(OVERLAY, page)
        self.assertIn('<meta name="agent-generator" content="agent-explainer">', page)
        csp = re.search(r'Content-Security-Policy" content="([^"]*)"', page).group(1)
        self.assertEqual(csp.count("sha256-"), 2)
        self.assertIn("connect-src http://127.0.0.1:8787", csp)

    def test_no_overlay_flag_omits_it(self):
        page = self.render(overlay=False)
        self.assertNotIn(OVERLAY, page)
        self.assertNotIn("connect-src", page)
        self.assertIn('<meta name="agent-generator" content="agent-explainer">', page)

    def test_generator_is_escaped(self):
        page = self.render(generator='evil"><script>')
        self.assertIn('<meta name="agent-generator" content="evil&quot;&gt;&lt;script&gt;">', page)
        self.assertNotIn('evil"><script>', page)

    def test_save_keeps_overlay_and_feedback_file_separate(self):
        with tempfile.TemporaryDirectory() as home:
            destination = agent_explainer.save(
                ROOT, "overlaydemo", dict(SAMPLE_INPUT), Path(home))
            self.assertEqual(destination.name, "overlaydemo.html")
            self.assertIn(OVERLAY, destination.read_text(encoding="utf-8"))
            self.assertFalse(list(destination.parent.glob("*.feedback.json")))


if __name__ == "__main__":
    unittest.main()
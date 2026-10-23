import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


instructions = load("instructions", ROOT / "scripts/install-agent-instructions.py")
explainer = load("explainer", ROOT / "scripts/agent-explainer.py")


class InstructionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / "home"
        self.root = self.base / "source"
        for name, text in {
            "opencode/AGENTS.md": "Personal rules",
            "agents/communication.md": "Plain language",
            "claude/RTK.md": "RTK rules",
        }.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def install(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            instructions.install(self.home, self.root, **kwargs)

    def test_composition_backup_and_idempotence(self):
        target = self.home / ".claude/CLAUDE.md"
        target.parent.mkdir(parents=True)
        target.write_text("Custom original")
        self.install()
        self.install()
        self.assertEqual(target.with_name("CLAUDE.md.before-agent-context").read_text(), "Custom original")
        self.assertFalse(target.with_name("CLAUDE.md.before-agent-context.1").exists())
        for harness, destination in instructions.TARGETS.items():
            path = self.home / destination
            self.assertTrue(path.is_symlink())
            self.assertIn("Plain language", path.read_text())
            self.assertEqual("RTK rules" in path.read_text(), harness in ("claude", "opencode"))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_private_context_before_or_after_personal_install(self):
        self.install()
        context = self.base / "private/AGENTS.md"
        context.parent.mkdir()
        context.write_text("PRIVATE_CONTEXT_SENTINEL")
        link = self.home / ".hf-context/AGENTS.md"
        link.parent.mkdir()
        link.symlink_to(context)
        self.install()
        self.install(work_context=context)
        for destination in instructions.TARGETS.values():
            self.assertIn("PRIVATE_CONTEXT_SENTINEL", (self.home / destination).read_text())
        for path in self.root.rglob("*.md"):
            self.assertNotIn("PRIVATE_CONTEXT_SENTINEL", path.read_text())

    def test_fail_closed_before_any_write(self):
        generated = self.home / ".config/agent-context/copilot.md"
        generated.parent.mkdir(parents=True)
        generated.symlink_to(self.base / "missing")
        with self.assertRaises(ValueError):
            self.install()
        self.assertFalse((self.home / ".claude").exists())

    def test_missing_and_broken_private_context(self):
        with self.assertRaises(ValueError):
            self.install(work_context=self.base / "missing")
        link = self.home / ".hf-context/AGENTS.md"
        link.parent.mkdir(parents=True)
        link.symlink_to(self.base / "missing")
        with self.assertRaises(ValueError):
            self.install()

    def test_imports_and_repo_destination_rejected(self):
        (self.root / "opencode/AGENTS.md").write_text("@unresolved.md")
        with self.assertRaises(ValueError):
            self.install()
        (self.root / "opencode/AGENTS.md").write_text("Rules")
        with self.assertRaises(ValueError):
            instructions.install(self.root, self.root)
        self.assertFalse((self.root / ".config").exists())

    def test_missing_rtk_and_dry_run_do_not_partially_install(self):
        self.install(dry_run=True)
        self.assertFalse(self.home.exists())
        (self.root / "claude/RTK.md").unlink()
        with self.assertRaises(OSError):
            self.install()
        self.assertFalse(self.home.exists())


class ExplainerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo with spaces"
        self.git("init", "-q", str(self.repo))
        self.home = self.base / "home"
        self.data = {"title": "How this works", "summary": "<script>unsafe</script>",
                     "sections": [{"heading": "Flow", "flow": ["Input", "Output"]},
                                  {"heading": "Example", "flow": ["A", "B"],
                                   "code": "<p>not markup</p>"}]}

    def git(self, *args):
        return subprocess.run(["git", *args], check=True, capture_output=True, text=True)

    def test_safe_offline_html_and_unique_diagrams(self):
        output = explainer.render(self.data)
        self.assertIn("&lt;script&gt;", output)
        self.assertNotIn("<script>", output)
        self.assertIn("default-src 'none'", output)
        self.assertIn('id="arrow-0"', output)
        self.assertIn('id="arrow-1"', output)
        self.assertIn("&lt;p&gt;not markup&lt;/p&gt;", output)

    def test_source_urls(self):
        for url in ["javascript:alert(1)", "http://example.org", "https://u:p@example.org",
                    "https://example.org/\npath"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                explainer.render({**self.data, "sources": [{"label": "Source", "url": url}]})
        self.assertIn('rel="noreferrer"', explainer.render({
            **self.data, "sources": [{"label": "Source", "url": "https://example.org/code"}],
        }))

    def test_atomic_persistence_and_path_guards(self):
        path = explainer.save(self.repo, "review-1", self.data, self.home)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path, explainer.save(self.repo, "review-1", self.data, self.home))
        self.assertEqual(list(path.parent.iterdir()), [path])
        with self.assertRaises(ValueError):
            explainer.save(self.repo, "../escape", self.data, self.home)
        with self.assertRaises(ValueError):
            explainer.save(self.repo, "review", self.data, self.repo)
        self.assertFalse((self.repo / ".local").exists())
        path.unlink()
        path.symlink_to(self.repo / "must-not-write")
        with self.assertRaises(ValueError):
            explainer.save(self.repo, "review-1", self.data, self.home)
        self.assertFalse((self.repo / "must-not-write").exists())

    def test_symlinked_artifact_root_inside_repo_is_rejected(self):
        root = self.home / ".local/share/agent-explainers"
        root.parent.mkdir(parents=True)
        root.symlink_to(self.repo)
        with self.assertRaises(ValueError):
            explainer.save(self.repo, "review", self.data, self.home)
        self.assertEqual([p.name for p in self.repo.iterdir()], [".git"])

    def test_repo_keys_and_worktree_stability(self):
        other = self.base / "another/repo with spaces"
        self.git("init", "-q", str(other))
        self.assertNotEqual(explainer.repository_key(self.repo), explainer.repository_key(other))
        self.git("-C", str(self.repo), "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                 "-c", "user.name=Test", "-c", "user.email=test@example.org",
                 "commit", "--allow-empty", "-qm", "fixture")
        worktree = self.base / "different worktree name"
        self.git("-C", str(self.repo), "worktree", "add", "-q", "--detach", str(worktree))
        self.assertEqual(explainer.repository_key(self.repo), explainer.repository_key(worktree))
        self.git("-C", str(self.repo), "remote", "add", "origin", "https://user:password@example.org/org/repo.git")
        key = explainer.repository_key(self.repo)
        self.assertNotIn("password", key)
        self.assertNotIn("user", key)
        self.assertEqual(key, explainer.repository_key(worktree))

    def test_bad_input_and_open_failure(self):
        for data in [None, {}, {**self.data, "sections": "not-list"}]:
            with self.assertRaises(ValueError):
                explainer.render(data)
        source = self.base / "input.json"
        source.write_text(json.dumps(self.data))
        error = io.StringIO()
        args = ["agent-explainer", "--repo", str(self.repo), "--topic", "review", "--input", str(source)]
        with patch.object(sys, "argv", args), patch.object(Path, "home", return_value=self.home), \
                patch.object(explainer, "open_page", side_effect=OSError("unavailable")), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(error):
            self.assertEqual(explainer.main(), 1)
        self.assertIn("saved file manually", error.getvalue())
        self.assertEqual(len(list(self.home.rglob("review.html"))), 1)


FAKE_GH = """#!/usr/bin/env python3
import json, os, pathlib, sys
state = pathlib.Path(os.environ["FAKE_STATE"])
with (state / "calls").open("a") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")
if sys.argv[1:3] == ["pr", "checks"]:
    counter = state / "counter"
    index = int(counter.read_text()) if counter.exists() else 0
    responses = json.loads(os.environ["FAKE_RESPONSES"])
    response = responses[min(index, len(responses)-1)]
    counter.write_text(str(index+1))
    print(response["raw"] if "raw" in response else json.dumps(response["checks"]))
    sys.exit(response["exit"])
elif sys.argv[1] == "api":
    index = int((state / "counter").read_text())
    print(json.dumps([] if index == 1 else [{"id": 12, "user": {"login": "reviewer"}, "state": "COMMENTED"}]))
else:
    sys.exit(99)
"""


class WatcherTest(unittest.TestCase):
    def run_watcher(self, responses):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            executable = root / "gh"
            executable.write_text(FAKE_GH)
            executable.chmod(0o755)
            env = {**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"],
                   "HOME": str(root), "FAKE_STATE": str(root), "FAKE_RESPONSES": json.dumps(responses)}
            result = subprocess.run(
                ["bash", str(ROOT / "claude/scripts/pr-wait-green.sh"), "23", "--repo", "org/repo",
                 "--interval", "0", "--max-ticks", "2"],
                env=env, capture_output=True, text=True, timeout=20,
            )
            calls = (root / "calls").read_text()
            self.assertNotIn(" merge ", calls)
            self.assertNotIn(" comment ", calls)
            self.assertNotIn("POST", calls)
            self.assertIn("LOG_PATH=", result.stdout)
            self.assertIn("pr-wait-org-repo-23.", result.stdout)
            self.assertLessEqual(int((root / "counter").read_text()), 2)
            return result

    def response(self, buckets, exit_code=0):
        return {"exit": exit_code, "checks": [{"name": f"check-{i}", "bucket": b}
                                             for i, b in enumerate(buckets)]}

    def test_pending_exit_eight_and_new_discussion(self):
        result = self.run_watcher([self.response(["pending"], 8), self.response(["pass", "skipping"])])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("state=PENDING", result.stderr)
        self.assertIn("EVENT review_comment", result.stderr)
        self.assertIn("EVENT review ", result.stderr)
        self.assertIn("EVENT comment ", result.stderr)

    def test_settled_failures_and_cancellations(self):
        for bucket in ("fail", "cancel"):
            with self.subTest(bucket=bucket):
                result = self.run_watcher([self.response([bucket], 1)])
                self.assertEqual(result.returncode, 2, result.stderr)

    def test_pending_failure_waits_until_settled(self):
        result = self.run_watcher([self.response(["fail", "pending"], 8),
                                   self.response(["fail", "pass"], 1)])
        self.assertEqual(result.returncode, 2)
        self.assertIn("tick=2", result.stderr)

    def test_unknown_empty_api_errors_and_pending_are_bounded(self):
        for response in [self.response([]), self.response(["unknown"]),
                         {"exit": 1, "raw": "API unavailable"}, self.response(["pending"], 8)]:
            with self.subTest(response=response):
                result = self.run_watcher([response])
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("EVENT timeout ticks=2", result.stderr)


if __name__ == "__main__":
    unittest.main()

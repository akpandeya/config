import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
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
                [str(ROOT / "claude/scripts/pr-wait-green.sh"), "23", "--repo", "org/repo",
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


ATELIER = Path(__file__).resolve().parents[3] / "atelier"


@unittest.skipUnless(
    (ATELIER / "scripts/agent-explainer.py").is_file(),
    "atelier repo not checked out next to config",
)
class AtelierIntegrationTest(unittest.TestCase):
    """The artifact toolchain moved to the atelier repo; these checks keep the
    two repos consistent (config references atelier, never forks it)."""

    def setUp(self):
        self.explainer = load("explainer", ATELIER / "scripts/agent-explainer.py")

    def test_skill_review_template_renders(self):
        skill = (ROOT / "claude/skills/deep-review/SKILL.md").read_text()
        explainer = self.explainer
        marker = skill.index("Review template")
        template = re.search(r"```json\n(.*?)```", skill[marker:], re.DOTALL).group(1)
        values = {
            "PR title or stack subject": "WeekCalibrator stack (#5065 ADR, #5069 spec, #5072 skeleton)",
            "number": "5065",
            "owner": "hellofresh",
            "repo": "production-planning",
            "sha": "ab33640fdb64f21d3e85dcc66474b4f006525ae4",
            "base": "ab33640fdb64f21d3e85dcc66474b4f006525ae4",
            "head": "4abcfb0499999999999999999999999999999999",
            "line": "42",
            "what": "ADR",
        }

        def fill(value):
            if isinstance(value, str):
                if value == "blocker | should-fix | nit | question":
                    return "should-fix"
                def substitute(match):
                    name = match.group(1)
                    if name not in values:
                        raise AssertionError(f"template placeholder <{name}> has no fill value in the test")
                    return values[name]
                return re.sub(r"<([^>]+)>", substitute, value)
            if isinstance(value, list):
                return [fill(item) for item in value]
            if isinstance(value, dict):
                return {key: fill(item) for key, item in value.items()}
            return value

        data = fill(json.loads(template))
        leftover = re.search(r"<[^>]+>", json.dumps(data))
        self.assertIsNone(leftover, f"unfilled placeholder in template: {leftover and leftover.group(0)}")
        output = explainer.render(data)
        self.assertIn('id="finding-1"', output)
        self.assertIn('href="#finding-1"', output)
        self.assertIn("severity-should-fix", output)
        self.assertIn('class="location"', output)
        self.assertEqual(output.count('class="copy"'), 1)
        self.assertIn('class="comparison"', output)
        self.assertIn('class="callout"', output)
        self.assertIn('class="supporting"', output)
        self.assertIn("mermaid-svg", output)
        self.assertIn("Generated ", output)
        self.assertIn("https://github.com/hellofresh/production-planning/pull/5065", output)
        self.assertIn("/changes#diff-", output)
        self.assertIn("Diff-validated, UI-unverified", output)
        self.assertIn("https://github.com/hellofresh/production-planning/compare/ab33640f", output)

    def test_mermaid_setup_points_at_atelier(self):
        package = json.loads((ATELIER / "scripts/mermaid/package.json").read_text())
        self.assertEqual(package["dependencies"]["@mermaid-js/mermaid-cli"], "12.0.0")
        self.assertEqual(package["dependencies"]["puppeteer"], "25.16.0")
        self.assertTrue(package["allowScripts"]["puppeteer@25.16.0"])
        lock = json.loads((ATELIER / "scripts/mermaid/package-lock.json").read_text())
        self.assertEqual(lock["packages"][""]["dependencies"], package["dependencies"])
        setup = (ROOT / "setup-dev-env.sh").read_text()
        self.assertIn('npm ci --prefix "$ATELIER_DIR/scripts/mermaid"', setup)
        self.assertNotIn('npm ci --prefix "$REPO_DIR/scripts/mermaid"', setup)
        self.assertNotIn("npx mmdc", setup)


if __name__ == "__main__":
    unittest.main()

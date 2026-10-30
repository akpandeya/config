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
        self.assertNotIn("<script>unsafe", output)
        self.assertEqual(output.count("<script>"), 1)  # the static copy helper only
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

    def test_unknown_keys_are_rejected_and_write_nothing(self):
        cases = [
            ({**self.data, "titel": "x"}, "titel"),
            ({**self.data, "kind": "audit"}, "kind"),
            ({**self.data, "sections": [{"heading": "H", "comment": ["c"]}]}, "comment"),
            ({**self.data, "sources": [{"label": "L", "url": "https://example.org", "href": "x"}]}, "href"),
            ({**self.data, "metadata": {"Rev": {"text": "t", "url": "https://example.org", "v": 1}}}, "v"),
        ]
        for data, fragment in cases:
            with self.subTest(fragment=fragment), self.assertRaises(ValueError) as ctx:
                explainer.render(data)
            self.assertIn(fragment, str(ctx.exception))
        with self.assertRaises(ValueError):
            explainer.save(self.repo, "review-2", cases[2][0], self.home)
        self.assertFalse((self.home / ".local").exists())

    def test_autolinker_validates_urls_and_preserves_quoting(self):
        data = {**self.data, "sections": [{"heading": "H", "paragraphs": [
            "plain http://example.org/http and https://user:pass@example.org/x stay text",
            'quoted "https://example.org/x?a=1&b=2" and trailing https://example.org/ok.',
        ]}]}
        output = explainer.render(data)
        self.assertNotIn('href="http://', output)
        self.assertNotIn("user:pass@example.org/x</a>", output)
        self.assertIn("http://example.org/http", output)
        self.assertIn("https://user:pass@example.org/x", output)
        self.assertIn('href="https://example.org/x?a=1&amp;b=2"', output)
        self.assertNotIn("&quot\"", output)
        self.assertIn('href="https://example.org/ok"', output)

    def review_data(self):
        return {
            "kind": "review",
            "title": "Deep review: something",
            "summary": "overview",
            "sections": [
                {"heading": "How this works", "paragraphs": ["the flow"]},
                {"heading": "Finding 1 (should-fix): misleading name", "severity": "should-fix",
                 "location": "src/main.kt:10", "paragraphs": ["why it matters"],
                 "comments": ["rename this?"]},
                {"heading": "Verdict and coverage", "paragraphs": ["Comment only"]},
            ],
        }

    def test_review_mode_renders_index_badges_location_and_stamp(self):
        output = explainer.render(self.review_data())
        self.assertIn('id="finding-1"', output)
        self.assertIn('href="#finding-1"', output)
        self.assertIn("severity-should-fix", output)
        self.assertIn('class="location"', output)
        self.assertIn("src/main.kt:10", output)
        self.assertRegex(output, r"Generated \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00 by agent-explainer\.py")
        self.assertIn("color-scheme:light dark", output)
        self.assertIn("@media print{:root{color-scheme:light", output)

    def test_review_mode_validation(self):
        for key in ("severity", "location", "comments"):
            broken = json.loads(json.dumps(self.review_data()))
            del broken["sections"][1][key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                explainer.render(broken)
        broken = json.loads(json.dumps(self.review_data()))
        broken["sections"][1]["comments"] = []
        with self.assertRaises(ValueError):
            explainer.render(broken)
        broken = json.loads(json.dumps(self.review_data()))
        broken["sections"][1]["severity"] = "critical"
        with self.assertRaises(ValueError):
            explainer.render(broken)
        broken = json.loads(json.dumps(self.review_data()))
        broken["sections"][-1]["heading"] = "Decision and coverage"
        with self.assertRaises(ValueError):
            explainer.render(broken)
        for placeholder in ("<sha>", "<number>", "<owner>", "<repo>"):
            broken = json.loads(json.dumps(self.review_data()))
            broken["summary"] = f"base {placeholder} compared"
            with self.subTest(placeholder=placeholder), self.assertRaises(ValueError) as ctx:
                explainer.render(broken)
            self.assertIn(placeholder, str(ctx.exception))

    def test_placeholder_scan_ignores_content_fields(self):
        data = self.review_data()
        data["sections"][0]["paragraphs"] = [
            "the template says https://github.com/<owner>/<repo>/pull/<number> literally"
        ]
        data["sections"][0]["steps"] = ["replace <owner> first"]
        data["sections"][0]["code"] = "url = 'https://github.com/<owner>/<repo>'"
        data["sections"][1]["comments"] = ["base <sha>...head <sha>, fill this in"]
        output = explainer.render(data)
        self.assertIn("&lt;owner&gt;", output)
        self.assertIn("&lt;sha&gt;", output)

    def test_placeholder_scan_still_covers_fill_in_slots(self):
        mutations = [
            ("heading", lambda d: d["sections"][1].update(heading="Finding 1 (<sha>): bad name")),
            ("summary", lambda d: d.update(summary="base <sha> compared")),
            ("metadata text", lambda d: d.update(
                metadata={"PR": {"text": "#<number>", "url": "https://github.com/o/r/pull/1"}})),
            ("metadata url", lambda d: d.update(
                metadata={"PR": {"text": "#1", "url": "https://github.com/<owner>/<repo>/pull/1"}})),
            ("location string", lambda d: d["sections"][1].update(location="see <sha>")),
            ("location url", lambda d: d["sections"][1].update(
                location={"text": "file:1", "url": "https://github.com/<owner>/<repo}/blob/x"})),
            ("source label", lambda d: d.update(
                sources=[{"label": "PR #<number>", "url": "https://github.com/o/r/pull/1"}])),
            ("source url", lambda d: d.update(
                sources=[{"label": "PR", "url": "https://github.com/<owner>/<repo>/pull/1"}])),
        ]
        for slot, mutate in mutations:
            broken = json.loads(json.dumps(self.review_data()))
            mutate(broken)
            with self.subTest(slot=slot), self.assertRaises(ValueError) as ctx:
                explainer.render(broken)
            self.assertIn("placeholder", str(ctx.exception))

    def test_skill_review_template_renders(self):
        skill = (ROOT / "claude/skills/deep-review/SKILL.md").read_text()
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

    def test_generic_mode_skips_review_validation(self):
        generic = json.loads(json.dumps(self.review_data()))
        del generic["kind"]
        generic["sections"][-1]["heading"] = "Decision and coverage"
        generic["summary"] = "base <sha> compared"
        output = explainer.render(generic)
        self.assertNotIn('id="finding-1"', output)
        self.assertIn("severity-should-fix", output)  # explicit severity still renders as a badge

    def test_location_link_and_plain_text(self):
        data = self.review_data()
        data["sections"][1]["location"] = {"text": "main.kt:10",
                                           "url": "https://github.com/o/r/blob/abc/main.kt#L10"}
        output = explainer.render(data)
        self.assertIn('href="https://github.com/o/r/blob/abc/main.kt#L10"', output)
        for bad_location in ({"text": "x", "url": "http://example.org"},
                             {"text": "x", "url": "https://u:p@example.org"},
                             {"text": "x", "url": "https://example.org", "line": 5}):
            data["sections"][1]["location"] = bad_location
            with self.subTest(location=bad_location), self.assertRaises(ValueError):
                explainer.render(data)
        data["sections"][1]["location"] = "see https://example.org/a"
        output = explainer.render(data)
        self.assertNotIn('href="https://example.org/a"', output)

    def test_csp_hash_matches_inline_script(self):
        output = explainer.render(self.data)
        csp = re.search(r"script-src 'sha256-([^']+)'", output).group(1)
        script = re.search(r"<script>(.*?)</script>", output, re.DOTALL).group(1)
        digest = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode("ascii")
        self.assertEqual(csp, digest)
        self.assertNotIn("script-src 'unsafe-inline'", output)

    def test_copy_script_checks_execcommand_result(self):
        output = explainer.render(self.data)
        self.assertIn("copied = document.execCommand('copy')", output)
        self.assertIn("Copy failed — select manually", output)

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

    def block_data(self):
        return {
            "title": "Ordered explanation",
            "summary": "The important relationship is visible.",
            "sections": [{
                "heading": "Mechanism",
                "blocks": [
                    {"type": "callout", "title": "Key rule",
                     "text": "Validate before saving."},
                    {"type": "text", "text": "Start with one concrete input."},
                    {"type": "comparison",
                     "left": {"label": "Expected", "value": "accepted",
                              "text": "The valid value is stored."},
                     "right": {"label": "Actual", "value": "rejected",
                               "text": "The old implementation drops it."},
                     "caption": "The differing outcome is the point."},
                    {"type": "steps", "items": ["Read input", "Validate", "Store"]},
                    {"type": "code", "code": "save(validate(value))"},
                    {"type": "details", "summary": "Evidence",
                     "blocks": [
                         {"type": "text", "text": "Trace: parser → validator → store."},
                         {"type": "steps", "items": ["Parser accepts", "Validator rejects"]},
                     ]},
                    {"type": "comments", "items": ["Can we validate before saving?"]},
                ],
            }],
        }

    def test_ordered_blocks_render_in_declared_order(self):
        output = explainer.render(self.block_data())
        fragments = [
            "Key rule", "Start with one concrete input.", "Expected", "Actual",
            "Read input", "save(validate(value))", "Evidence",
            "Can we validate before saving?",
        ]
        positions = [output.index(fragment) for fragment in fragments]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('class="callout"', output)
        self.assertIn('class="comparison"', output)
        self.assertIn('class="supporting"', output)
        self.assertEqual(output.count('class="copy"'), 1)

    def test_blocks_reject_ambiguous_or_invalid_input(self):
        cases = [
            {"heading": "Mixed", "blocks": [], "paragraphs": []},
            {"heading": "Unknown", "blocks": [{"type": "video", "url": "x"}]},
            {"heading": "Extra", "blocks": [{"type": "text", "text": "x", "html": "<b>x</b>"}]},
            {"heading": "Comparison", "blocks": [{
                "type": "comparison", "left": {"label": "Before", "value": "x"},
                "right": {"label": "After"},
            }]},
            {"heading": "Details", "blocks": [{
                "type": "details", "summary": "Nested", "blocks": [{
                    "type": "details", "summary": "Too deep",
                    "blocks": [{"type": "text", "text": "x"}],
                }],
            }]},
            {"heading": "Hidden diagram", "blocks": [{
                "type": "details", "summary": "Evidence", "blocks": [{
                    "type": "diagram", "source": "flowchart TD\nA-->B",
                    "caption": "Flow", "text_alt": "A leads to B.",
                }],
            }]},
        ]
        for section in cases:
            with self.subTest(section=section["heading"]), self.assertRaises(ValueError):
                explainer.render({
                    "title": "Invalid", "summary": "Invalid", "sections": [section],
                })

    def test_review_finding_accepts_direct_comment_block(self):
        data = self.review_data()
        data["sections"][1].pop("paragraphs")
        data["sections"][1].pop("comments")
        data["sections"][1]["blocks"] = [
            {"type": "text", "text": "Expected differs from actual."},
            {"type": "comments", "items": ["Please preserve the valid value."]},
        ]
        output = explainer.render(data)
        self.assertIn("Please preserve the valid value.", output)
        data["sections"][1]["blocks"] = [{
            "type": "details", "summary": "Hidden", "blocks": [
                {"type": "comments", "items": ["Not a primary comment"]},
            ],
        }]
        with self.assertRaises(ValueError):
            explainer.render(data)

    def test_real_mermaid_rendering_is_static_accessible_and_namespaced(self):
        if not explainer.MERMAID_CLI.is_file():
            self.skipTest("local Mermaid CLI is not installed")
        data = {
            "title": "Diagram", "summary": "Static diagram",
            "sections": [{"heading": "Flow", "blocks": [
                {"type": "diagram",
                 "source": "flowchart TD\n A[Input] --> B{Valid?}\n B -->|Yes| C[Save]",
                 "caption": "Validation controls whether input is saved.",
                 "text_alt": "Input reaches a validation decision; valid input is saved."},
                {"type": "diagram",
                 "source": "sequenceDiagram\n Client->>Service: Request\n Service-->>Client: Response",
                 "caption": "A client request receives a service response.",
                 "text_alt": "The client sends a request and the service returns a response."},
            ]}],
        }
        output = explainer.render(data)
        self.assertEqual(len(re.findall(r'class="[^"]*mermaid-svg[^"]*"', output)), 4)
        self.assertIn("diagram-0-0-title diagram-0-0-description", output)
        self.assertIn("diagram-0-1-title diagram-0-1-description", output)
        self.assertEqual(output.count(" diagram-light"), 2)
        self.assertEqual(output.count(" diagram-dark"), 2)
        self.assertIn("diagram-0-0-dark-title", output)
        self.assertIn('aria-hidden="true"', output)
        self.assertIn("<summary>Mermaid source</summary>", output)
        self.assertIn("flowchart TD", output)
        self.assertNotIn("<foreignObject", output)
        self.assertNotIn("http://www.w3.org/1999/xhtml", output)

    def test_mermaid_failures_are_explicit(self):
        block = {
            "title": "Diagram", "summary": "Static diagram",
            "sections": [{"heading": "Flow", "blocks": [{
                "type": "diagram", "source": "flowchart TD\nA-->B",
                "caption": "A leads to B.", "text_alt": "Node A leads to node B.",
            }]}],
        }
        with patch.object(explainer, "MERMAID_CLI", self.base / "missing-mmdc"):
            with self.assertRaisesRegex(ValueError, "not installed"):
                explainer.render(block)
        directive = json.loads(json.dumps(block))
        directive["sections"][0]["blocks"][0]["source"] = (
            "%%{init: {'securityLevel': 'loose'}}%%\nflowchart TD\nA-->B"
        )
        with self.assertRaisesRegex(ValueError, "not supported"):
            explainer.render(directive)
        frontmatter = json.loads(json.dumps(block))
        frontmatter["sections"][0]["blocks"][0]["source"] = (
            "---\nconfig:\n  securityLevel: loose\n---\nflowchart TD\nA-->B"
        )
        with self.assertRaisesRegex(ValueError, "frontmatter"):
            explainer.render(frontmatter)
        if explainer.MERMAID_CLI.is_file():
            invalid = json.loads(json.dumps(block))
            invalid["sections"][0]["blocks"][0]["source"] = "flowchart TD\nA --"
            with self.assertRaisesRegex(ValueError, "rendering failed"):
                explainer.render(invalid)

    def test_mermaid_browser_is_configured_without_network_access(self):
        def fake_run(command, **_kwargs):
            puppeteer_path = Path(command[command.index("--puppeteerConfigFile") + 1])
            config = json.loads(puppeteer_path.read_text())
            self.assertIn("--disable-background-networking", config["args"])
            self.assertIn("--proxy-server=http://127.0.0.1:9", config["args"])
            output_path = Path(command[command.index("--output") + 1])
            output_path.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0,0 L1,1"/></svg>'
            )
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(explainer, "MERMAID_CLI", Path(sys.executable)), \
                patch.object(explainer.subprocess, "run", side_effect=fake_run):
            output = explainer.render_mermaid(
                "flowchart TD\nA-->B", "Caption", "A leads to B.", "diagram",
            )
        self.assertIn("A leads to B.", output)

    def test_svg_sanitizer_rejects_active_or_external_content(self):
        unsafe = [
            '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg"><rect onload="alert(1)"/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.org/x"/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg"><style>@import "https://example.org/x";</style><rect/></svg>',
            '<html><body>not svg</body></html>',
            '<svg xmlns="http://www.w3.org/2000/svg">',
        ]
        for svg in unsafe:
            with self.subTest(svg=svg), self.assertRaises(ValueError):
                explainer.sanitize_mermaid_svg(svg, "Caption", "Alternative", "diagram")
        safe = explainer.sanitize_mermaid_svg(
            '<svg xmlns="http://www.w3.org/2000/svg"><defs><marker id="arrow">'
            '<path d="M0,0 L1,1"/></marker></defs><path id="edge" d="M0,0 L1,1" '
            'marker-end="url(#arrow)"/></svg>',
            "Caption", "Alternative", "diagram",
        )
        self.assertIn('marker-end="url(#diagram-arrow)"', safe)
        self.assertIn('id="diagram-edge"', safe)

    def test_failed_diagram_preserves_existing_artifact(self):
        path = explainer.save(self.repo, "stable", self.data, self.home)
        original = path.read_bytes()
        data = {
            "title": "Replacement", "summary": "Must not replace",
            "sections": [{"heading": "Diagram", "blocks": [{
                "type": "diagram", "source": "flowchart TD\nA-->B",
                "caption": "A leads to B.", "text_alt": "A leads to B.",
            }]}],
        }

        def fail(*args, **kwargs):
            raise ValueError("unsafe generated SVG")

        with self.assertRaisesRegex(ValueError, "unsafe generated SVG"):
            explainer.save(self.repo, "stable", data, self.home, mermaid_renderer=fail)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(path.parent.iterdir()), [path])
        if explainer.MERMAID_CLI.is_file():
            data["sections"][0]["blocks"][0]["source"] = "flowchart TD\nA --"
            with self.assertRaisesRegex(ValueError, "rendering failed"):
                explainer.save(self.repo, "stable", data, self.home)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_table_block_renders_and_validates(self):
        data = {**self.data, "sections": [{"heading": "T", "blocks": [{
            "type": "table",
            "columns": [{"label": "Region", "align": "left"}, {"label": "Revenue", "align": "right"}],
            "rows": [["emea", "1,200"], ["apac", "980"]],
            "caption": "Weekly totals",
        }]}]}
        output = explainer.render(data)
        self.assertIn('<th style="text-align:left">Region</th>', output)
        self.assertIn('<td style="text-align:right">980</td>', output)
        self.assertIn("Weekly totals", output)
        for broken in [
            {"type": "table", "columns": ["A"], "rows": [["1", "2"]]},
            {"type": "table", "columns": [{"label": "A", "align": "middle"}], "rows": [["1"]]},
            {"type": "table", "columns": ["A"], "rows": "nope"},
            {"type": "table", "columns": [], "rows": []},
            {"type": "table", "columns": ["A"], "rows": [[None]]},
        ]:
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                explainer.render({**self.data, "sections": [{"heading": "T", "blocks": [broken]}]})
        nested = {**self.data, "sections": [{"heading": "T", "blocks": [{
            "type": "details", "summary": "Evidence", "blocks": [{
                "type": "table", "columns": ["A"], "rows": [["1"]]}],
        }]}]}
        self.assertIn("data-table", explainer.render(nested))

    def test_chart_block_renders_sanitized_static_svg(self):
        chart = {
            "type": "chart", "kind": "bar", "labels": ["W1", "W2"],
            "series": [{"name": "reported", "values": [120, 150]},
                       {"name": "actual", "values": [120, 90]}],
            "yLabel": "USD", "caption": "Fan-out gap", "text_alt": "Actuals fall behind reported.",
        }
        output = explainer.render({**self.data, "sections": [{"heading": "C", "blocks": [chart]}]})
        self.assertEqual(output.count('class="mermaid-svg"'), 1)
        self.assertIn("<rect", output)
        self.assertIn("var(--chart-1)", output)
        self.assertIn("Fan-out gap", output)
        self.assertIn("Chart data", output)
        self.assertNotIn("<foreignObject", output)
        line = dict(chart, kind="line")
        output = explainer.render({**self.data, "sections": [{"heading": "C", "blocks": [line]}]})
        self.assertIn("<polyline", output)
        for broken, fragment in [
            (dict(chart, kind="area"), "kind"),
            (dict(chart, labels=["W1"], series=chart["series"]), "numbers"),
            (dict(chart, series=[{"name": "s", "values": ["a", "b"]}]), "numbers"),
            (dict(chart, series=[]), "series"),
            (dict(chart, series=[{"name": "s", "values": [True, 1]}]), "numbers"),
            (dict(chart, caption=None), "caption"),
        ]:
            with self.subTest(broken=broken.get("kind"), fragment=fragment), self.assertRaisesRegex(
                    ValueError, fragment):
                explainer.render({**self.data, "sections": [{"heading": "C", "blocks": [broken]}]})
        with self.assertRaisesRegex(ValueError, "details"):
            explainer.render({**self.data, "sections": [{"heading": "C", "blocks": [{
                "type": "details", "summary": "Hidden", "blocks": [chart]}]}]})

    def test_dbml_block_converts_through_a_strict_subset(self):
        source = (
            "Table users {\n  id bigint [pk, increment]\n"
            "  email varchar [unique, not null]\n}\n"
            "Table orders {\n  id bigint [pk]\n  user_id bigint [not null]\n}\n"
            "Ref: orders.user_id > users.id\n")
        mermaid = explainer.dbml_to_mermaid(source, "dbml")
        self.assertIn("erDiagram", mermaid)
        self.assertIn("t0[users] {", mermaid)
        self.assertIn("bigint id PK", mermaid)
        self.assertIn('varchar email UK "not null"', mermaid)
        self.assertIn("t1 }o--|| t0 : user_id", mermaid)
        for bad, fragment in [
            ("Table users [headercolor: #fff] {\n a int\n}", "settings"),
            ("Table users {\n a int\n}\nEnum e { x }\n", "ENUM"),
            ("Table users {\n a int [fk]\n}", "constraint"),
            ("Table users {\n Note: 'hi'\n}", "Note"),
            ("Table users {\n amount numeric(10,2)\n}", "column syntax"),
            ("Table users {\n a int\n}\nRef: orders.user_id > users.id\n", "unknown table"),
            ("Table users {\n a int\n}\nRef: users.a > users.missing\n", "unknown column"),
            ("Table users {\n a int\n", "unclosed"),
            ("Table users {\n a int\n}\nTable users {\n b int\n}", "duplicate"),
            ("// just a comment\nSELECT 1\n", "unsupported DBML"),
        ]:
            with self.subTest(bad=bad.splitlines()[-1]), self.assertRaisesRegex(ValueError, fragment):
                explainer.dbml_to_mermaid(bad, "dbml")

    def test_dbml_block_renders_through_mermaid(self):
        if not explainer.MERMAID_CLI.is_file():
            self.skipTest("local Mermaid CLI is not installed")
        data = {**self.data, "sections": [{"heading": "S", "blocks": [{
            "type": "dbml", "caption": "Orders reference users.",
            "text_alt": "Each order belongs to one user; users have many orders.",
            "source": "Table users {\n  id bigint [pk]\n}\nTable orders {\n  id bigint [pk]\n  user_id bigint\n}\nRef: orders.user_id > users.id",
        }]}]}
        output = explainer.render(data)
        self.assertEqual(len(re.findall(r'class="[^"]*mermaid-svg[^"]*"', output)), 2)
        self.assertIn("DBML source", output)

    def test_citations_link_claims_to_numbered_sources(self):
        data = {**self.data,
                "summary": "Claim one [[1]] and two [[2]].",
                "sections": [{"heading": "H", "paragraphs": ["Cited [[1]].", "Uncited."]}],
                "sources": [
                    {"label": "One", "url": "https://example.org/1", "date": "accessed 2026-10-27"},
                    {"label": "Two", "url": "https://example.org/2"},
                ]}
        output = explainer.render(data)
        self.assertEqual(len(re.findall(r'id="source-\d+"', output)), 2)
        self.assertEqual(output.count('href="#source-1"'), 2)  # summary + paragraph
        self.assertEqual(output.count('href="#source-2"'), 1)
        self.assertIn("accessed 2026-10-27", output)
        self.assertNotIn("\x00", output)
        too_far = json.loads(json.dumps(data))
        too_far["sections"][0]["paragraphs"] = ["Gone too far [[3]]."]
        with self.assertRaisesRegex(ValueError, "does not match any source"):
            explainer.render(too_far)
        no_sources = json.loads(json.dumps(data))
        del no_sources["sources"]
        with self.assertRaisesRegex(ValueError, "require at least one source"):
            explainer.render(no_sources)
        literal = {**self.data,
                   "sections": [{"heading": "H", "comments": ["see [[1]] and [[9]]"]}],
                   "sources": [{"label": "L", "url": "https://example.org"}]}
        output = explainer.render(literal)
        self.assertIn("[[9]]", output)
        self.assertNotIn('href="#source-', output)

    def test_block_styles_cover_accessibility_responsive_theme_and_print(self):
        output = explainer.render(self.block_data())
        self.assertIn("summary:focus-visible", output)
        self.assertIn("@media(max-width:600px)", output)
        self.assertIn("@media(prefers-color-scheme:dark)", output)
        self.assertIn("details:not([open])>:not(summary)", output)
        self.assertIn("grid-template-columns:1fr", output)

    def test_mermaid_dependency_is_local_pinned_and_setup_managed(self):
        package = json.loads((ROOT / "scripts/mermaid/package.json").read_text())
        self.assertEqual(package["dependencies"]["@mermaid-js/mermaid-cli"], "12.0.0")
        self.assertEqual(package["dependencies"]["puppeteer"], "25.16.0")
        self.assertTrue(package["allowScripts"]["puppeteer@25.16.0"])
        lock = json.loads((ROOT / "scripts/mermaid/package-lock.json").read_text())
        self.assertEqual(lock["packages"][""]["dependencies"], package["dependencies"])
        setup = (ROOT / "setup-dev-env.sh").read_text()
        self.assertIn('npm ci --prefix "$REPO_DIR/scripts/mermaid"', setup)
        self.assertNotIn("npx mmdc", setup)


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


if __name__ == "__main__":
    unittest.main()

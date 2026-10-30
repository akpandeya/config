import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ship = load("epic_ship", ROOT / "claude/scripts/epic-ship.py")

TASKS = ["task-00", "task-01a", "task-02"]


def config(**extra):
    raw = {
        "session": "claude:sonnet",
        "defaults": {
            "implement": "opencode:impl-7",
            "review": "claude:rev-7",
            "fix": "claude:fix-7",
            "escalate": "claude:esc-7",
            "fallback": "agy:fb-7",
        },
    }
    raw.update(extra)
    return ship.load_run_config(raw, TASKS)


class RunConfigTest(unittest.TestCase):
    def test_per_task_override_wins_only_for_its_stage(self):
        cfg = config(tasks={"task-01a": {"review": "claude:opus-x"}})
        models = ship.stage_models(cfg, "task-01a")
        self.assertEqual(models.review, "claude:opus-x")
        self.assertEqual(models.implement, "opencode:impl-7")
        self.assertEqual(ship.stage_models(cfg, "task-02").review, "claude:rev-7")

    def test_rejects_partial_defaults(self):
        raw = {"session": "claude:sonnet", "defaults": {"implement": "opencode:x"}}
        with self.assertRaises(ship.ConfigError):
            ship.load_run_config(raw, TASKS)

    def test_rejects_unknown_task_and_bad_model(self):
        with self.assertRaises(ship.ConfigError):
            config(skip={"task-99": "typo"})
        with self.assertRaises(ship.ConfigError):
            config(tasks={"task-02": {"review": "opus"}})

    def test_session_must_be_claude(self):
        with self.assertRaises(ship.ConfigError):
            config(session="opencode:glm")


class SkipReasonTest(unittest.TestCase):
    def test_blocked_until_dependency_done(self):
        cfg = config()
        task = {"id": "task-02", "blockedBy": ["task-01a"]}
        self.assertIn("task-01a (failed)", ship.skip_reason(task, {"task-01a": "failed"}, cfg))
        self.assertIsNone(ship.skip_reason(task, {"task-01a": "done"}, cfg))

    def test_configured_skip(self):
        cfg = config(skip={"task-00": "mock not approved"})
        self.assertEqual(ship.skip_reason({"id": "task-00"}, {}, cfg), "config: mock not approved")


class ParseResultTest(unittest.TestCase):
    def write(self, data):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "r.json"
        path.write_text(json.dumps(data))
        return path

    def test_reads_complete_result(self):
        path = self.write({"status": "MERGED_WITH_KNOWN_ISSUES", "pr": "https://x/pull/731",
                           "followUp": "https://x/issues/732", "branch": "agy/b-731", "notes": "n"})
        result = ship.parse_result(path)
        self.assertEqual((result.status, result.pr_url, result.follow_up, result.branch),
                         ("MERGED_WITH_KNOWN_ISSUES", "https://x/pull/731", "https://x/issues/732", "agy/b-731"))

    def test_rejects_missing_keys_unknown_status_and_merge_without_pr(self):
        for data in ({"status": "MERGED"},
                     {"status": "DONE", "pr": "u", "followUp": "", "branch": "b", "notes": ""},
                     {"status": "MERGED", "pr": "", "followUp": "", "branch": "b", "notes": ""}):
            with self.assertRaises(ValueError):
                ship.parse_result(self.write(data))


class SessionPromptTest(unittest.TestCase):
    def test_carries_every_stage_model_issue_and_brief(self):
        models = ship.StageModels("opencode:impl-7", "claude:rev-7", "claude:fix-7", "claude:esc-7", "agy:fb-7")
        prompt = ship.build_session_prompt(repo="o/r", sub_issue=4711, models=models,
                                           brief="BRIEF-MARKER", result_path=Path("/p/results/t.json"))
        for needle in ("/issue-ship o/r 4711", "IMPLEMENT=opencode:impl-7", "REVIEW=claude:rev-7",
                       "FIX=claude:fix-7", "claude:esc-7", "agy:fb-7", "BRIEF-MARKER", "/p/results/t.json"):
            self.assertIn(needle, prompt)


if __name__ == "__main__":
    unittest.main()

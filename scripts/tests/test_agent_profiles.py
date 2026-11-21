import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
LAUNCHERS = ROOT / "agents/bin"
HARNESSES = ("pi", "opencode", "claude", "copilot")
INSTRUCTIONS = {
    "pi": "AGENTS.md",
    "opencode": "AGENTS.md",
    "claude": "CLAUDE.md",
    "copilot": "copilot-instructions.md",
}


class AgentProfileTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / "home"
        self.personal_root = self.home / "code/personal"
        self.work_root = self.home / "code/work"
        self.personal_repo = self.personal_root / "project"
        self.work_repo = self.work_root / "project"
        self.personal_repo.mkdir(parents=True)
        self.work_repo.mkdir(parents=True)
        self.git_init(self.personal_repo)
        self.git_init(self.work_repo)
        self.personal_memory = self.personal_root / "pi-memory"
        self.work_memory = self.work_root / "agent-memory"
        self.personal_memory.mkdir()
        self.work_memory.mkdir()
        for profile in ("personal", "work"):
            for harness, filename in INSTRUCTIONS.items():
                config = self.home / f".agent/profiles/{profile}/{harness}"
                config.mkdir(parents=True)
                (config / filename).write_text(f"{profile.upper()}_{harness.upper()}_CANARY")

        self.fake_bin = self.base / "bin"
        self.fake_bin.mkdir()
        for harness in HARNESSES:
            fake = self.fake_bin / harness
            fake.write_text(
                f"#!{sys.executable}\n"
                "import json, os, pathlib, sys\n"
                "with open(os.environ['AGENT_TEST_CAPTURE'], 'w') as stream:\n"
                "    json.dump({'harness': pathlib.Path(sys.argv[0]).name, 'argv': sys.argv[1:],\n"
                "               'profile': os.environ.get('AGENT_PROFILE_ROOT'),\n"
                "               'scope': os.environ.get('AGENT_MEMORY_SCOPE'),\n"
                "               'memory': os.environ.get('AGENT_MEMORY_ROOT'),\n"
                "               'device': os.environ.get('AGENT_DEVICE_MEMORY_FILE'),\n"
                "               'pi_agent': os.environ.get('PI_CODING_AGENT_DIR'),\n"
                "               'pi_sessions': os.environ.get('PI_CODING_AGENT_SESSION_DIR'),\n"
                "               'opencode_config': os.environ.get('OPENCODE_CONFIG_DIR'),\n"
                "               'opencode_config_file': os.environ.get('OPENCODE_CONFIG'),\n"
                "               'opencode_config_content': os.environ.get('OPENCODE_CONFIG_CONTENT'),\n"
                "               'xdg_data': os.environ.get('XDG_DATA_HOME'),\n"
                "               'xdg_state': os.environ.get('XDG_STATE_HOME'),\n"
                "               'xdg_cache': os.environ.get('XDG_CACHE_HOME'),\n"
                "               'claude_config': os.environ.get('CLAUDE_CONFIG_DIR'),\n"
                "               'copilot_home': os.environ.get('COPILOT_HOME'),\n"
                "               'git_dir': os.environ.get('GIT_DIR'),\n"
                "               'git_work_tree': os.environ.get('GIT_WORK_TREE')}, stream)\n"
            )
            fake.chmod(0o755)

    def git_init(self, path):
        subprocess.run(["git", "init", "-q", str(path)], check=True)

    def run_profile(self, harness, profile, cwd, *args, extra_env=None):
        capture = self.base / f"capture-{harness}-{profile}-{len(list(self.base.glob('capture-*')))}.json"
        env = os.environ.copy()
        env.update({
            "HOME": str(self.home),
            "PATH": str(self.fake_bin) + os.pathsep + env["PATH"],
            "AGENT_TEST_CAPTURE": str(capture),
            "XDG_DATA_HOME": str(self.home / ".data"),
            "XDG_STATE_HOME": str(self.home / ".state"),
            "XDG_CACHE_HOME": str(self.home / ".cache-custom"),
            "PI_CODING_AGENT_DIR": "/inherited/wrong/pi",
            "PI_CODING_AGENT_SESSION_DIR": "/inherited/wrong/pi-sessions",
            "OPENCODE_CONFIG_DIR": "/inherited/wrong/opencode",
            "OPENCODE_CONFIG": "/inherited/wrong/opencode.json",
            "OPENCODE_CONFIG_CONTENT": "{\"model\":\"inherited/wrong\"}",
            "CLAUDE_CONFIG_DIR": "/inherited/wrong/claude",
            "COPILOT_HOME": "/inherited/wrong/copilot",
        })
        if extra_env:
            env.update(extra_env)
        result = subprocess.run(
            [str(LAUNCHERS / f"{harness}-{profile}"), *args],
            cwd=cwd, env=env, text=True, capture_output=True,
        )
        captured = json.loads(capture.read_text()) if capture.exists() else None
        return result, captured

    def test_personal_pi_overrides_inherited_paths_and_passes_arguments(self):
        result, captured = self.run_profile(
            "pi", "personal", self.personal_repo, "--model", "distinguishing-model", "--session-id", "personal-id"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(captured["argv"], ["--model", "distinguishing-model", "--session-id", "personal-id"])
        profile = self.home / ".agent/profiles/personal"
        self.assertEqual(captured["profile"], str(profile))
        self.assertEqual(captured["pi_agent"], str(profile / "pi"))
        self.assertEqual(captured["pi_sessions"], str(self.home / ".data/agent-profiles/personal/pi/sessions"))
        self.assertEqual(captured["scope"], "personal")
        self.assertEqual(captured["memory"], str(profile / "memory"))
        self.assertEqual((profile / "memory").resolve(), self.personal_memory.resolve())
        self.assertEqual(captured["device"], str(profile / "device.md"))

    def test_work_opencode_uses_standalone_and_distinct_config_and_data(self):
        result, captured = self.run_profile("opencode", "work", self.work_repo, "--session", "work-id")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(captured["argv"], ["--standalone", "--session", "work-id"])
        profile = self.home / ".agent/profiles/work"
        self.assertEqual(captured["opencode_config"], str(profile / "opencode"))
        self.assertIsNone(captured["opencode_config_file"])
        self.assertIsNone(captured["opencode_config_content"])
        self.assertEqual(captured["xdg_data"], str(self.home / ".data/agent-profiles/work"))
        self.assertEqual(captured["xdg_state"], str(self.home / ".state/agent-profiles/work"))
        self.assertEqual(captured["xdg_cache"], str(self.home / ".cache-custom/agent-profiles/work"))
        self.assertEqual(captured["memory"], str(profile / "memory"))
        self.assertEqual((profile / "memory").resolve(), self.work_memory.resolve())

    def test_claude_and_copilot_use_the_same_scope_with_native_config_roots(self):
        for harness, key in (("claude", "claude_config"), ("copilot", "copilot_home")):
            with self.subTest(harness=harness):
                result, captured = self.run_profile(harness, "work", self.work_repo, "--model", "work-model")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(captured["harness"], harness)
                self.assertEqual(captured["argv"], ["--model", "work-model"])
                self.assertEqual(captured[key], str(self.home / f".agent/profiles/work/{harness}"))
                self.assertEqual(captured["scope"], "work")

    def test_wrong_profile_and_unknown_location_fail_before_harness(self):
        wrong, captured = self.run_profile("pi", "personal", self.work_repo)
        self.assertEqual(wrong.returncode, 2)
        self.assertIsNone(captured)
        self.assertIn("refusing to cross scopes", wrong.stderr)

        unknown = self.home / "elsewhere"
        unknown.mkdir()
        result, captured = self.run_profile("opencode", "work", unknown)
        self.assertEqual(result.returncode, 2)
        self.assertIsNone(captured)
        self.assertIn("without scoped memory", result.stderr)

    def test_cross_scope_memory_symlink_is_rejected(self):
        result, captured = self.run_profile(
            "claude", "work", self.work_repo, extra_env={"AGENT_WORK_MEMORY_DIR": str(self.personal_memory)}
        )
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(captured)
        self.assertIn("outside", result.stderr)
        self.assertFalse((self.home / ".agent/profiles/work/memory").exists())

    def test_existing_wrong_memory_link_is_not_replaced(self):
        link = self.home / ".agent/profiles/work/memory"
        link.symlink_to(self.personal_memory)
        result, captured = self.run_profile("copilot", "work", self.work_repo)
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(captured)
        self.assertEqual(link.resolve(), self.personal_memory.resolve())
        self.assertIn("different memory store", result.stderr)

    def test_missing_memory_launches_without_a_memory_root(self):
        missing = self.work_root / "missing-memory"
        result, captured = self.run_profile(
            "pi", "work", self.work_repo, extra_env={"AGENT_WORK_MEMORY_DIR": str(missing)}
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(captured["memory"])
        self.assertFalse((self.home / ".agent/profiles/work/memory").exists())
        self.assertIn("without long-term memory", result.stderr)

    def test_config_and_data_symlink_escapes_are_rejected(self):
        config = self.home / ".agent/profiles/personal/claude"
        config.rename(self.home / ".agent/profiles/personal/claude-original")
        config.symlink_to(self.home / ".agent/profiles/work/claude")
        result, captured = self.run_profile("claude", "personal", self.personal_repo)
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(captured)
        self.assertIn("symlink scope escape", result.stderr)

        data_profiles = self.home / ".data/agent-profiles"
        data_profiles.mkdir(parents=True, exist_ok=True)
        (data_profiles / "personal").rmdir()
        (data_profiles / "personal").symlink_to(data_profiles / "work")
        result, captured = self.run_profile("pi", "personal", self.personal_repo)
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(captured)
        self.assertIn("symlink scope escape", result.stderr)

    def test_instruction_link_must_match_harness_and_profile(self):
        instruction = self.home / ".agent/profiles/personal/pi/AGENTS.md"
        generated = self.home / ".config/agent-context/pi-work.md"
        generated.parent.mkdir(parents=True)
        generated.write_text("WORK_CANARY")
        instruction.unlink()
        instruction.symlink_to(generated)
        result, captured = self.run_profile("pi", "personal", self.personal_repo)
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(captured)
        self.assertIn("does not match", result.stderr)

    def test_inherited_git_worktree_variables_cannot_change_scope(self):
        result, captured = self.run_profile(
            "pi", "personal", self.personal_repo,
            extra_env={"GIT_DIR": str(self.work_repo / ".git"), "GIT_WORK_TREE": str(self.work_repo)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(captured["scope"], "personal")
        self.assertIsNone(captured["git_dir"])
        self.assertIsNone(captured["git_work_tree"])

    def test_directory_arguments_cannot_cross_scope(self):
        for harness, arguments in (
            ("opencode", (str(self.personal_repo),)),
            ("opencode", ("--directory", str(self.personal_repo))),
            ("opencode", (f"--directory={self.personal_repo}",)),
            ("copilot", ("-C", str(self.personal_repo))),
        ):
            with self.subTest(harness=harness, arguments=arguments):
                result, captured = self.run_profile(harness, "work", self.work_repo, *arguments)
                self.assertEqual(result.returncode, 2)
                self.assertIsNone(captured)
                self.assertIn("crosses", result.stderr)
        result, captured = self.run_profile("opencode", "work", self.work_repo, str(self.work_repo))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(captured["argv"], ["--standalone", str(self.work_repo)])

    def test_pi_external_session_paths_are_rejected_but_ids_pass(self):
        for arguments in (
            ("--session", str(self.home / "other-session.jsonl")),
            ("--fork=../other-session",),
            ("--session", "other-session.jsonl"),
        ):
            with self.subTest(arguments=arguments):
                result, captured = self.run_profile("pi", "work", self.work_repo, *arguments)
                self.assertEqual(result.returncode, 2)
                self.assertIsNone(captured)
                self.assertIn("session paths are disabled", result.stderr)
        result, captured = self.run_profile("pi", "work", self.work_repo, "--session", "distinguishing-id")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(captured["argv"], ["--session", "distinguishing-id"])

    def test_setup_validates_scoped_roots_before_linking_resources(self):
        setup = (ROOT / "setup-dev-env.sh").read_text()
        composer = setup.index('python3 "$REPO_DIR/scripts/install-agent-instructions.py"\nfi')
        scoped_links = setup.index('link_config "$HOME/.pi/agent/extensions" "$profile_root/pi/extensions"')
        self.assertLess(composer, scoped_links)

    def test_pi_session_dir_override_is_reserved(self):
        for option in ("--session-dir", "--session-dir=/tmp/other"):
            with self.subTest(option=option):
                args = (option, str(self.home / "other")) if option == "--session-dir" else (option,)
                result, captured = self.run_profile("pi", "work", self.work_repo, *args)
                self.assertEqual(result.returncode, 2)
                self.assertIsNone(captured)
                self.assertIn("reserved", result.stderr)

    def test_worktree_location_not_repository_identity_selects_scope(self):
        source = self.personal_root / "config-source"
        source.mkdir()
        self.git_init(source)
        subprocess.run([
            "git", "-C", str(source), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "-q", "--allow-empty", "-m", "initial",
        ], check=True)
        worktree = self.work_root / "config-worktree"
        subprocess.run(["git", "-C", str(source), "worktree", "add", "-q", str(worktree)], check=True)
        result, captured = self.run_profile("opencode", "work", worktree)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(captured["scope"], "work")


if __name__ == "__main__":
    unittest.main()

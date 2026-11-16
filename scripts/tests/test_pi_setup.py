"""Pi launcher and installer checks using temporary repos and stub CLIs."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class PiSetupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.code = self.base / "code"
        (self.code / "personal/example/.git").mkdir(parents=True)
        self.shell = self.base / "shell"
        self.shell.mkdir()
        shutil.copy(ROOT / "shell/dev.sh", self.shell / "dev.sh")
        (self.shell / "dev-shortcuts.conf").write_text(
            "demo = personal/example : pi\n"
            "pc = personal/example : claude\n"
            "pi = personal/example : claude\n"
        )
        self.log = self.base / "calls.json"
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}",
                        DEV_CODE_ROOT=str(self.code), CALL_LOG=str(self.log))

    def executable(self, name, content):
        target = self.bin / name
        target.write_text(content)
        target.chmod(0o755)
        return target

    def stub_pi(self):
        return self.executable("pi", f"#!{shutil.which('python3')}\n"
                               "import json, os, sys\n"
                               "from pathlib import Path\n"
                               "Path(os.environ['CALL_LOG']).write_text(json.dumps([os.getcwd(), sys.argv[1:]]))\n")

    def zsh(self, command):
        if not shutil.which("zsh"):
            self.skipTest("zsh unavailable")
        result = subprocess.run(["zsh", "-f", "-c", 'source "$1"; ' + command,
                                 "test", str(self.shell / "dev.sh")],
                                cwd=self.base, env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_current_directory_and_native_pi(self):
        self.stub_pi()
        self.zsh('pc --model "sonnet:high" --print "hello world"')
        self.assertEqual(json.loads(self.log.read_text()),
                         [str(self.base), ["--model", "sonnet:high", "--print", "hello world"]])
        result = self.zsh('whence -w pi; pi "a native prompt"')
        self.assertIn("pi: command", result.stdout)
        self.assertEqual(json.loads(self.log.read_text())[1], ["a native prompt"])
        self.assertIn("shortcut 'pc' ignored", result.stderr)
        self.assertIn("shortcut 'pi' ignored", result.stderr)

    def test_target_resolution_flags_and_persistent_cd(self):
        self.stub_pi()
        for target in ("demo", "example", "personal/example", "personal"):
            with self.subTest(target=target):
                result = self.zsh(f'pc {target} --continue; pwd')
                expected = self.code / ("personal" if target == "personal" else "personal/example")
                self.assertEqual(json.loads(self.log.read_text()), [str(expected), ["--continue"]])
                self.assertEqual(result.stdout.splitlines()[-1], str(expected))

    def test_reload_does_not_warn_for_our_own_shortcuts(self):
        result = self.zsh('source "$1"; source "$1"')
        self.assertNotIn("shortcut 'demo' shadows", result.stderr)
        result = self.zsh('demo() { echo custom; }; source "$1"')
        self.assertIn("shortcut 'demo' shadows", result.stderr)

    def test_exact_shortcut_wins_over_multiple_fuzzy_matches(self):
        self.stub_pi()
        for name in ("work/fda-other", "personal/fda-copy", "work/example"):
            (self.code / name / ".git").mkdir(parents=True)
        # A picker must not be invoked at all for an exact shortcut.
        self.executable("fzf", "#!/bin/bash\nexit 99\n")
        with (self.shell / "dev-shortcuts.conf").open("a") as conf:
            conf.write("fda = personal/example : pi\n")
        self.zsh("pc fda")
        self.assertEqual(json.loads(self.log.read_text()),
                         [str(self.code / "personal/example"), []])

    def test_cancelled_ambiguous_query_never_launches_pi(self):
        self.stub_pi()
        (self.code / "work/example/.git").mkdir(parents=True)
        self.executable("fzf", '#!/bin/bash\ncat >/dev/null\nif [[ "$*" == *--filter=* ]]; then printf "personal/example\\nwork/example\\n"; else exit 130; fi\n')
        self.zsh("pc example; result=$?; [[ $result -ne 0 ]]")
        self.assertFalse(self.log.exists())

    def test_shortcut_and_picker_launch_pi(self):
        self.stub_pi()
        self.zsh('demo --resume')
        self.assertEqual(json.loads(self.log.read_text())[1], ["--resume"])
        self.executable("fzf", "#!/bin/bash\ncat >/dev/null\nprintf 'ctrl-p\\npersonal/example\\n'\n")
        self.zsh("dev")
        self.assertEqual(json.loads(self.log.read_text()), [str(self.code / "personal/example"), []])
        self.assertIn("[p]i", (self.shell / "dev.sh").read_text())

    def installer(self, **env):
        return subprocess.run(["bash", str(ROOT / "scripts/install-pi.sh")],
                              env=dict(self.env, **env), text=True, capture_output=True)

    def test_dry_run_and_skip_never_call_npm(self):
        self.executable("npm", "#!/bin/bash\nexit 99\n")
        for env in ({"DRY_RUN": "1"}, {"SKIP_PI": "1"}):
            result = self.installer(**env)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Would run if Pi is missing", self.installer(DRY_RUN="1").stdout)

    def test_existing_install_is_verified_not_upgraded(self):
        if not shutil.which("node"):
            self.skipTest("node unavailable")
        package = self.base / "npm-root/@earendil-works/pi-coding-agent"
        package.mkdir(parents=True)
        (package / "package.json").write_text(json.dumps({
            "name": "@earendil-works/pi-coding-agent", "bin": {"pi": "cli.sh"}}))
        cli = package / "cli.sh"
        cli.write_text("#!/bin/bash\necho 1.2.3\n")
        cli.chmod(0o755)
        (self.bin / "pi").symlink_to(cli)
        self.executable("npm", f'#!/bin/bash\nif [ "$*" = "root -g" ]; then echo "{self.base / "npm-root"}"; else exit 99; fi\n')
        for _ in range(2):
            result = self.installer()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("leaving its version unchanged", result.stdout)
            self.assertIn("1.2.3", result.stdout)

    def test_unrelated_pi_is_not_overwritten(self):
        if not shutil.which("node"):
            self.skipTest("node unavailable")
        binary = self.stub_pi()
        original = binary.read_text()
        self.executable("npm", f'#!/bin/bash\necho "{self.base / "missing"}"\n')
        result = self.installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not Pi from the current global npm prefix", result.stderr)
        self.assertEqual(binary.read_text(), original)
        self.assertFalse(self.log.exists())

    def test_old_node_rejected(self):
        self.executable("node", '#!/bin/bash\nif [ "$1" = "--version" ]; then echo v22.18.0; else exit 1; fi\n')
        self.executable("npm", "#!/bin/bash\nexit 99\n")
        result = self.installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("found v22.18.0", result.stderr)

    def test_missing_install_and_verification(self):
        # Isolate PATH from any real Pi installation and npm invocation.
        isolated = self.base / "isolated"
        isolated.mkdir()
        for command in ("bash", "node"):
            binary = shutil.which(command)
            if not binary:
                self.skipTest(f"{command} unavailable")
            (isolated / command).symlink_to(binary)
        npm = isolated / "npm"
        npm.write_text('#!/bin/bash\n'
                       '[ "$*" = "install -g --ignore-scripts @earendil-works/pi-coding-agent" ] || exit 99\n'
                       'printf "#!/bin/bash\\necho installed-version\\n" > "$DEST/pi"\n'
                       '"$CHMOD" +x "$DEST/pi"\n')
        npm.chmod(0o755)
        result = self.installer(PATH=str(isolated), DEST=str(isolated), CHMOD=shutil.which("chmod"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("installed-version", result.stdout)


if __name__ == "__main__":
    unittest.main()

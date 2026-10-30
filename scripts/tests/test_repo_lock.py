import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "claude/scripts/repo-lock.sh"


class RepoLockTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.lock_root = base / "locks"
        self.repo = base / "checkout"
        self.repo.mkdir()
        self.env = {**os.environ, "AGENT_LOCK_ROOT": str(self.lock_root)}

    def run_lock(self, *args):
        return subprocess.run([str(SCRIPT), *args], env=self.env,
                              capture_output=True, text=True)

    def acquire(self, *extra):
        out = self.run_lock("acquire", str(self.repo), "test session", *extra)
        self.assertEqual(out.returncode, 0, out.stderr)
        token_line = [line for line in out.stdout.splitlines() if line.startswith("TOKEN=")]
        self.assertTrue(token_line, out.stdout)
        return token_line[0].split("=", 1)[1]

    def test_acquire_check_release_cycle(self):
        token = self.acquire()

        held = self.run_lock("check", str(self.repo))
        self.assertEqual(held.returncode, 9)
        owner = json.loads(held.stderr.strip().splitlines()[-1])
        self.assertEqual(owner["command"], "test session")
        self.assertEqual(owner["repo"], str(self.repo.resolve()))

        again = self.run_lock("acquire", str(self.repo), "second driver")
        self.assertEqual(again.returncode, 9)
        self.assertIn("refusing", again.stderr)

        wrong = self.run_lock("release", str(self.repo), "not-the-token")
        self.assertEqual(wrong.returncode, 9)
        self.assertIn("token mismatch", wrong.stderr)

        ok = self.run_lock("release", str(self.repo), token)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        free = self.run_lock("check", str(self.repo))
        self.assertEqual(free.returncode, 0)

    def test_force_steals_and_reports_previous_owner(self):
        self.acquire()
        stolen = self.run_lock("acquire", str(self.repo), "rescue session", "--force")
        self.assertEqual(stolen.returncode, 0, stolen.stderr)
        self.assertIn("stealing", stolen.stderr)
        self.assertIn('"command":"test session"', stolen.stderr)

    def test_release_without_lock_is_a_noop(self):
        out = self.run_lock("release", str(self.repo), "anything")
        self.assertEqual(out.returncode, 0)
        self.assertIn("no lock held", out.stdout)

    def test_missing_directory_is_a_usage_error(self):
        out = self.run_lock("acquire", str(self.repo / "nope"), "test")
        self.assertEqual(out.returncode, 2)


if __name__ == "__main__":
    unittest.main()

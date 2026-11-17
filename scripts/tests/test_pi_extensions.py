"""Regression coverage for the vendored pi extensions' enforcement wiring.

Delegates to scripts/tests/pi_extensions.test.mjs (node --test): the code under
test is TypeScript loaded through jiti, so the assertions live in Node. This
wrapper only locates the @earendil-works/pi-coding-agent package and runs it,
so the suite stays discoverable via `python3 -m unittest` like the rest of
scripts/tests. See pi/README.md for what the wiring protects.
"""

import os
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST_FILE = Path(__file__).resolve().parent / "pi_extensions.test.mjs"


def pi_package_root() -> str:
    """Global install root of @earendil-works/pi-coding-agent."""
    npm_root = subprocess.run(
        ["npm", "root", "-g"], capture_output=True, text=True, check=True
    ).stdout.strip()
    return str(Path(npm_root) / "@earendil-works" / "pi-coding-agent")


class PiExtensionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not TEST_FILE.exists():
            raise FileNotFoundError(TEST_FILE)
        cls.env = dict(
            os.environ,
            PI_EXTENSIONS_TEST_ROOT=str(ROOT),
            PI_EXTENSIONS_TEST_PKG=pi_package_root(),
        )

    def test_node_suite_passes(self):
        result = subprocess.run(
            ["node", "--test", str(TEST_FILE)],
            capture_output=True,
            text=True,
            env=self.env,
            timeout=300,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"node --test failed:\n{result.stdout}\n{result.stderr}",
        )
        # Guard against a silent pass: the spec reporter's summary must show
        # real test counts and zero failures.
        passed = re.search(r"pass (\d+)", result.stdout)
        self.assertIsNotNone(passed, f"no test summary in node output:\n{result.stdout}")
        # A floor, not an exact count, so adding cases keeps this green while a
        # mass-skip/empty run still fails.
        self.assertGreaterEqual(int(passed.group(1)), 10, "node suite ran too few tests")
        self.assertIn("fail 0", result.stdout, f"node suite had failures:\n{result.stdout}")


if __name__ == "__main__":
    unittest.main()
import importlib.util
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
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


links = load("pr_comment_links", ROOT / "claude/scripts/pr-comment-links.py")


class RepositoryFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.git("init", "-q", "-b", "main", str(self.repo))
        self.git("-C", str(self.repo), "config", "user.name", "Test")
        self.git("-C", str(self.repo), "config", "user.email", "test@example.org")
        self.git("-C", str(self.repo), "config", "commit.gpgsign", "false")

    def git(self, *args, input=None):
        return subprocess.run(
            ["git", *args],
            input=input,
            check=True,
            capture_output=True,
        ).stdout.decode().strip()

    def write(self, path, content, binary=False):
        destination = self.repo / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if binary:
            destination.write_bytes(content)
        else:
            destination.write_text(content)

    def commit(self, message):
        self.git("-C", str(self.repo), "add", "-A")
        self.git("-C", str(self.repo), "commit", "-qm", message)
        return self.git("-C", str(self.repo), "rev-parse", "HEAD")

    def revisions(self, base_tip, head, merge_base=None):
        return links.Revisions(
            base_tip=base_tip,
            merge_base=merge_base or base_tip,
            head=head,
        )


class DiffValidationTest(RepositoryFixture):
    def build_text_diff(self):
        original = [f"line {number}" for number in range(1, 81)]
        original[4] = "delete this"
        self.write("src/example.txt", "\n".join(original) + "\n")
        base = self.commit("base")
        changed = original[:]
        del changed[4]
        changed.insert(4, "replacement")
        changed[59] = "changed far away"
        self.write("src/example.txt", "\n".join(changed) + "\n")
        head = self.commit("head")
        return base, head

    def test_added_deleted_multiple_hunks_and_context_rejection(self):
        base, head = self.build_text_diff()
        snapshot = links.load_diff(self.repo, self.revisions(base, head))
        right = links.FindingRequest("right", "src/example.txt", "RIGHT", 5)
        left = links.FindingRequest("left", "src/example.txt", "LEFT", 5)
        far = links.FindingRequest("far", "src/example.txt", "RIGHT", 60)
        self.assertEqual(links.find_reviewed_line(snapshot, right)[1].text, b"replacement")
        self.assertEqual(links.find_reviewed_line(snapshot, left)[1].text, b"delete this")
        self.assertEqual(links.find_reviewed_line(snapshot, far)[1].text, b"changed far away")
        with self.assertRaisesRegex(links.EvidenceError, "not exactly one added/deleted line"):
            links.find_reviewed_line(
                snapshot,
                links.FindingRequest("context", "src/example.txt", "RIGHT", 20),
            )

    def test_renamed_deleted_and_unusual_paths(self):
        self.write("old name.txt", "alpha\nbeta\ngamma\n")
        self.write("delete-me.txt", "gone\n")
        self.write("odd/naïve # file.txt", "before\n")
        base = self.commit("base")
        self.git("-C", str(self.repo), "mv", "old name.txt", "new name.txt")
        self.write("new name.txt", "alpha\nchanged\ngamma\n")
        (self.repo / "delete-me.txt").unlink()
        self.write("odd/naïve # file.txt", "after\n")
        head = self.commit("head")
        snapshot = links.load_diff(self.repo, self.revisions(base, head))

        renamed_right = links.find_reviewed_line(
            snapshot, links.FindingRequest("rename-r", "new name.txt", "RIGHT", 2)
        )
        renamed_left = links.find_reviewed_line(
            snapshot, links.FindingRequest("rename-l", "old name.txt", "LEFT", 2)
        )
        deleted = links.find_reviewed_line(
            snapshot, links.FindingRequest("deleted", "delete-me.txt", "LEFT", 1)
        )
        unusual = links.find_reviewed_line(
            snapshot, links.FindingRequest("odd", "odd/naïve # file.txt", "RIGHT", 1)
        )

        self.assertEqual(renamed_right[0].new_path, "new name.txt")
        self.assertEqual(renamed_left[0].old_path, "old name.txt")
        self.assertIsNone(deleted[0].new_path)
        pinned = links.pinned_source_url(
            "https://github.example/org/repo/pull/7",
            self.revisions(base, head),
            unusual[0],
            unusual[1],
        )
        self.assertIn("odd/na%C3%AFve%20%23%20file.txt#L1", pinned)

    def test_binary_target_is_explicitly_unsupported(self):
        self.write("image.bin", b"\x00\x01base", binary=True)
        base = self.commit("base")
        self.write("image.bin", b"\x00\x02head", binary=True)
        head = self.commit("head")
        snapshot = links.load_diff(self.repo, self.revisions(base, head))
        with self.assertRaisesRegex(links.EvidenceError, "binary patch is unsupported"):
            links.find_reviewed_line(
                snapshot, links.FindingRequest("binary", "image.bin", "RIGHT", 1)
            )

    def test_ambiguous_remapping_is_unavailable(self):
        line = links.ChangedLine("RIGHT", 2, b"same", "signature")
        reviewed_file = links.DiffFile("M", "100644", "100644", "a.txt", "a.txt")
        live_a = links.DiffFile("M", "100644", "100644", "a.txt", "a.txt")
        live_b = links.DiffFile("M", "100644", "100644", "b.txt", "b.txt")
        live_a.changed_lines.append(line)
        live_b.changed_lines.append(
            links.ChangedLine("RIGHT", 9, b"same", "signature")
        )
        snapshot = links.DiffSnapshot(
            links.Revisions("a" * 40, "b" * 40, "c" * 40),
            "d" * 64,
            (live_a, live_b),
            b"",
        )
        self.assertIsNone(links.remap_line(reviewed_file, line, snapshot))


class UrlFormatTest(unittest.TestCase):
    def test_candidate_hash_and_side_format_do_not_claim_ui_verification(self):
        diff_file = links.DiffFile(
            "M", "100644", "100644", "src/a file.py", "src/a file.py"
        )
        right = links.ChangedLine("RIGHT", 42, b"value", "signature")
        left = links.ChangedLine("LEFT", 17, b"value", "signature")
        digest = links.hashlib.sha256(b"src/a file.py").hexdigest()
        base = "https://github.com/org/repo/pull/3"
        self.assertEqual(
            links.comment_url(base, diff_file, right),
            f"{base}/changes#diff-{digest}R42",
        )
        self.assertEqual(
            links.comment_url(base, diff_file, left),
            f"{base}/changes#diff-{digest}L17",
        )


class InputValidationTest(RepositoryFixture):
    def valid_input(self):
        sha = "a" * 40
        return {
            "repository": str(self.repo),
            "pr_url": "https://github.com/org/repo/pull/1",
            "reviewed": {"base_tip": sha, "merge_base": sha, "head": sha},
            "findings": [
                {"id": "one", "path": "src/a.py", "side": "RIGHT", "line": 1}
            ],
        }

    def test_rejects_malformed_partial_and_duplicate_input(self):
        cases = []
        missing = self.valid_input()
        del missing["reviewed"]["head"]
        cases.append(missing)
        partial_finding = self.valid_input()
        del partial_finding["findings"][0]["side"]
        cases.append(partial_finding)
        invalid_side = self.valid_input()
        invalid_side["findings"][0]["side"] = "BOTH"
        cases.append(invalid_side)
        duplicate = self.valid_input()
        duplicate["findings"].append(dict(duplicate["findings"][0]))
        cases.append(duplicate)
        traversal = self.valid_input()
        traversal["findings"][0]["path"] = "../secret"
        cases.append(traversal)
        for case in cases:
            with self.subTest(case=case), self.assertRaises(links.InputError):
                links.parse_request(case)

    def test_whole_input_is_validated_before_live_metadata(self):
        invalid = self.valid_input()
        invalid["findings"][0]["line"] = 0
        with patch.object(links, "fetch_pr_metadata") as fetch:
            with self.assertRaises(links.InputError):
                links.parse_request(invalid)
            fetch.assert_not_called()


class SnapshotAndCachingTest(RepositoryFixture):
    def test_base_tip_movement_reuses_rendered_verification_when_effective_diff_is_unchanged(self):
        self.write("feature.txt", "base\n")
        merge_base = self.commit("base")
        self.git("-C", str(self.repo), "switch", "-qc", "feature")
        self.write("feature.txt", "changed\n")
        head = self.commit("feature")
        reviewed_revisions = self.revisions(merge_base, head)
        reviewed_diff = links.load_diff(self.repo, reviewed_revisions)
        reviewed_file, reviewed_line = links.find_reviewed_line(
            reviewed_diff,
            links.FindingRequest("one", "feature.txt", "RIGHT", 1),
        )
        url = links.comment_url(
            "https://github.com/org/repo/pull/9", reviewed_file, reviewed_line
        )
        fingerprint = links.target_fingerprint(reviewed_file, reviewed_line)

        self.git("-C", str(self.repo), "switch", "-q", "main")
        self.write("base-only.txt", "new base metadata\n")
        moved_base_tip = self.commit("base moved")

        request = links.parse_request({
            "repository": str(self.repo),
            "pr_url": "https://github.com/org/repo/pull/9",
            "reviewed": {
                "base_tip": merge_base,
                "merge_base": merge_base,
                "head": head,
            },
            "findings": [{
                "id": "one",
                "path": "feature.txt",
                "side": "RIGHT",
                "line": 1,
                "rendered_verification": {
                    "url": url,
                    "base_tip": merge_base,
                    "merge_base": merge_base,
                    "head": head,
                    "target_fingerprint": fingerprint,
                },
            }],
        })
        metadata = {
            "url": request.pr_url,
            "state": "OPEN",
            "baseRefOid": moved_base_tip,
            "headRefOid": head,
            "mergedAt": None,
        }
        with patch.object(links, "fetch_pr_metadata", return_value=metadata) as fetch, \
                patch.object(links, "load_diff", wraps=links.load_diff) as load_diff:
            output = links.generate(request)

        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(load_diff.call_count, 1)
        self.assertEqual(output["snapshot"]["base_tip"], moved_base_tip)
        self.assertEqual(output["snapshot"]["merge_base"], merge_base)
        self.assertEqual(output["findings"][0]["status"], "rendered-verified")
        self.assertEqual(
            output["findings"][0]["comment_in_pr"]["target_fingerprint"],
            fingerprint,
        )
        self.assertEqual(
            output["findings"][0]["reviewed"]["base_tip"], merge_base
        )

    def test_valid_target_defaults_to_diff_validated_ui_unverified(self):
        self.write("a.txt", "base\n")
        base = self.commit("base")
        self.write("a.txt", "head\n")
        head = self.commit("head")
        request = links.parse_request({
            "repository": str(self.repo),
            "pr_url": "https://github.com/org/repo/pull/11",
            "reviewed": {
                "base_tip": base,
                "merge_base": base,
                "head": head,
            },
            "findings": [
                {"id": "one", "path": "a.txt", "side": "RIGHT", "line": 1}
            ],
        })
        metadata = {
            "url": request.pr_url,
            "state": "OPEN",
            "baseRefOid": base,
            "headRefOid": head,
            "mergedAt": None,
        }
        with patch.object(links, "fetch_pr_metadata", return_value=metadata):
            output = links.generate(request)
        result = output["findings"][0]
        self.assertEqual(result["status"], "diff-validated-ui-unverified")
        self.assertIn("/changes#diff-", result["comment_in_pr"]["url"])
        self.assertIn("was not inspected", result["reason"])

    def test_moving_revisions_are_bounded_and_report_last_snapshot(self):
        self.write("a.txt", "base\n")
        base = self.commit("base")
        self.write("a.txt", "head\n")
        head = self.commit("head")
        request = links.parse_request({
            "repository": str(self.repo),
            "pr_url": "https://github.com/org/repo/pull/10",
            "reviewed": {
                "base_tip": base,
                "merge_base": base,
                "head": head,
            },
            "findings": [
                {"id": "one", "path": "a.txt", "side": "RIGHT", "line": 1}
            ],
            "max_revision_attempts": 2,
        })
        metadata = [
            {"url": request.pr_url, "state": "OPEN", "baseRefOid": base,
             "headRefOid": head, "mergedAt": None},
            {"url": request.pr_url, "state": "CLOSED", "baseRefOid": base,
             "headRefOid": head, "mergedAt": None},
        ] * 2
        with patch.object(links, "fetch_pr_metadata", side_effect=metadata):
            with self.assertRaisesRegex(links.EvidenceError, "2 bounded attempt"):
                links.generate(request)

    def test_cli_emits_one_complete_batch_result(self):
        self.write("a.txt", "base\n")
        base = self.commit("base")
        self.write("a.txt", "head\n")
        head = self.commit("head")
        request_path = Path(self.temp.name) / "request.json"
        request_path.write_text(json.dumps({
            "repository": str(self.repo),
            "pr_url": "https://github.com/org/repo/pull/12",
            "reviewed": {
                "base_tip": base,
                "merge_base": base,
                "head": head,
            },
            "findings": [
                {"id": "one", "path": "a.txt", "side": "RIGHT", "line": 1}
            ],
        }))
        fake_bin = Path(self.temp.name) / "bin"
        fake_bin.mkdir()
        fake_gh = fake_bin / "gh"
        fake_gh.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$FAKE_GH_METADATA\"\n"
        )
        fake_gh.chmod(0o755)
        metadata = json.dumps({
            "url": "https://github.com/org/repo/pull/12",
            "state": "OPEN",
            "baseRefOid": base,
            "headRefOid": head,
            "mergedAt": None,
        })
        result = subprocess.run(
            [
                str(ROOT / "claude/scripts/pr-comment-links.py"),
                "--input", str(request_path),
            ],
            env={
                **os.environ,
                "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
                "FAKE_GH_METADATA": metadata,
            },
            capture_output=True,
            text=True,
            check=True,
        )
        output = json.loads(result.stdout)
        self.assertEqual(output["findings"][0]["id"], "one")
        self.assertEqual(
            output["findings"][0]["status"],
            "diff-validated-ui-unverified",
        )
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Generate diff-validated GitHub PR comment links without posting anything.

The input is one JSON object:

{
  "repository": "/path/to/checkout",
  "pr_url": "https://github.com/owner/repo/pull/123",
  "reviewed": {
    "base_tip": "<full sha>",
    "merge_base": "<full sha>",
    "head": "<full sha>"
  },
  "findings": [
    {
      "id": "finding-1",
      "path": "src/example.py",
      "side": "RIGHT",
      "line": 42,
      "rendered_verification": {
        "url": "https://github.com/owner/repo/pull/123/changes#diff-...R42",
        "base_tip": "<full sha>",
        "merge_base": "<full sha>",
        "head": "<full sha>",
        "target_fingerprint": "<sha256 of the validated file/hunk target>"
      }
    }
  ],
  "max_revision_attempts": 3
}

The helper validates the complete request before querying GitHub or emitting
JSON. It reads PR metadata with `gh pr view`, reads existing Git objects, and
never fetches, checks out, writes to, or posts to the reviewed repository.
Candidate `diff-<sha256(path)>R|L<line>` fragments are an observed GitHub UI
convention, not a public API. A generated candidate is therefore
`diff-validated-ui-unverified` unless matching rendered-verification evidence
is supplied for an unchanged effective diff.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from urllib.parse import quote, urlsplit


FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
PR_PATH = re.compile(r"^/([^/]+)/([^/]+)/pull/([1-9][0-9]*)/?$")
HUNK_HEADER = re.compile(
    rb"^@@ -(?P<old>[0-9]+)(?:,(?P<old_count>[0-9]+))? "
    rb"\+(?P<new>[0-9]+)(?:,(?P<new_count>[0-9]+))? @@"
)
ALLOWED_TOP_LEVEL = {
    "repository", "pr_url", "reviewed", "findings", "max_revision_attempts",
}
ALLOWED_REVISIONS = {"base_tip", "merge_base", "head"}
ALLOWED_FINDING = {"id", "path", "side", "line", "rendered_verification"}
ALLOWED_RENDERED = {"url", "base_tip", "merge_base", "head", "target_fingerprint"}
STATUSES = {
    "rendered-verified",
    "diff-validated-ui-unverified",
    "unavailable",
}


class InputError(ValueError):
    """The caller supplied malformed or incomplete input."""


class EvidenceError(RuntimeError):
    """Required Git or GitHub evidence could not be established."""


@dataclass(frozen=True)
class Revisions:
    base_tip: str
    merge_base: str
    head: str


@dataclass(frozen=True)
class RenderedVerification:
    url: str
    base_tip: str
    merge_base: str
    head: str
    target_fingerprint: str


@dataclass(frozen=True)
class FindingRequest:
    id: str
    path: str
    side: str
    line: int
    rendered_verification: RenderedVerification | None = None


@dataclass(frozen=True)
class Request:
    repository: Path
    pr_url: str
    reviewed: Revisions
    findings: tuple[FindingRequest, ...]
    max_revision_attempts: int


@dataclass(frozen=True)
class PullRequestSnapshot:
    url: str
    state: str
    base_tip: str
    head: str
    merge_base: str


@dataclass(frozen=True)
class ChangedLine:
    side: str
    line: int
    text: bytes
    hunk_signature: str


@dataclass
class DiffFile:
    status: str
    old_mode: str
    new_mode: str
    old_path: str | None
    new_path: str | None
    patch: bytes = b""
    changed_lines: list[ChangedLine] = field(default_factory=list)
    unsupported_reason: str | None = None

    @property
    def anchor_path(self) -> str:
        path = self.new_path or self.old_path
        if path is None:
            raise EvidenceError("diff file has neither an old nor a new path")
        return path


@dataclass(frozen=True)
class DiffSnapshot:
    revisions: Revisions
    diff_sha256: str
    files: tuple[DiffFile, ...]
    patch: bytes


def reject_unknown(mapping: dict[str, Any], allowed: set[str], field_name: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise InputError(f"{field_name} has unknown key(s): {', '.join(unknown)}")


def require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError(f"{field_name} must be an object")
    return value


def require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise InputError(f"{field_name} must be nonempty text")
    if any(ord(character) < 32 for character in value):
        raise InputError(f"{field_name} must not contain control characters")
    return value


def require_sha(value: Any, field_name: str) -> str:
    text = require_text(value, field_name).lower()
    if not FULL_SHA.fullmatch(text):
        raise InputError(f"{field_name} must be a full 40-character commit SHA")
    return text


def parse_https_url(value: Any, field_name: str) -> str:
    url = require_text(value, field_name)
    try:
        parsed = urlsplit(url)
    except ValueError as error:
        raise InputError(f"{field_name} is not a valid URL") from error
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise InputError(
            f"{field_name} must be an HTTPS URL without credentials, query, or fragment"
        )
    return url.rstrip("/")


def parse_pr_url(value: Any) -> str:
    url = parse_https_url(value, "pr_url")
    if not PR_PATH.fullmatch(urlsplit(url).path):
        raise InputError("pr_url must end with /<owner>/<repo>/pull/<number>")
    return url


def validate_repository_path(value: Any) -> Path:
    repository = Path(require_text(value, "repository")).expanduser()
    if not repository.is_absolute():
        raise InputError("repository must be an absolute path")
    if not repository.is_dir():
        raise InputError("repository must be an existing directory")
    return repository.resolve()


def validate_relative_path(value: Any, field_name: str) -> str:
    path = require_text(value, field_name)
    candidate = Path(path)
    if candidate.is_absolute() or path in {".", ".."} or ".." in candidate.parts:
        raise InputError(f"{field_name} must be a repository-relative path")
    return path


def parse_revisions(value: Any, field_name: str) -> Revisions:
    data = require_mapping(value, field_name)
    reject_unknown(data, ALLOWED_REVISIONS, field_name)
    missing = sorted(ALLOWED_REVISIONS - set(data))
    if missing:
        raise InputError(f"{field_name} is missing: {', '.join(missing)}")
    return Revisions(
        base_tip=require_sha(data["base_tip"], f"{field_name}.base_tip"),
        merge_base=require_sha(data["merge_base"], f"{field_name}.merge_base"),
        head=require_sha(data["head"], f"{field_name}.head"),
    )


def parse_rendered_verification(value: Any, field_name: str) -> RenderedVerification:
    data = require_mapping(value, field_name)
    reject_unknown(data, ALLOWED_RENDERED, field_name)
    missing = sorted(ALLOWED_RENDERED - set(data))
    if missing:
        raise InputError(f"{field_name} is missing: {', '.join(missing)}")
    digest = require_text(
        data["target_fingerprint"], f"{field_name}.target_fingerprint"
    ).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise InputError(
            f"{field_name}.target_fingerprint must be a SHA-256 hex digest"
        )
    url = require_text(data["url"], f"{field_name}.url")
    try:
        parsed = urlsplit(url)
    except ValueError as error:
        raise InputError(f"{field_name}.url is not a valid URL") from error
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query
            or not parsed.fragment.startswith("diff-")):
        raise InputError(f"{field_name}.url must be an HTTPS GitHub diff-line URL")
    return RenderedVerification(
        url=url,
        base_tip=require_sha(data["base_tip"], f"{field_name}.base_tip"),
        merge_base=require_sha(data["merge_base"], f"{field_name}.merge_base"),
        head=require_sha(data["head"], f"{field_name}.head"),
        target_fingerprint=digest,
    )


def parse_finding(value: Any, index: int) -> FindingRequest:
    field_name = f"findings[{index}]"
    data = require_mapping(value, field_name)
    reject_unknown(data, ALLOWED_FINDING, field_name)
    required = {"id", "path", "side", "line"}
    missing = sorted(required - set(data))
    if missing:
        raise InputError(f"{field_name} is missing: {', '.join(missing)}")
    finding_id = require_text(data["id"], f"{field_name}.id")
    side = require_text(data["side"], f"{field_name}.side").upper()
    if side not in {"LEFT", "RIGHT"}:
        raise InputError(f"{field_name}.side must be LEFT or RIGHT")
    line = data["line"]
    if isinstance(line, bool) or not isinstance(line, int) or line < 1:
        raise InputError(f"{field_name}.line must be a positive integer")
    rendered = None
    if "rendered_verification" in data:
        rendered = parse_rendered_verification(
            data["rendered_verification"], f"{field_name}.rendered_verification"
        )
    return FindingRequest(
        id=finding_id,
        path=validate_relative_path(data["path"], f"{field_name}.path"),
        side=side,
        line=line,
        rendered_verification=rendered,
    )


def parse_request(data: Any) -> Request:
    mapping = require_mapping(data, "input")
    reject_unknown(mapping, ALLOWED_TOP_LEVEL, "input")
    required = {"repository", "pr_url", "reviewed", "findings"}
    missing = sorted(required - set(mapping))
    if missing:
        raise InputError(f"input is missing: {', '.join(missing)}")
    findings_value = mapping["findings"]
    if not isinstance(findings_value, list) or not findings_value:
        raise InputError("findings must be a nonempty list")
    findings = tuple(parse_finding(value, index) for index, value in enumerate(findings_value))
    ids = [finding.id for finding in findings]
    if len(ids) != len(set(ids)):
        raise InputError("finding ids must be unique")
    attempts = mapping.get("max_revision_attempts", 3)
    if isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 5:
        raise InputError("max_revision_attempts must be an integer from 1 to 5")
    return Request(
        repository=validate_repository_path(mapping["repository"]),
        pr_url=parse_pr_url(mapping["pr_url"]),
        reviewed=parse_revisions(mapping["reviewed"], "reviewed"),
        findings=findings,
        max_revision_attempts=attempts,
    )


def run(command: list[str], cwd: Path | None = None) -> bytes:
    result = subprocess.run(command, cwd=cwd, capture_output=True)
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise EvidenceError(f"{' '.join(command[:3])} failed: {message or 'unknown error'}")
    return result.stdout


def git(repository: Path, *arguments: str) -> bytes:
    return run(["git", "-C", str(repository), *arguments])


def verify_commit(repository: Path, sha: str, field_name: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(repository), "cat-file", "-e", f"{sha}^{{commit}}"],
        capture_output=True,
    )
    if result.returncode != 0:
        raise EvidenceError(
            f"{field_name} commit {sha} is not available locally; "
            "the helper does not fetch or mutate the checkout"
        )


def computed_merge_base(repository: Path, base_tip: str, head: str) -> str:
    output = git(repository, "merge-base", base_tip, head).decode().strip()
    if not FULL_SHA.fullmatch(output):
        raise EvidenceError("git merge-base did not return one full commit SHA")
    return output.lower()


def verify_revisions(repository: Path, revisions: Revisions, field_name: str) -> None:
    verify_commit(repository, revisions.base_tip, f"{field_name}.base_tip")
    verify_commit(repository, revisions.merge_base, f"{field_name}.merge_base")
    verify_commit(repository, revisions.head, f"{field_name}.head")
    actual = computed_merge_base(repository, revisions.base_tip, revisions.head)
    if actual != revisions.merge_base:
        raise EvidenceError(
            f"{field_name}.merge_base is {revisions.merge_base}, but Git computes {actual}"
        )


def parse_raw_diff(raw: bytes) -> list[DiffFile]:
    fields = raw.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    files = []
    index = 0
    while index < len(fields):
        header = fields[index]
        index += 1
        if not header.startswith(b":"):
            raise EvidenceError("unsupported raw diff record")
        try:
            modes_and_shas, status_bytes = header[1:].rsplit(b" ", 1)
            old_mode, new_mode, _old_sha, _new_sha = modes_and_shas.split(b" ")
            status = status_bytes.decode("ascii")
        except (ValueError, UnicodeDecodeError) as error:
            raise EvidenceError("malformed raw diff metadata") from error
        if index >= len(fields):
            raise EvidenceError("raw diff record is missing its path")
        old_path_bytes = fields[index]
        index += 1
        if status.startswith(("R", "C")):
            if index >= len(fields):
                raise EvidenceError("rename/copy record is missing its destination path")
            new_path_bytes = fields[index]
            index += 1
        else:
            new_path_bytes = old_path_bytes
        old_path = old_path_bytes.decode("utf-8", "surrogateescape")
        new_path = new_path_bytes.decode("utf-8", "surrogateescape")
        if status.startswith("A"):
            old_path = None
        if status.startswith("D"):
            new_path = None
        files.append(DiffFile(
            status=status,
            old_mode=old_mode.decode("ascii"),
            new_mode=new_mode.decode("ascii"),
            old_path=old_path,
            new_path=new_path,
        ))
    return files


def split_patch(patch: bytes) -> list[bytes]:
    starts = [match.start() for match in re.finditer(rb"(?m)^diff --git ", patch)]
    if not starts:
        return [] if not patch else [patch]
    starts.append(len(patch))
    return [patch[starts[index]:starts[index + 1]] for index in range(len(starts) - 1)]


def parse_hunks(diff_file: DiffFile) -> None:
    if (b"GIT binary patch" in diff_file.patch
            or b"Binary files " in diff_file.patch):
        diff_file.unsupported_reason = "binary patch"
        return
    if diff_file.old_mode == "160000" or diff_file.new_mode == "160000":
        diff_file.unsupported_reason = "submodule patch"
        return
    lines = diff_file.patch.splitlines()
    index = 0
    while index < len(lines):
        match = HUNK_HEADER.match(lines[index])
        if not match:
            index += 1
            continue
        old_line = int(match.group("old"))
        new_line = int(match.group("new"))
        body = []
        index += 1
        while index < len(lines) and not lines[index].startswith(b"@@ "):
            line = lines[index]
            if line.startswith(b"diff --git "):
                break
            if line == rb"\ No newline at end of file":
                index += 1
                continue
            if not line or line[:1] not in {b" ", b"+", b"-"}:
                index += 1
                continue
            body.append(line)
            index += 1
        normalized_hunk = b"\n".join(body)
        for body_index, line in enumerate(body):
            prefix = line[:1]
            signature = hashlib.sha256(
                normalized_hunk + b"\0target-index=" + str(body_index).encode("ascii")
            ).hexdigest()
            if prefix == b" ":
                old_line += 1
                new_line += 1
            elif prefix == b"-":
                diff_file.changed_lines.append(
                    ChangedLine("LEFT", old_line, line[1:], signature)
                )
                old_line += 1
            elif prefix == b"+":
                diff_file.changed_lines.append(
                    ChangedLine("RIGHT", new_line, line[1:], signature)
                )
                new_line += 1


def load_diff(repository: Path, revisions: Revisions) -> DiffSnapshot:
    raw = git(
        repository, "diff", "--raw", "-z", "--no-abbrev", "--find-renames",
        revisions.merge_base, revisions.head, "--",
    )
    patch = git(
        repository, "diff", "--patch", "--full-index", "--binary",
        "--find-renames", "--no-ext-diff", "--no-textconv",
        revisions.merge_base, revisions.head, "--",
    )
    files = parse_raw_diff(raw)
    sections = split_patch(patch)
    if len(files) != len(sections):
        raise EvidenceError(
            "complete diff metadata and patch sections disagree; refusing partial parsing"
        )
    for diff_file, section in zip(files, sections):
        diff_file.patch = section
        parse_hunks(diff_file)
    return DiffSnapshot(
        revisions=revisions,
        diff_sha256=hashlib.sha256(patch).hexdigest(),
        files=tuple(files),
        patch=patch,
    )


def fetch_pr_metadata(pr_url: str) -> dict[str, Any]:
    fields = "url,state,baseRefOid,headRefOid,mergedAt"
    output = run(["gh", "pr", "view", pr_url, "--json", fields])
    try:
        data = json.loads(output)
    except json.JSONDecodeError as error:
        raise EvidenceError("gh pr view returned invalid JSON") from error
    if not isinstance(data, dict):
        raise EvidenceError("gh pr view returned a non-object")
    return data


def snapshot_pr(repository: Path, pr_url: str) -> PullRequestSnapshot:
    data = fetch_pr_metadata(pr_url)
    live_url = parse_pr_url(data.get("url"))
    if live_url != pr_url:
        raise EvidenceError(f"GitHub resolved a different PR URL: {live_url}")
    base_tip = require_sha(data.get("baseRefOid"), "live.base_tip")
    head = require_sha(data.get("headRefOid"), "live.head")
    verify_commit(repository, base_tip, "live.base_tip")
    verify_commit(repository, head, "live.head")
    merge_base = computed_merge_base(repository, base_tip, head)
    state = require_text(data.get("state"), "live.state").lower()
    if data.get("mergedAt"):
        state = "merged"
    elif state not in {"open", "closed", "merged"}:
        raise EvidenceError(f"unsupported PR state from GitHub: {state}")
    return PullRequestSnapshot(live_url, state, base_tip, head, merge_base)


def find_reviewed_line(snapshot: DiffSnapshot, finding: FindingRequest) -> tuple[DiffFile, ChangedLine]:
    matches = []
    for diff_file in snapshot.files:
        expected_path = diff_file.new_path if finding.side == "RIGHT" else diff_file.old_path
        if expected_path != finding.path:
            continue
        if diff_file.unsupported_reason:
            raise EvidenceError(
                f"{finding.id}: {diff_file.unsupported_reason} is unsupported for "
                f"{finding.path}"
            )
        for line in diff_file.changed_lines:
            if line.side == finding.side and line.line == finding.line:
                matches.append((diff_file, line))
    if len(matches) != 1:
        raise EvidenceError(
            f"{finding.id}: {finding.path}:{finding.line} ({finding.side}) is not exactly "
            "one added/deleted line in the reviewed merge-base-to-head diff"
        )
    return matches[0]


def remap_line(
    reviewed_file: DiffFile,
    reviewed_line: ChangedLine,
    live: DiffSnapshot,
) -> tuple[DiffFile, ChangedLine] | None:
    matches = []
    for diff_file in live.files:
        for line in diff_file.changed_lines:
            if (line.side == reviewed_line.side
                    and line.hunk_signature == reviewed_line.hunk_signature
                    and line.text == reviewed_line.text):
                matches.append((diff_file, line))
    if len(matches) == 1:
        return matches[0]
    return None


def comment_url(pr_url: str, diff_file: DiffFile, line: ChangedLine) -> str:
    path_digest = hashlib.sha256(diff_file.anchor_path.encode("utf-8")).hexdigest()
    side_prefix = "R" if line.side == "RIGHT" else "L"
    return f"{pr_url}/changes#diff-{path_digest}{side_prefix}{line.line}"


def target_fingerprint(diff_file: DiffFile, line: ChangedLine) -> str:
    payload = b"\0".join([
        diff_file.anchor_path.encode("utf-8", "surrogateescape"),
        line.side.encode("ascii"),
        str(line.line).encode("ascii"),
        line.hunk_signature.encode("ascii"),
        line.text,
    ])
    return hashlib.sha256(payload).hexdigest()


def pinned_source_url(
    pr_url: str,
    reviewed: Revisions,
    diff_file: DiffFile,
    line: ChangedLine,
) -> str:
    parsed = urlsplit(pr_url)
    match = PR_PATH.fullmatch(parsed.path)
    if not match:
        raise EvidenceError("cannot extract repository identity from PR URL")
    owner, repository, _number = match.groups()
    if line.side == "RIGHT":
        sha = reviewed.head
        path = diff_file.new_path
    else:
        sha = reviewed.merge_base
        path = diff_file.old_path
    if path is None:
        raise EvidenceError("pinned source path is unavailable for the selected side")
    encoded_path = quote(path, safe="/")
    return (
        f"{parsed.scheme}://{parsed.netloc}/{quote(owner)}/{quote(repository)}"
        f"/blob/{sha}/{encoded_path}#L{line.line}"
    )


def rendered_evidence_matches(
    evidence: RenderedVerification | None,
    candidate_url: str,
    live_file: DiffFile,
    live_line: ChangedLine,
) -> bool:
    if evidence is None:
        return False
    return (
        evidence.url == candidate_url
        and evidence.target_fingerprint == target_fingerprint(live_file, live_line)
    )


def finding_result(
    request: Request,
    finding: FindingRequest,
    reviewed: DiffSnapshot,
    live: DiffSnapshot,
    pr_state: str,
) -> dict[str, Any]:
    reviewed_file, reviewed_line = find_reviewed_line(reviewed, finding)
    if reviewed.diff_sha256 == live.diff_sha256:
        live_target = find_reviewed_line(live, finding)
    else:
        live_target = remap_line(reviewed_file, reviewed_line, live)
    pinned_url = pinned_source_url(
        request.pr_url, request.reviewed, reviewed_file, reviewed_line
    )
    base_result = {
        "id": finding.id,
        "pr_state": pr_state,
        "reviewed": {
            "base_tip": request.reviewed.base_tip,
            "merge_base": request.reviewed.merge_base,
            "head": request.reviewed.head,
            "path": finding.path,
            "side": finding.side,
            "line": finding.line,
            "diff_sha256": reviewed.diff_sha256,
        },
        "pinned_source": {
            "url": pinned_url,
            "path": finding.path,
            "side": finding.side,
            "line": finding.line,
            "sha": (
                request.reviewed.head
                if finding.side == "RIGHT"
                else request.reviewed.merge_base
            ),
        },
    }
    if live_target is None:
        return {
            **base_result,
            "status": "unavailable",
            "reason": (
                "the reviewed change does not have one unambiguous matching hunk target "
                "in the live effective diff"
            ),
            "comment_in_pr": None,
            "live": {
                "base_tip": live.revisions.base_tip,
                "merge_base": live.revisions.merge_base,
                "head": live.revisions.head,
                "diff_sha256": live.diff_sha256,
            },
        }
    live_file, live_line = live_target
    candidate_url = comment_url(request.pr_url, live_file, live_line)
    rendered = rendered_evidence_matches(
        finding.rendered_verification, candidate_url, live_file, live_line
    )
    status = "rendered-verified" if rendered else "diff-validated-ui-unverified"
    reason = (
        "matching rendered GitHub target evidence was preserved because the "
        "validated target fingerprint and candidate URL are unchanged"
        if rendered
        else "Git correspondence is verified; the generated GitHub URL fragment was not inspected"
    )
    result = {
        **base_result,
        "status": status,
        "reason": reason,
        "comment_in_pr": {
            "url": candidate_url,
            "path": live_file.anchor_path,
            "side": live_line.side,
            "line": live_line.line,
            "anchor_path": live_file.anchor_path,
            "target_fingerprint": target_fingerprint(live_file, live_line),
        },
        "live": {
            "base_tip": live.revisions.base_tip,
            "merge_base": live.revisions.merge_base,
            "head": live.revisions.head,
            "diff_sha256": live.diff_sha256,
        },
    }
    if rendered and finding.rendered_verification is not None:
        result["rendered_at"] = {
            "base_tip": finding.rendered_verification.base_tip,
            "merge_base": finding.rendered_verification.merge_base,
            "head": finding.rendered_verification.head,
        }
    return result


def generate(request: Request) -> dict[str, Any]:
    verify_revisions(request.repository, request.reviewed, "reviewed")
    reviewed = load_diff(request.repository, request.reviewed)
    diff_cache = {
        (request.reviewed.merge_base, request.reviewed.head): reviewed,
    }
    last_snapshot = None
    for attempt in range(1, request.max_revision_attempts + 1):
        before = snapshot_pr(request.repository, request.pr_url)
        live_revisions = Revisions(before.base_tip, before.merge_base, before.head)
        cache_key = (before.merge_base, before.head)
        cached = diff_cache.get(cache_key)
        if cached is None:
            cached = load_diff(request.repository, live_revisions)
            diff_cache[cache_key] = cached
        live = DiffSnapshot(
            revisions=live_revisions,
            diff_sha256=cached.diff_sha256,
            files=cached.files,
            patch=cached.patch,
        )
        after = snapshot_pr(request.repository, request.pr_url)
        last_snapshot = after
        if before == after:
            results = [
                finding_result(request, finding, reviewed, live, before.state)
                for finding in request.findings
            ]
            if any(result["status"] not in STATUSES for result in results):
                raise AssertionError("internal status invariant failed")
            return {
                "schema_version": 1,
                "pr": {
                    "url": request.pr_url,
                    "state": before.state,
                },
                "snapshot": {
                    "attempt": attempt,
                    "base_tip": before.base_tip,
                    "merge_base": before.merge_base,
                    "head": before.head,
                    "diff_sha256": live.diff_sha256,
                },
                "findings": results,
                "limitations": [
                    "GitHub diff fragments are a UI convention, not a guaranteed public API.",
                    "An HTTP 200 response does not validate a URL fragment.",
                    "Only rendered-verified means the actual GitHub diff anchor and target were inspected.",
                ],
            }
    assert last_snapshot is not None
    raise EvidenceError(
        "PR revisions kept moving across "
        f"{request.max_revision_attempts} bounded attempt(s); last snapshot was "
        f"base_tip={last_snapshot.base_tip} merge_base={last_snapshot.merge_base} "
        f"head={last_snapshot.head}"
    )


def load_json(path: str) -> Any:
    try:
        if path == "-":
            return json.load(sys.stdin)
        with Path(path).open(encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise InputError(f"cannot read input JSON: {error}") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", required=True,
        help="JSON request path, or - for stdin",
    )
    arguments = parser.parse_args()
    try:
        request = parse_request(load_json(arguments.input))
        output = generate(request)
    except (InputError, EvidenceError) as error:
        print(f"pr-comment-links: {error}", file=sys.stderr)
        return 2
    json.dump(output, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

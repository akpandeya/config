#!/usr/bin/env python3
"""Ship a decomposed epic task by task, unattended, with no model in the outer loop.

Usage: epic-ship.py <prompt-dir> [--dry-run] [--only <task-id>] [--retry-failed]

<prompt-dir> is an issue-decompose output folder: manifest.json, task-*.md, plus a
run-config.json you write once (see RUN_CONFIG_EXAMPLE below). For each task, in
manifest order, the script:

  1. skips it when a blockedBy task is not done, or run-config lists it in "skip";
  2. returns the repo to a clean, current main (a crashed task's leftovers are
     committed to that task's own branch, never stashed or discarded; a dirty main
     aborts the run because it may be the user's work);
  3. files the task as a sub-issue of the epic (once; reused on resume);
  4. runs one headless `claude -p` session that executes /issue-ship with every
     answer preset, and asks it to write results/<task-id>.json;
  5. validates that result, confirms a claimed merge with `gh pr view`, and records
     the outcome in manifest.json (status) and epic-ship-ledger.md.

Judgement (review, fixes, escalation) happens only inside the per-task session.
Re-running resumes: done, failed and skipped tasks are left alone (--retry-failed
re-runs failed ones).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

STATUSES = {"MERGED", "MERGED_WITH_KNOWN_ISSUES", "FAILED"}
STAGES = ("implement", "review", "fix", "escalate", "fallback")
# A session that ends this fast with no result never started work (bad CLI args, auth).
SETUP_FAILURE_SECONDS = 120

RUN_CONFIG_EXAMPLE = {
    "session": "claude:sonnet",
    "timeoutMinutes": 240,
    "defaults": {
        "implement": "opencode:melious/glm-5.3-flash",
        "review": "claude:sonnet",
        "fix": "claude:sonnet",
        "escalate": "claude:opus",
        "fallback": "claude:sonnet",
    },
    "tasks": {"task-01a": {"review": "claude:opus"}},
    "briefs": {"task-01a": "Extra instructions for this task's reviewer or implementer."},
    "skip": {"task-05": "mock not approved"},
}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class StageModels:
    implement: str
    review: str
    fix: str
    escalate: str
    fallback: str


@dataclass(frozen=True)
class TaskResult:
    status: str
    pr_url: str | None
    follow_up: str | None
    branch: str | None
    notes: str


# --------------------------------------------------------------------------- pure logic


def _check_harness_model(value: object, where: str) -> str:
    if not isinstance(value, str) or ":" not in value or value.startswith(":") or value.endswith(":"):
        raise ConfigError(f"{where}: want '<harness>:<model>', got {value!r}")
    return value


def load_run_config(raw: dict, task_ids: list[str]) -> dict:
    """Validate run-config before anything runs; reject unknown tasks and partial stage sets."""
    if not isinstance(raw, dict):
        raise ConfigError("run-config must be a JSON object")
    session = _check_harness_model(raw.get("session"), "session")
    if not session.startswith("claude:"):
        raise ConfigError("session must be a claude model: /issue-ship is a Claude Code skill")
    defaults = raw.get("defaults")
    if not isinstance(defaults, dict) or set(defaults) != set(STAGES):
        raise ConfigError(f"defaults must set exactly {list(STAGES)}")
    for stage in STAGES:
        _check_harness_model(defaults[stage], f"defaults.{stage}")
    known = set(task_ids)
    for section in ("tasks", "briefs", "skip"):
        value = raw.get(section, {})
        if not isinstance(value, dict):
            raise ConfigError(f"{section} must be an object keyed by task id")
        unknown = set(value) - known
        if unknown:
            raise ConfigError(f"{section} names unknown tasks: {sorted(unknown)}")
    for tid, overrides in raw.get("tasks", {}).items():
        if not isinstance(overrides, dict) or not set(overrides) <= set(STAGES):
            raise ConfigError(f"tasks.{tid} may only set {list(STAGES)}")
        for stage, value in overrides.items():
            _check_harness_model(value, f"tasks.{tid}.{stage}")
    timeout = raw.get("timeoutMinutes", 240)
    if not isinstance(timeout, int) or timeout <= 0:
        raise ConfigError("timeoutMinutes must be a positive integer")
    return raw


def stage_models(config: dict, task_id: str) -> StageModels:
    merged = {**config["defaults"], **config.get("tasks", {}).get(task_id, {})}
    return StageModels(**{stage: merged[stage] for stage in STAGES})


def skip_reason(task: dict, statuses: dict[str, str], config: dict) -> str | None:
    """Why this task must not run now, or None when it may run."""
    configured = config.get("skip", {}).get(task["id"])
    if configured:
        return f"config: {configured}"
    for dep in task.get("blockedBy", []):
        if statuses.get(dep) != "done":
            return f"blocked by {dep} ({statuses.get(dep, 'unknown')})"
    return None


def parse_result(path: Path) -> TaskResult:
    """Read the per-task result file; reject anything incomplete instead of guessing."""
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("result is not a JSON object")
    missing = {"status", "pr", "followUp", "branch", "notes"} - set(data)
    if missing:
        raise ValueError(f"result is missing {sorted(missing)}")
    if data["status"] not in STATUSES:
        raise ValueError(f"unknown status {data['status']!r}")
    if data["status"] != "FAILED" and not data["pr"]:
        raise ValueError(f"{data['status']} without a PR url")
    return TaskResult(data["status"], data["pr"] or None, data["followUp"] or None,
                      data["branch"] or None, str(data["notes"]))


def build_session_prompt(*, repo: str, sub_issue: int, models: StageModels, brief: str | None,
                         result_path: Path) -> str:
    extra = f"\nTask-specific instructions:\n{brief}\n" if brief else ""
    return f"""Run the issue-ship skill: `/issue-ship {repo} {sub_issue}`.

This is a headless, unattended session. Nobody can answer questions. The upfront batch is
already answered; never call AskUserQuestion:
IMPLEMENT={models.implement}, REVIEW={models.review}, FIX={models.fix}, SHIP_AFTER_CLEAN=yes.
Verify comes from the repo's CLAUDE.md (with AI_BENCH_KEY and MELIOUS_API_KEY unset).

Overrides to the skill, authorized by the user for this run:
(a) Run every command in the foreground. Do not use run_in_background: this session ends when
    your turn ends, so a background job would be abandoned.
(b) On harness failure, retry that stage once with {models.fallback}; if it fails again, stop.
(c) Escalation ladder when 2 normal fix rounds leave findings or verify is red: up to 2 rounds
    with {models.escalate} as fixer and re-reviewer (fix only; no scope beyond the acceptance
    criteria; re-run verify each round). CLEAN → ship. Findings left but verify green → commit,
    push, open the PR and merge; list them under "Known issues" in the PR body and file one
    follow-up issue "Follow-up: <task title>". Verify still red → push the branch, do not merge.
(d) Never post PR review comments. No Claude-Session trailer.
(e) Where the skill or task would stop to ask, take the conservative option that keeps the
    build green and stays inside the design doc, and note it.
{extra}
Before you finish, write this JSON file (and nothing else there): {result_path}
{{"status": "MERGED" | "MERGED_WITH_KNOWN_ISSUES" | "FAILED", "pr": "<url or empty>",
  "followUp": "<url or empty>", "branch": "<branch>", "notes": "<at most 5 lines: rounds,
  escalation, decisions under (e), failure reason>"}}
"""


# --------------------------------------------------------------------------- side effects


def sh(args: list[str], cwd: Path | None = None, check: bool = True) -> str:
    out = subprocess.run(args, cwd=cwd, check=check, capture_output=True, text=True)
    return out.stdout.strip()


def log(msg: str) -> None:
    print(f"[epic-ship {dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def clean_main(repo_path: Path, task_id: str) -> None:
    """Return to a current main. Leftovers on a task branch are committed there, never lost."""
    branch = sh(["git", "branch", "--show-current"], repo_path)
    if sh(["git", "status", "--porcelain"], repo_path):
        if branch in ("main", "master", ""):
            raise RuntimeError(f"uncommitted changes on {branch or 'detached HEAD'}; "
                               "not touching possible user work")
        sh(["git", "add", "-A"], repo_path)
        sh(["git", "commit", "--no-verify", "-m", f"wip: leftovers from an interrupted run (before {task_id})"],
           repo_path)
        log(f"committed leftovers on {branch}")
    sh(["git", "checkout", "main"], repo_path)
    sh(["git", "pull", "--ff-only"], repo_path)


def file_sub_issue(repo: str, epic: int, task: dict, task_file: Path) -> int:
    body = f"Part of #{epic}.\n\n" + task_file.read_text()
    url = sh(["gh", "issue", "create", "--repo", repo, "--title", f"{task['title']} (Ref #{epic})",
              "--body", body])
    return int(url.rstrip("/").rsplit("/", 1)[-1])


def pr_is_merged(pr_url: str) -> bool:
    return sh(["gh", "pr", "view", pr_url, "--json", "state", "--jq", ".state"], check=False) == "MERGED"


def save_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompt_dir", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="print the plan; file nothing, run nothing")
    ap.add_argument("--only", help="run just this task id")
    ap.add_argument("--retry-failed", action="store_true")
    args = ap.parse_args(argv)

    pdir = args.prompt_dir.expanduser().resolve()
    manifest_path = pdir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    tasks = manifest["tasks"]
    if not manifest.get("repoPath"):
        print("manifest.repoPath is null; set it first", file=sys.stderr)
        return 2
    repo, epic, repo_path = manifest["repo"], int(manifest["issue"]), Path(manifest["repoPath"])
    try:
        config = load_run_config(json.loads((pdir / "run-config.json").read_text()), [t["id"] for t in tasks])
    except (FileNotFoundError, ConfigError) as exc:
        print(f"run-config.json: {exc}\nexample:\n{json.dumps(RUN_CONFIG_EXAMPLE, indent=2)}", file=sys.stderr)
        return 2

    state_path = pdir / "epic-ship-state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"subIssues": {}}
    ledger = pdir / "epic-ship-ledger.md"
    (pdir / "results").mkdir(exist_ok=True)
    (pdir / "logs").mkdir(exist_ok=True)
    session_model = config["session"].split(":", 1)[1]

    def record(task: dict, status: str, line: str) -> None:
        task["status"] = status
        save_json(manifest_path, manifest)
        with ledger.open("a") as fh:
            fh.write(f"- {dt.datetime.now():%Y-%m-%d %H:%M} | {task['id']} | {status} | {line}\n")
        log(f"{task['id']}: {status} — {line}")

    for task in tasks:
        tid = task["id"]
        if args.only and tid != args.only:
            continue
        if task.get("status") in ("done", "skipped") or (task.get("status") == "failed" and not args.retry_failed):
            continue
        statuses = {t["id"]: t.get("status", "pending") for t in tasks}
        reason = skip_reason(task, statuses, config)
        models = stage_models(config, tid)
        if args.dry_run:
            print(f"{tid}: {'SKIP ' + reason if reason else 'RUN'} | {models}")
            if not reason:
                statuses[tid] = "done"  # assume success for the rest of the plan
                task["status"] = "done"
            continue
        if reason:
            record(task, "skipped", reason)
            continue
        try:
            clean_main(repo_path, tid)
        except (RuntimeError, subprocess.CalledProcessError) as exc:
            log(f"stopping: {exc}")
            return 1
        sub_issue = state["subIssues"].get(tid)
        if sub_issue is None:
            sub_issue = file_sub_issue(repo, epic, task, pdir / f"{tid}.md")
            state["subIssues"][tid] = sub_issue
            save_json(state_path, state)
        result_path = pdir / "results" / f"{tid}.json"
        result_path.unlink(missing_ok=True)
        prompt = build_session_prompt(repo=repo, sub_issue=sub_issue, models=models,
                                      brief=config.get("briefs", {}).get(tid), result_path=result_path)
        log(f"{tid}: running /issue-ship #{sub_issue} ({models.implement} → {models.review})")
        log_file = pdir / "logs" / f"{tid}.session.log"
        started = dt.datetime.now()
        try:
            with log_file.open("w") as fh:
                # The prompt goes on stdin: --add-dir is variadic and would swallow a trailing
                # positional prompt as another directory.
                subprocess.run(["claude", "-p", "--model", session_model, "--permission-mode",
                                "bypassPermissions", "--add-dir", str(pdir)],
                               input=prompt, cwd=repo_path, stdout=fh, stderr=subprocess.STDOUT,
                               text=True, timeout=config.get("timeoutMinutes", 240) * 60)
        except subprocess.TimeoutExpired:
            record(task, "failed", f"#{sub_issue} session timed out; log {log_file}")
            continue
        try:
            result = parse_result(result_path)
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            if (dt.datetime.now() - started).total_seconds() < SETUP_FAILURE_SECONDS:
                # Too fast to have done any work: the launch itself is broken. Stop instead of
                # failing every later task the same way; the task stays pending for a rerun.
                log(f"stopping: {tid} session ended in under {SETUP_FAILURE_SECONDS}s without a "
                    f"result ({exc}); see {log_file}")
                return 1
            record(task, "failed", f"#{sub_issue} no valid result ({exc}); log {log_file}")
            continue
        if result.status != "FAILED" and not pr_is_merged(result.pr_url):
            record(task, "failed", f"#{sub_issue} claims {result.status} but {result.pr_url} is not merged")
            continue
        status = "failed" if result.status == "FAILED" else "done"
        record(task, status, f"#{sub_issue} {result.status} pr={result.pr_url} "
                             f"follow-up={result.follow_up} | {result.notes.replace(chr(10), ' / ')}")

    if not args.dry_run:
        try:
            clean_main(repo_path, "end")
        except (RuntimeError, subprocess.CalledProcessError) as exc:
            log(f"left repo as is: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

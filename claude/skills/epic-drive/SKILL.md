---
name: epic-drive
description: >-
  Drive a decomposed GitHub issue or epic to completion with one PR per task, verify
  and CI gates, and one epic review after its last merge. The implementer harness and
  model are chosen by the caller.
  Usage: /epic-drive <owner/repo> <issue-number> IMPLEMENTER=<harness>:<model> [COOLDOWN=<seconds>] [REVIEWER=<harness>:<model>] [--retry-failed]
allowed-tools: Bash, Read, Write, Agent
argument-hint: "<owner/repo> <issue-number> IMPLEMENTER=<harness>:<model> [COOLDOWN=<seconds>|manifest] [REVIEWER=<harness>:<model>] [--retry-failed]"
---

Orchestrate autonomous implementation of a decomposed GitHub issue or epic. Each task
from the manifest is implemented by one implementer run, gets its own PR, and must pass
verification and CI before it merges. There is no per-PR review. The epic gets one review
after its last merge, handled by `epic-review`.

Publishing is part of this explicitly invoked workflow. Work-repo merges still belong to
a human. A plan-only invocation stops before execution. Use the shared communication style
for reports, without an HTML page per status.

Nothing here is repo-specific. Build commands, scope fences, lockfile policy and pacing come
from the manifest, with defaults that reproduce the original behaviour for manifests that do
not set them.

## Inputs

`$ARGUMENTS`: `<owner/repo> <issue-number> IMPLEMENTER=<harness>:<model> [COOLDOWN=<seconds>|manifest] [REVIEWER=<harness>:<model>] [--retry-failed]`

- `IMPLEMENTER` is one of `claude:<alias or id>`, `opencode:<provider/model>` or
  `agy:<model id>`. When called from `epic-run`, it is already resolved; do not ask again.
- `REVIEWER` is passed through to `epic-review` in the Final review step.
- `COOLDOWN` is the minimum interval between task starts, in seconds. `epic-run` asks for it up front and
  passes `COOLDOWN=<seconds>`, or `COOLDOWN=manifest` to use `manifest.cooldownSeconds`. There is no silent
  default: if it is absent when this skill is run on its own, ask once (0, 540 or 900 seconds, or use the
  manifest value when `cooldownSeconds` is set). `cooldownSeconds` in the manifest is used only when the
  caller chose "use manifest value".
- `SLUG` = owner + "-" + repo-name + "-issue-" + issue-number.
- `PROMPT_DIR` = `${AGENT_PROMPTS_DIR:-$HOME/.local/share/agent-prompts}/$SLUG`.
  Harness-neutral XDG data home, same convention as nvim's py-scratch/sql-scratch. The same
  directory is used by every harness, so a manifest written by one harness can be driven by another.
- `RETRY_FAILED` applies only when `--retry-failed` is present.

If `--reviewer` is passed, stop and say that review is no longer part of this skill. Use
`epic-review` after the last merge.

## Harness mapping

The procedure is written once. Each harness has a different name for the same operation:

| operation | Claude Code | OpenCode | agy |
|---|---|---|---|
| same-harness subagent | `Agent` tool with `model:` | subagent via `@agent` / task | `invoke_subagent` |
| headless implementer on another harness | `run-harness.sh claude ...` | `run-harness.sh opencode ...` | `run-harness.sh agy ...` |

Use the same-harness subagent when `IMPLEMENTER` names the harness you are running in. Use
`run-harness.sh` for any other harness. The helper script lives at
`~/.config/agent-context/scripts/run-harness.sh`. Do not assume the repo path exists.

## Check for manifest

If `$PROMPT_DIR/manifest.json` does not exist, tell the user:
"No decomposition found. Run `/issue-decompose $REPO $ISSUE_NUM` first."
Then stop.

## Run-all

When called with no epic, list `${AGENT_PROMPTS_DIR:-$HOME/.local/share/agent-prompts}/*/manifest.json`,
read each manifest's `repo` and `issue` (not the folder name), sort by `issue`, and skip
epics whose tasks are all `merged` or `skipped`. Resolve every epic's config before the first
task. Run one epic at a time, each fully finished before the next starts. A halt stops the
whole run. The cool-down spans epics: `PREV_FINISHED_AT` is the latest `finishedAt` across all
manifests in the run.

## Resolve config

| value | source | default |
|---|---|---|
| `REPO_PATH` | `manifest.repoPath` | required |
| `EPIC` | `manifest.epic` | `manifest.issue` when the manifest has no per-task issues, else `null` |
| `VERIFY` | `manifest.verifyCommands` → repo `CLAUDE.md` "Full verification" / "Build & Test" → `["npm run build", "npm test"]` only if `package.json` exists | required (see below) |
| `COOLDOWN` | argument `COOLDOWN=<seconds>`; `manifest.cooldownSeconds` only for `COOLDOWN=manifest` | required, asked by `epic-run` (see Inputs) |
| `GATES` | `manifest.gateAfter` | `[]` |
| `IMPLEMENTER` | argument | required |
| `REVIEWER` | argument from `epic-run`, else `manifest.reviewer` → `manifest.finalReviewer` | passed to `epic-review` (see Final review) |

**Inferred values need confirmation.** If `VERIFY` or `EPIC` came from detection rather than
the manifest, do not start the loop. Print the resolved config and ask the user to confirm, or
to write the value into the manifest. A wrong verify command turns every task red, and a wrong
`Closes` line closes an epic on its first merge.

Per task, each falling back to the manifest value: `task.verifyCommands`, `task.scope`
(default `[]`, no fencing), `task.lockfileException` (default `false`), `task.promptFile`
(default `<id>.md`).

## Detect manifest shape

If **any** task has `githubIssue` or `issue`, the manifest is **epic-style**: each task closes
its own issue.

    TASK_ISSUE(t) = t.githubIssue ?? t.issue ?? manifest.issue

Commit and PR bodies get `Closes #<TASK_ISSUE(t)>`, plus `Part of #<EPIC>` when `EPIC` is set
and differs from `TASK_ISSUE(t)`.

**Epic without per-task issues.** If no task has `githubIssue` or `issue`, and `EPIC` equals
`manifest.issue`, then commit and PR bodies get `Part of #<EPIC>` only. There is **no `Closes`
line**, because a `Closes` on the first task would close the whole epic after one merge. Step
(i) skips the per-task issue check, and the epic is closed by `epic-review`.

Otherwise the manifest is **legacy single-issue**: every task closes `manifest.issue` and no
`Part of` line is emitted.

## Drive the task loop

**Run the loop in the main conversation.** Two failure modes are well attested with a
delegated cheap orchestrator: the cool-down gets skipped, and tasks run in parallel in one
worktree. The loop is mostly waiting, not tokens.

Save each implementer's output to `$PROMPT_DIR/logs/<task.id>.<harness>.log` and read only its
tail. Ask a same-harness subagent to end with a summary of at most 40 lines.

**Three coordination guards, established before any task runs:**

1. **The lock.** Acquire one persistent directory for the whole invocation:
   ```bash
   mkdir "$PROMPT_DIR/.lock" || { echo "DRIVER_BUSY"; exit 9; }
   ```
   Exit code 9 means another driver may own it: abort rather than deleting it. Record the
   session identity in it. Release only your own lock on completion or a clean halt. After a
   crash, inspect ownership and ask before removing a stale lock.
2. **The repo lock.** The prompt-dir lock serializes drivers of the same epic; this one
   serializes drivers of the same checkout (another epic-drive, issue-ship, ship.py):
   ```bash
   ~/.config/agent-context/scripts/repo-lock.sh acquire "$REPO_PATH" "epic-drive $REPO#$ISSUE_NUM"
   ```
   Exit 9 means another driver owns the checkout: abort and show the printed owner. Keep the
   printed `TOKEN=`; release with it on completion or a clean halt. Steal only after inspecting
   the owner (`--force`) — a live holder means real concurrent work, not a stale lock.
3. **Cool-down at the front, not the back.** A trailing sleep is skippable at zero cost. Fused
   to the head of the next task's work it is not (step a).

**Sequentiality:** exactly one implementer may be running at a time, and no command for task N+1
may start before task N reaches `merged`.

### Preflight (once per invocation)

- `git -C $REPO_PATH status --porcelain` is empty, else stop and report.
- Resolve the actual base branch and the required work ticket first. Use the repository's branch
  prefix and real ticket key.
- Check out that base and `git pull --ff-only` only within the authorized workspace. Do not
  overwrite another session's branch or dirty files.
- `gh auth status` succeeds.
- Every file the task prompts tell the implementer to read exists. A missing shared spec is a hard
  abort, not a warning.
- Run `VERIFY` on the clean base and confirm green, so later failures are attributable to the
  implementer.
- Record `EPIC_BASE_SHA` = `git rev-parse HEAD` on that clean base, and the base branch name. `epic-review`
  diffs against them, so write them to the manifest as `epicBaseSha` and `baseBranch` before the first
  task. On a resume, keep the existing `epicBaseSha`.

Work through tasks in dependency order (respect `blockedBy`), skipping `merged` and `skipped`. A
`failed` task is not retried unless `--retry-failed` was passed.

### a. Cool-down + sync base

One tracked Bash call, cool-down fused to the front:

```bash
# PREV_FINISHED_AT: epoch seconds of the previous task's finishedAt in the manifest (the only anchor).
# No previous finish (first task) means no sleep.
COOL=$(( COOLDOWN - ( $(date +%s) - PREV_FINISHED_AT ) ))   # 0 on the first task
if [ $COOL -gt 0 ]; then
  echo "COOLDOWN START $(date +%s) ($(date)) — ${COOL}s"
  sleep $COOL
  echo "COOLDOWN END $(date +%s) ($(date))"
fi
cd <repoPath> && git checkout <base> && git pull --ff-only && git checkout -b <task.branch>
```

The cool-down is a minimum inter-task-start interval, not a fixed tax. A task that already took
longer than `COOLDOWN` pays nothing. The anchor is always one field: the previous task's `finishedAt`. That bounds requests per hour, which is what usage limits
measure.

Before the sync, assert the checkout is what this run left behind: `git status --porcelain`
empty and HEAD on the base branch. Anything else at a task boundary is foreign work — halt and
report; never commit, stash or discard changes this run did not create.

Set `status: "running"`, increment `attempts`, write `startedAt` **before** launching the
implementer.

### b. Run the implementer

Dispatch on `IMPLEMENTER`. The prompt is the same either way:

- Working directory `<repoPath>`, already on `<task.branch>`.
- Read `$PROMPT_DIR/<task.promptFile>` and implement it, including every acceptance criterion
  and the repository's `VERIFY` commands, run in order.
- The fixed **implementer preamble**, prepended to every implement prompt. Its text lives in one place,
  `~/.config/agent-context/scripts/implement-preamble.md` (source: `claude/scripts/implement-preamble.md`).
  It says: do not `git add`, `git commit`, `git push` or open PRs; stay inside `task.scope` if set; the final
  reply is at most 40 lines; ask no questions; stop and say so if blocked. `run-harness.sh` prepends it
  for the `implement` role only, into a temp file next to the log (`<log>.prompt`), and leaves the
  original prompt file untouched. For a same-harness subagent, read that file and put its text at the top
  of the subagent prompt yourself.
- Do not edit dependency manifests unless the task requires it.

**Same harness as this session:** spawn one subagent of the same harness with the model from
`IMPLEMENTER`. In Claude Code that is `Agent` with `model:` and `subagent_type: general-purpose`.

**Any other harness:**

```bash
mkdir -p "$PROMPT_DIR/logs"
~/.config/agent-context/scripts/run-harness.sh <harness> <model> implement \
  "$REPO_PATH" "$PROMPT_DIR/<task.promptFile>" "$PROMPT_DIR/logs/<task.id>.<harness>.log"
```

Keep the command's handle. Read only `tail -60` of the log. Each run is bounded by `TIMEOUT` (default
30m; set the env var to change it) and a timeout exits non-zero. Exit code 3 means the log shows a
permission denial, so the run did not really succeed: treat it as an incomplete implementer.

Acceptance criteria that need a device, an emulator or screenshots cannot be met by a headless run.
Report them as **not done**, never as failed.

The loop waits for the implementer. It never starts a second implementer on the same branch.

### c. Output gate

`git diff --stat` and `git status --porcelain`. If nothing changed, run the implementer once more with
this appended to the prompt: "IMPORTANT: Nothing was changed. You must implement the code now. Do not
stop until the code is written, the build passes, and tests pass."

Still nothing → `status: "failed"`, `lastError: "no-op"`, **halt the run**. Continuing past a silent
no-op builds a stack of PRs on a missing foundation.

### d. Hygiene + scope check

Remove only explicitly identified scratch files created by this invocation. Never infer ownership from
an extension, timestamp or generic filename.

**Dependencies.** If an unexpected manifest or lockfile change appears, investigate and correct the
implementation rather than silently restoring files. Stop if a required dependency change exceeds the
approved scope.

**Scope.** If `task.scope` is non-empty, assert every path in `git status --porcelain` matches one of its
globs. Stop on unexpected changes. Do not discard them automatically.

### e. Verify

Run each entry of `task.verifyCommands ?? VERIFY` from `$REPO_PATH`, in order, stopping at the first
non-zero exit. The order matters: where one workspace imports another's built output, the build must
precede the tests.

On failure, hand the failing tail to a fixer, the same harness and model as `IMPLEMENTER`, with a
fix-only prompt that also may not commit. Max 2 attempts. Still failing → `status: "failed"`, halt. Never
open a PR that is known red.

### f. Commit

Use the git-commit skill with explicit paths and the actual harness and model attribution from
`IMPLEMENTER`. Use `Part of` for an umbrella epic, and `Closes` only for the task's own issue. Do not claim
another model authored a commit.

### g. Push + PR

Use the pr-create skill with the resolved base, task branch and repository draft policy. Body: concise
summary bullets from the acceptance criteria, then `Closes #<TASK_ISSUE(t)>` and `Part of #<EPIC>`, as
the manifest shape requires.

No `Claude-Session` trailer and no claude.ai session link in commit messages or PR bodies. If
authentication fails, report the blocker. Do not change the remote URL, account or credential
configuration.

Record `task.pr` and `status: "pr_open"`, then **write the manifest immediately**. This is the most
important persistence point for resumability.

### h. Wait for CI + merge

Use the read-only pr-watch helper for the exact repository and PR, with a bounded wait (for example
`--interval 30 --max-ticks 40`). Mergeability alone does not prove checks passed.

- Passing checks and satisfied branch requirements → the scope-aware pr-merge skill. For work
  repositories, leave the PR for human merge and stop dependent work. Record `merged` only after
  GitHub confirms it.
- Failing checks → one scoped ci-fix commit and push, then resume observation. This is the explicitly
  authorized repair for this workflow.
- `DIRTY` (conflict) → report the divergence and request approved recovery. Do not rebase, amend or
  force-push automatically.
- Timeout → `failed`, halt. **Never merge unverified.**

### i. Settle

Only after GitHub confirms the merge: `status: "merged"`, `finishedAt`, keep `pr`. In an epic-style
manifest with per-task issues, confirm the issue closed (`gh issue view <TASK_ISSUE(t)> --json state`).
If the `Closes` trailer did not fire, close it with a comment linking the PR. Skip this for an epic
without per-task issues.

**No trailing sleep.** The cool-down is the next task's step (a).

If `task.id` is in `GATES`, stop and emit a checkpoint report instead of continuing.

## Final review

When every task is `merged` or `skipped`, run the `epic-review` skill, with `REVIEWER=<harness>:<model>` as
chosen in `epic-run` (or `manifest.reviewer`, else ask once). Do this after the last merge and before the final
report. Pass it `REPO_PATH`, the confirmed `VERIFY`, and `epicBaseSha`/`baseBranch` from the manifest. Do not
run it after a halt. If `epicReview` is already `approved`, skip it. The review loop and its fix PRs belong
to `epic-review`.

## Failure handling

| failure | detection | action |
|---|---|---|
| implementer no-op | empty `diff --stat` after the retry | `failed`, halt |
| implementer incomplete | ends without finishing or reports an error | keep partial work, run (c), (d), then (e); verify red → `failed`, halt |
| verify red | non-zero verify command | fixer ×2 → else `failed`, halt |
| out-of-scope files | `status --porcelain` vs `task.scope` | preserve files, halt, resolve ownership or scope |
| CI red | `statusCheckRollup` FAILURE | `ci-fix` ×1 → else `failed`, halt |
| merge conflict | `mergeStateStatus: DIRTY` | halt, request approved recovery |
| **usage limit** | log matches `usage limit\|rate limit\|resets at\|429` | **not a failure**. Parse the reset time, sleep until it + 120 s, do not increment `attempts`, retry the same task. Exit code 0 is possible on agy, so check the log, not only the exit code |
| lock held | `mkdir` fails, exit 9 | abort; another driver is live |
| repo lock held | `repo-lock.sh acquire` exits 9 | abort; show the printed owner. Steal with `--force` only after inspecting it |
| foreign checkout state | dirty tree or wrong branch at a task boundary | halt; never commit, stash or discard work the run did not create |

"Halt" always means: leave the branch and PR intact, write `lastError`, print a resume line,
release the repo lock, stop.
**Never skip a failed task and continue.**

Cap `attempts` at 3 per task.

## Resumability

Status runs `pending → running → pr_open → merged`, plus terminal `failed` and `skipped`. The loop writes
exactly these; implement and verify are steps inside `running`, not states. `epicReview` is owned by `epic-review`. Write the manifest after **every** transition.

Re-invoking reconciles against GitHub, which is the source of truth:

1. Find the first task not `merged` or `skipped`. If there is none, the tasks are done: hand off to
   `epic-review` unless `epicReview` is already `approved`.
2. `gh pr list --head <task.branch> --state all --json number,state,mergedAt`:
   - merged → mark `merged`, move on
   - open → resume at step (h)
   - no PR, remote branch exists → resume at step (e)
   - nothing → restart at step (a)
3. `failed` tasks need `--retry-failed` before `attempts` resets.

Worst-case loss from a crash is one implementer run.

## Final report

A table: task → issue → PR → status → wall clock → implementer. Then the `epic-review` verdict, the
epic's state, and the resume command if anything is outstanding. For a run-all, one section per epic in
run order, then a short overall line: epics completed, the epic that halted (if any), and epics not started.

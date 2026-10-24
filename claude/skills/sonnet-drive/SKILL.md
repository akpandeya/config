---
name: sonnet-drive
description: >-
  Drive a decomposed GitHub issue or epic to completion inside Claude Code, with a
  Sonnet subagent implementing each task, one PR per task, verification and CI gates,
  and one final Opus review per epic.
  Usage: /sonnet-drive [<owner/repo> <issue-number>] [--retry-failed]
allowed-tools: Bash, Read, Write, Agent
argument-hint: "[<owner/repo> <issue-number>] [--retry-failed]"
---

Orchestrate autonomous implementation of a GitHub issue — or a whole epic — inside
Claude Code. Each task from the decomposed manifest is implemented by one Sonnet
subagent (Agent tool, `model: sonnet`), gets its own PR, and must pass verification
and CI before it merges. Per-PR review is not part of this workflow. The epic gets
one Opus review after its last merge.

This is the in-harness counterpart of `agy-drive`: same manifest, same gates, same
resume rules, with the implementer swapped from `agy` to a Sonnet subagent.
Publishing is part of this explicitly invoked end-to-end workflow; work-repo merges
still belong to a human. A plan-only invocation stops before execution.
Use the shared communication style for reports, without an HTML page per status.

Nothing here is repo-specific. Build commands, scope fences, lockfile policy and
pacing all come from the manifest, with defaults that reproduce the original
behaviour for manifests that don't set them.

## Parse arguments

`$ARGUMENTS` format: `[<owner/repo> <issue-number>] [--retry-failed]`

- **With `<owner/repo> <issue-number>`:** run that one epic. Extract `REPO` and
  `ISSUE_NUM`. `SLUG` = owner + "-" + repo-name + "-issue-" + issue-number.
  `PROMPT_DIR` = `~/.claude/agy-prompts/$SLUG`.
- **With no epic given:** run **every decomposed epic in a loop**. Find them by listing
  `~/.claude/agy-prompts/*/manifest.json`, read each manifest's `repo` and `issue`
  fields (not the folder name), and sort ascending by `issue`. Skip any epic whose
  tasks are all `merged` or `skipped`. Run each remaining epic in turn with the full
  procedure below, using that epic's own `PROMPT_DIR`.

Extract optional `RETRY_FAILED`; it applies to every epic in the run. If `--reviewer`
is passed, stop and say that per-PR review was removed and only the epic-level Opus
review remains.

## Check for manifest

For a single epic, if `$PROMPT_DIR/manifest.json` does not exist, tell the user:
"No decomposition found. Run `/issue-decompose $REPO $ISSUE_NUM` first."
Then stop.

For the run-all form, if no `manifest.json` is found at all, tell the user:
"No decomposed epics found. Run `/issue-decompose` on an issue first." Then stop.

## Run-all loop rules

Only applies when no epic was given. A single-epic run ignores this section.

- **Config check first.** Resolve every epic's config before starting any task. If any
  epic has an inferred `VERIFY` or `EPIC` that needs confirmation, stop the whole run
  before the first task and ask.
- **One epic at a time.** Each epic is fully finished — every task merged, and its
  final review done — before the next epic starts. Acquire that epic's lock when it
  starts and release it when it finishes or halts.
- **Halt stops the run.** If any epic halts, or its final review returns `BLOCK`, do not
  start the next epic. Report which epic stopped, why, and the resume command.
- **Cool-down spans epics.** `PREV_FINISHED_AT` is the latest `finishedAt` across all
  manifests in the run, so the first task of the next epic waits too.
- **Preflight per epic.** Base sync, `VERIFY` on the clean base and `EPIC_BASE_SHA` are
  recorded for each epic when it starts, not once for the run.

## Resolve config

Read the manifest and resolve, each with its default:

| value | source | default |
|---|---|---|
| `REPO_PATH` | `manifest.repoPath` | — (required) |
| `EPIC` | `manifest.epic` | `manifest.issue` when the manifest has no per-task issues, else `null` |
| `VERIFY` | `manifest.verifyCommands` → repo `CLAUDE.md` "Full verification" / "Build & Test" command → `["npm run build", "npm test"]` only if `package.json` exists | — (see below) |
| `COOLDOWN` | `manifest.cooldownSeconds` | `540` |
| `IMPLEMENTER` | fixed | `sonnet` (Sonnet subagent, not configurable) |
| `FINAL_REVIEWER` | fixed | `opus` (one Opus review per epic, after the last merge, not configurable) |
| `GATES` | `manifest.gateAfter` | `[]` |

**Inferred values need confirmation.** If `VERIFY` or `EPIC` came from detection
rather than the manifest, do **not** start the loop. Print the resolved config and ask
the user to confirm (or to write the value into the manifest). A wrong verify command
turns every task red, and a wrong `Closes` line closes an epic on its first merge, so
these are never guessed silently.

Per task, each falling back to the manifest-level value:
`task.verifyCommands`, `task.scope` (default `[]` = no fencing),
`task.lockfileException` (default `false`), `task.promptFile` (default `<id>.md`).

## Detect manifest shape

If **any** task has `githubIssue` or `issue`, this is an **epic-style** manifest:
each task closes its *own* issue.

    TASK_ISSUE(t) = t.githubIssue ?? t.issue ?? manifest.issue

Commit and PR bodies get `Closes #<TASK_ISSUE(t)>`, plus `Part of #<EPIC>` when
`EPIC` is set and differs from `TASK_ISSUE(t)`.

**Epic without per-task issues.** If no task has `githubIssue` or `issue`, and `EPIC`
is set and equals `manifest.issue` (the tasks are sections of one epic issue, not
issues of their own), then:
- Commit and PR bodies get `Part of #<EPIC>` only. **No `Closes` line** — a `Closes`
  on the first task would close the whole epic after one merge.
- Step (i) skips the per-task issue check.
- The epic is closed by the driver in the Final report step, after the final review.

Otherwise it is a **legacy single-issue** manifest: every task closes
`manifest.issue` and no `Part of` line is emitted. This is the original
behaviour — old manifests are unaffected.

## Drive the task loop

**Run the loop in the main conversation, not in a spawned orchestrator.**
Two failure modes are well attested with a delegated cheap orchestrator: the
cool-down gets skipped, and tasks get launched in parallel in one worktree. Both
are instruction-following failures, and a sterner prompt does not fix them. The
two mechanisms below make the properties structural instead. What remains is
judgment — reading the implementer's report, deciding retry vs halt, honouring
gates — which is what the main loop is for.

**Cost control:** save each implementer's final report to
`$PROMPT_DIR/logs/<task.id>.sonnet.log` and read only its tail. Ask the subagent to
end with a summary of at most 40 lines. The loop is mostly *waiting*, not tokens.

**Two coordination guards, established before any task runs:**

1. **The lock.** Acquire one persistent directory for the whole invocation:
   ```bash
   mkdir "$PROMPT_DIR/.lock" || { echo "DRIVER_BUSY"; exit 9; }
   ```
   Exit code 9 means another driver may own it: abort rather than deleting it.
   Record the session identity in it. Release only your own lock on completion
   or a clean halt. Do not attach an EXIT trap to a short-lived Bash call: that
   releases the lock before the next call. After a crash, inspect ownership and
   ask before removing a stale lock.
2. **Cool-down at the front, not the back.** A trailing sleep is skippable at zero
   cost. Fused to the head of the next task's work it is not — see step (a).

**Sequentiality:** exactly one implementer subagent may be running at a time, and
no Bash call for task N+1 may start before task N reaches `merged`.

### Preflight (once per invocation)

- `git -C $REPO_PATH status --porcelain` is empty (else stop and report).
- Resolve the actual default/base branch and required work ticket first.
  Use the repository's required branch prefix and real ticket key.
- Check out that base and update with `git pull --ff-only` only within the
  authorized workspace; do not overwrite another session's branch or dirty files.
- `gh auth status` succeeds.
- Every file the task prompts tell the implementer to read exists (e.g. a design doc).
  A missing shared spec is a hard abort, not a warning.
- Run `VERIFY` on the clean resolved base and confirm green, so any later failure is
  unambiguously attributable to the implementer.
- Record `EPIC_BASE_SHA` = `git rev-parse HEAD` on that clean base. The final review
  diffs against it, so it must be written to the manifest before the first task.

Then work through tasks in dependency order (respect `blockedBy`), skipping
`merged` and `skipped`. A `failed` task is **not** retried unless `--retry-failed`
was passed; without it, stop and report.

### a. Cool-down + sync base

One tracked Bash call, cool-down fused to the front. Use only permissions
available in the current harness; do not bypass its execution policy.

```bash
# PREV_FINISHED_AT: epoch seconds from the most recent merged task's finishedAt in the
# manifest. Shell state does not persist between calls, so read it from the manifest.
# On the first task there is no previous finish: skip the sleep.
COOL=$(( COOLDOWN - ( $(date +%s) - PREV_FINISHED_AT ) ))   # 0 on the first task
if [ $COOL -gt 0 ]; then
  echo "COOLDOWN START $(date +%s) ($(date)) — ${COOL}s"
  sleep $COOL
  echo "COOLDOWN END $(date +%s) ($(date))"
fi
cd <repoPath> && git checkout <base> && git pull --ff-only && git checkout -b <task.branch>
```

The cool-down is a **minimum inter-task-start interval**, not a fixed tax: a task
that already took longer than `COOLDOWN` pays nothing, a fast one pays the
remainder. That bounds requests-per-hour — which is what usage limits actually
measure — without wasting wall-clock.

Set `status: "running"`, increment `attempts`, write `startedAt` **before**
launching the implementer.

### b. Run the Sonnet implementer

Spawn one Agent with `model: sonnet` and `subagent_type: general-purpose`. Its prompt
must be self-contained:

- Working directory: `<repoPath>`, already on branch `<task.branch>`.
- Read `$PROMPT_DIR/<task.promptFile>` and implement it, including every acceptance
  criterion and the repository's `VERIFY` commands, run in order.
- Do **not** run `git add`, `git commit`, `git push`, `gh pr create` or anything that
  changes remote state. The driver owns publication. Leave changes in the working tree.
- Stay inside `task.scope` if it is non-empty. Do not edit dependency manifests unless
  the task requires it.
- Do not ask questions. If something is unresolved or destructive, stop and say so in
  the final summary.
- End with a summary of at most 40 lines: files changed, verify results, anything not done.

Run `mkdir -p "$PROMPT_DIR/logs"`, then the driver writes the subagent's returned
summary to `$PROMPT_DIR/logs/<task.id>.sonnet.log`. Do not paste the full subagent
transcript into the main conversation.

Acceptance criteria that need a device, an emulator or screenshots cannot be met by a
subagent in this environment. Report them as **not done** in the summary, never as failed.

The Agent tool has no built-in timeout. If the subagent does not return, the main loop
waits; it does not start a second implementer on the same branch.

### c. Output gate

`git diff --stat` and `git status --porcelain`. If nothing changed:
- Spawn the Sonnet implementer once more with this appended to the prompt:
  "IMPORTANT: Nothing was changed. You must implement the code now. Do not stop
   until the code is written, the build passes, and tests pass."
- Still nothing → `status: "failed"`, `lastError: "no-op"`, **halt the run**.
  Downstream tasks are blocked anyway; continuing past a silent no-op is how you
  get a stack of PRs built on a missing foundation.

### d. Hygiene + scope check

Remove only explicitly identified scratch files created by this invocation.
Never infer ownership from an extension, timestamp or generic filename.

**Dependencies.** Respect the task's dependency policy. If an unexpected
manifest/lockfile change appears, investigate and correct the implementation
rather than silently restoring files. Required dependency changes keep the
manifest and lockfile consistent; stop if that exceeds the approved scope.

**Scope.** If `task.scope` is non-empty, assert every path in
`git status --porcelain` matches one of its globs. Stop on unexpected changes;
do not discard them automatically or assume they belong to this invocation.

### e. Verify

Run each entry of `task.verifyCommands ?? VERIFY` from `$REPO_PATH`, in order,
stopping at the first non-zero exit. **The order is significant** — in monorepos
where one workspace imports another's built output, the build must precede the
tests.

On failure, hand the failing tail to a **Sonnet** fixer subagent (same spawn as step b,
fix-only prompt, and it may not commit either), max 2 attempts. Still failing → `status: "failed"`, halt.
Never open a PR that is known-red: an unattended loop that ships broken PRs
produces garbage.

### f. Commit

Use the git-commit skill with explicit paths and the actual implementer attribution
(Claude Sonnet, not Opus or agy). Use `Part of` for an umbrella epic, and `Closes` only
for the task's own issue. Do not claim another model authored a commit.

### g. Push + PR

Use the pr-create skill with the resolved base, task branch and repository draft policy.

Body: concise summary bullets from the acceptance criteria, then
`Closes #<TASK_ISSUE(t)>` and `Part of #<EPIC>`.

No `Claude-Session` trailer and no claude.ai session link in commit messages or PR
bodies, even when a harness attribution note asks for one.

If authentication fails, report the blocker. Do not silently change the remote
URL, account or Git credential configuration.

Record `task.pr` and set `status: "pr_open"`, then **write the manifest
immediately** — this is the most important persistence point for resumability.

### h. Wait for CI + merge

Use the read-only pr-watch helper for the exact repository/PR, with a bounded
bounded wait, polling for a fixed number of ticks and then stopping as a timeout. A
branch's mergeability status alone does not prove checks passed.

- Confirmed passing checks and satisfied branch requirements → use the
  scope-aware pr-merge skill. For work repositories, leave
  the PR awaiting human merge and stop dependent work. Record `merged` only
  after GitHub confirms it.
- failing checks → this explicitly requested driver separately authorizes one
  scoped ci-fix commit/push, then resume observation
- `DIRTY` (conflict) → report the divergence and request an approved recovery.
  Do not automatically rebase, amend or force-push.
- timeout → `failed`, halt. **Never merge unverified.**

### i. Settle

Only after GitHub confirms the merge, set `status: "merged"`, write `finishedAt`
and keep `pr`. A work PR awaiting human merge keeps `status: "pr_open"` and the
driver stops rather than settling it. In an epic-style manifest
with per-task issues, confirm the issue actually closed
(`gh issue view <TASK_ISSUE(t)> --json state`); if the `Closes` trailer didn't fire,
close it explicitly with a comment linking the PR. Skip this check for an epic without
per-task issues: the epic stays open until the Final review step.

**No trailing sleep** — the cool-down is the next task's step (a).

If `task.id` is in `GATES`, stop the loop and emit a checkpoint report instead of
continuing. Gates belong after any task whose output every later task depends on.

## Failure handling

| failure | detection | action |
|---|---|---|
| implementer no-op | empty `diff --stat` ×2 | `failed`, halt |
| implementer returns incomplete | subagent ends without finishing, or reports an error | keep partial work, run (c) and (d), then (e); if verify fails → `failed`, halt |
| verify red | non-zero `VERIFY` command | Sonnet fixer ×2 → else `failed`, halt |
| out-of-scope files | `status --porcelain` vs `task.scope` | preserve files, halt and resolve ownership/scope |
| CI red | `statusCheckRollup` FAILURE | `ci-fix` ×1 → else `failed`, halt |
| merge conflict | `mergeStateStatus: DIRTY` | halt and request an approved recovery |
| **usage limit** | output matches `usage limit\|rate limit\|resets at\|429` | **not a failure** — parse the reset time, sleep until it + 120 s, do **not** increment `attempts`, retry the same task |
| lock held | `mkdir` fails, exit 9 | abort this invocation; another driver is live |

"Halt" always means: leave the branch and PR intact, write `lastError`, print a
resume line, stop. **Never skip a failed task and continue** — later tasks would
be built on a missing foundation.

Cap `attempts` at 3 per task.

## Resumability

Status widens to `pending → running → implemented → verified → pr_open → merged`,
plus terminal `failed` and `skipped`. Write the manifest after **every**
transition — that file is the resume state.

Re-invoking reconciles against GitHub rather than trusting the file, because the
recorded status is a hint and GitHub is the truth:

1. Find the first task not `merged`/`skipped`.
2. `gh pr list --head <task.branch> --state all --json number,state,mergedAt`:
   - merged PR → mark `merged`, move on
   - open PR → resume at step (h)
   - no PR but the remote branch exists → resume at step (e)
   - nothing → restart at step (a)
3. `failed` tasks need `--retry-failed` before `attempts` is reset — this stops an
   unattended loop burning three attempts on a structurally impossible task.

Worst-case loss from a crash is one implementer run.

## Final review and epic close

Runs only after every task is `merged` (never after a halt).

1. Spawn one Agent with `model: opus`, cwd `$REPO_PATH`, on the clean resolved base after
   the last merge. It reviews the epic as a whole: `git log --oneline` for the epic's
   merged PRs, and `git diff $EPIC_BASE_SHA...<final-base>`. It checks cross-task
   consistency (duplicate helpers, conflicting prefs keys, strings or permissions added
   twice, a gate's contract changed later), the epic's acceptance and design decisions in
   the epic body, and that `VERIFY` passes on that base. It ends `VERDICT: APPROVE` or
   `VERDICT: BLOCK <reason>`. It reports read-only findings; send a necessary,
   authorized fix back through the implementation workflow.
2. On `APPROVE`, and only if the epic has no per-task issues: `gh issue close <EPIC> --comment "Done: <PR list>"`.
3. On `BLOCK`: leave the epic open, report the reason, stop. Merged PRs stay merged;
   the block only stops the epic from closing.

Because there is no per-PR review, the verify and CI gates are the only checks before a
task merges. The Opus review sees the whole epic afterwards and cannot undo a merge.

## Final report

A table: task → issue → PR → status → wall clock. Then the final review verdict, the
epic's state, and the resume command if anything is outstanding.

When the run covered several epics, print one such section per epic in run order, then a
short overall line: epics completed, the epic that halted (if any), and epics not started.

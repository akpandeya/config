---
name: agy-drive
description: Drive a decomposed GitHub issue or epic to completion using agy — one PR per task, each closing its own issue, reviewed by Opus/Sonnet/agy before merge. Usage: /agy-drive <owner/repo> <issue-number> [--reviewer=opus|sonnet|agy] [--retry-failed]
allowed-tools: Bash, Read, Write, Agent
argument-hint: "<owner/repo> <issue-number> [--reviewer=opus|sonnet|agy] [--retry-failed]"
---

Orchestrate autonomous implementation of a GitHub issue — or a whole epic — using
`agy`. Each task from the decomposed manifest runs as a separate `agy` invocation,
gets its own PR, and is reviewed and merged before the next task starts.

Nothing here is repo-specific. Build commands, scope fences, lockfile policy and
pacing all come from the manifest, with defaults that reproduce the original
behaviour for manifests that don't set them.

## Parse arguments

`$ARGUMENTS` format: `<owner/repo> <issue-number> [--reviewer=opus|sonnet|agy] [--retry-failed]`

Extract `REPO`, `ISSUE_NUM`, optional `REVIEWER`, optional `RETRY_FAILED`.
`SLUG` = owner + "-" + repo-name + "-issue-" + issue-number.
`PROMPT_DIR` = `~/.claude/agy-prompts/$SLUG`.

## Check for manifest

If `$PROMPT_DIR/manifest.json` does not exist, tell the user:
"No decomposition found. Run `/issue-decompose $REPO $ISSUE_NUM` first."
Then stop.

## Resolve config

Read the manifest and resolve, each with its default:

| value | source | default |
|---|---|---|
| `REPO_PATH` | `manifest.repoPath` | — (required) |
| `EPIC` | `manifest.epic` | `null` |
| `VERIFY` | `manifest.verifyCommands` | `["npm run build", "npm test"]` |
| `COOLDOWN` | `manifest.cooldownSeconds` | `540` |
| `REVIEWER` | `--reviewer` → `manifest.reviewer` → ask | — |
| `GATES` | `manifest.gateAfter` | `[]` |

Per task, each falling back to the manifest-level value:
`task.verifyCommands`, `task.scope` (default `[]` = no fencing),
`task.lockfileException` (default `false`), `task.promptFile` (default `<id>.md`).

## Detect manifest shape

If **any** task has `githubIssue` or `issue`, this is an **epic-style** manifest:
each task closes its *own* issue.

    TASK_ISSUE(t) = t.githubIssue ?? t.issue ?? manifest.issue

Commit and PR bodies get `Closes #<TASK_ISSUE(t)>`, plus `Part of #<EPIC>` when
`EPIC` is set and differs from `TASK_ISSUE(t)`.

Otherwise it is a **legacy single-issue** manifest: every task closes
`manifest.issue` and no `Part of` line is emitted. This is the original
behaviour — old manifests are unaffected.

## Ask reviewer if not provided

If `--reviewer` was absent and `manifest.reviewer` is unset, ask:

Who should review each PR before merging?
- **Opus** — deepest review; checks frozen contracts, purity, determinism and test
  substance, and blocks the merge on a violation (~8 min per PR). Use for engine,
  schema and contract work.
- **Sonnet** — thorough, good for ordinary feature changes (~2 min per PR)
- **agy** — a second autonomous agy pass that checks acceptance criteria and fixes
  issues (~3–5 min per PR)

## Drive the task loop

**Run the loop in the main conversation, not in a spawned Haiku orchestrator.**
Two failure modes are well attested with a delegated cheap orchestrator: the
cool-down gets skipped, and tasks get launched in parallel in one worktree. Both
are instruction-following failures, and a sterner prompt does not fix them. The
two mechanisms below make the properties structural instead. What remains is
judgment — reading agy's output, deciding retry vs halt, honouring gates — which
is what the main loop is for.

**Cost control:** `tee` agy's output to `$PROMPT_DIR/logs/<task.id>.agy.log` and
read only `tail -60` of it. The loop is mostly *waiting*, not tokens.

**Two structural guarantees, established before any task runs:**

1. **The lock.** `mkdir` is atomic, so this cannot race:
   ```bash
   mkdir "$PROMPT_DIR/.lock" || { echo "DRIVER_BUSY"; exit 9; }
   trap 'rmdir "$PROMPT_DIR/.lock" 2>/dev/null' EXIT
   ```
   Exit code 9 means another driver is live — **abort this invocation entirely**.
2. **Cool-down at the front, not the back.** A trailing sleep is skippable at zero
   cost. Fused to the head of the next task's work it is not — see step (a).

**Sequentiality:** exactly one Bash call may be in flight at a time. Never issue
task N+1's commands before task N reaches `merged`.

### Preflight (once per invocation)

- `git -C $REPO_PATH status --porcelain` is empty (else stop and report).
- `git -C $REPO_PATH checkout main && git pull --ff-only`.
- `gh auth status` succeeds.
- Every file the task prompts tell agy to read exists (e.g. a design doc).
  A missing shared spec is a hard abort, not a warning.
- Run `VERIFY` on clean `main` and confirm green, so any later failure is
  unambiguously attributable to agy.

Then work through tasks in dependency order (respect `blockedBy`), skipping
`merged` and `skipped`. A `failed` task is **not** retried unless `--retry-failed`
was passed; without it, stop and report.

### a. Cool-down + sync main

One bash call, **sandbox disabled**, cool-down fused to the front:

```bash
COOL=$(( COOLDOWN - ( $(date +%s) - PREV_FINISHED_AT ) ))   # 0 on the first task
if [ $COOL -gt 0 ]; then
  echo "COOLDOWN START $(date +%s) ($(date)) — ${COOL}s"
  sleep $COOL
  echo "COOLDOWN END $(date +%s) ($(date))"
fi
cd <repoPath> && git checkout main && git pull --ff-only && git checkout -B <task.branch>
```

The cool-down is a **minimum inter-task-start interval**, not a fixed tax: a task
that already took longer than `COOLDOWN` pays nothing, a fast one pays the
remainder. That bounds requests-per-hour — which is what usage limits actually
measure — without wasting wall-clock.

Set `status: "running"`, increment `attempts`, write `startedAt` **before**
launching agy.

### b. Run agy

Sandbox disabled; bash timeout 35 min (above agy's own 30, so agy's timeout fires
first and its partial work survives):

```bash
mkdir -p "$PROMPT_DIR/logs"
agy --dangerously-skip-permissions --print-timeout 30m \
  -p "$(cat $PROMPT_DIR/<task.promptFile>)" 2>&1 \
  | tee "$PROMPT_DIR/logs/<task.id>.agy.log"
```

Then read only `tail -60` of that log.

### c. Output gate

`git diff --stat` and `git status --porcelain`. If nothing changed:
- Re-run agy once with this appended to the prompt:
  "IMPORTANT: Nothing was changed. You must implement the code now. Do not stop
   until the code is written, the build passes, and tests pass."
- Still nothing → `status: "failed"`, `lastError: "no-op"`, **halt the run**.
  Downstream tasks are blocked anyway; continuing past a silent no-op is how you
  get a stack of PRs built on a missing foundation.

### d. Hygiene + scope check

Remove `*.patch`, `dev_output.log`, stray `.py` scratch scripts, `.agy/`.

**Lockfile.** Unless `task.lockfileException` is true, restore dependency
manifests from main:
```bash
git checkout main -- package.json package-lock.json 2>/dev/null || true
```
When `lockfileException` **is** true, leave them alone — the task creates a new
workspace, and CI's `npm ci` fails if the lockfile doesn't list it.

**Scope.** If `task.scope` is non-empty, assert every path in
`git status --porcelain` matches one of its globs. Revert anything outside
(`git checkout main -- <path>`, or `rm` if untracked) and note it in the PR body.

### e. Verify

Run each entry of `task.verifyCommands ?? VERIFY` from `$REPO_PATH`, in order,
stopping at the first non-zero exit. **The order is significant** — in monorepos
where one workspace imports another's built output, the build must precede the
tests.

On failure, hand the failing tail to a **Sonnet** fixer agent (this is mechanical;
it doesn't need Opus), max 2 attempts. Still failing → `status: "failed"`, halt.
Never open a PR that is known-red: an unattended loop that ships broken PRs
produces garbage.

### f. Commit

Sandbox disabled (SSH-agent signing fails inside it).

```bash
git add -- <explicit changed paths>     # never `git add -A`, never `git add -p`
git commit -m "<conventional-commit title>

Closes #<TASK_ISSUE(t)>
<Part of #EPIC — only when EPIC is set and differs>

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

`git add -p` is interactive and cannot work unattended — always use explicit paths.

If the commit fails with `agent refused operation` or `gpg failed to sign`, retry
once as `git -c commit.gpgsign=false commit --no-gpg-sign -m "..."`.

### g. Push + PR

```bash
git push -u origin <task.branch>
gh pr create --base main --head <task.branch> \
  --title "<task.title>" \
  --body "..."
```

Body: summary bullets from the acceptance criteria, a Test plan with one line per
`VERIFY` command, any out-of-scope reverts from step (d), then
`Closes #<TASK_ISSUE(t)>` and `Part of #<EPIC>`.

If the push fails with `Permission denied (publickey)`, run `gh auth setup-git`
and set the remote to its HTTPS URL, then retry.

Record `task.pr` and set `status: "pr_open"`, then **write the manifest
immediately** — this is the most important persistence point for resumability.

### h. Review

**reviewer = opus** — spawn an Opus Agent (`model: opus`), cwd `$REPO_PATH`,
branch checked out. It must check, in this order:

1. **Frozen-contract compliance**, if the task prompt names frozen files. Diff them
   against main; any rename, retype, removal or narrowed optionality is
   **blocking**. Additive-only is the bar. This is the check a cheaper reviewer
   waves through, so it goes first.
2. **Purity**, if the task prompt requires it — grep for the forbidden constructs
   it names (`Math.random`, `Date.now`, `fetch(`, DOM globals, I/O).
3. **Determinism** — if the package claims reproducibility, there must be a test
   asserting identical inputs produce identical serialized output, plus a
   round-trip test. Rules added without matching coverage is a finding.
4. **Acceptance criteria** — walk each `- [ ]` in the task file and state
   met / not-met / partial, **citing the file and line** that satisfies it.
   "Looks fine" is not acceptable.
5. **Conventions** — conformance to whatever template the task prompt points at.
6. **Scope** — `git diff --name-only main...<branch>` entirely within `task.scope`;
   lockfile touched only if `lockfileException`.
7. **Test substance** — no `.skip`/`.only`, no assertion-free tests, no snapshot
   added to paper over a failure, no loosened existing assertions. Diffs to
   pre-existing test files get extra scrutiny.
8. **Re-run `VERIFY` itself** and confirm exit 0.

It **may**: fix failing tests and type errors, add missing tests for implemented
criteria, tighten types, delete scratch files, revert out-of-scope edits, then
`git add && git commit --amend --no-edit && git push --force-with-lease`.

It **may not**: change a frozen schema (even to improve it), add dependencies,
edit outside `task.scope`, or redesign the approach.

It ends with `VERDICT: APPROVE` or `VERDICT: BLOCK <reason>`. On `BLOCK`, mark the
task `failed` and halt — do not merge.

**reviewer = sonnet** — spawn a Sonnet Agent (`model: sonnet`):
"Review the open PR on branch `<task.branch>` in `<repoPath>`. Read
`git diff main...<task.branch>`. Check each acceptance criterion in
`$PROMPT_DIR/<task.promptFile>`. Run: `<VERIFY commands>`. Fix any issues in the
working tree, then `git add && git commit --amend --no-edit && git push
--force-with-lease`. Report what you fixed."

**reviewer = agy**:
```bash
agy --dangerously-skip-permissions --print-timeout 15m -p "
Review the changes on git branch <task.branch> in <repoPath>.
Read: git diff main...<task.branch>
Check every acceptance criterion in $PROMPT_DIR/<task.promptFile>.
Run, in order, stopping at the first failure: <VERIFY commands>
Fix any issues. If you made fixes: git add <files> && git commit --amend --no-edit && git push --force-with-lease.
Report what you found and fixed. Then stop.
"
```

### i. Wait for CI + merge

Poll every 30 s, up to 40 times (20 min) — a real CI run doing a clean install
plus a full build and test suite will not be `CLEAN` inside the old 150 s budget.

```bash
for i in $(seq 1 40); do
  gh pr view <task.pr> --json mergeStateStatus,statusCheckRollup
  # CLEAN -> merge
  sleep 30
done
```

- `CLEAN` → `gh pr merge <task.pr> --squash --delete-branch`
- failing checks → invoke the `ci-fix` skill once, then resume polling
- `DIRTY` (conflict) → `git checkout <branch> && git rebase origin/main`, re-run
  `VERIFY`, force-push, resume polling; a second conflict → `failed`, halt
- timeout → `failed`, halt. **Never merge unverified.**

### j. Settle

Set `status: "merged"`, write `finishedAt`, keep `pr`. Confirm the issue actually
closed (`gh issue view <TASK_ISSUE(t)> --json state`); if the `Closes` trailer
didn't fire, close it explicitly with a comment linking the PR.

**No trailing sleep** — the cool-down is the next task's step (a).

If `task.id` is in `GATES`, stop the loop and emit a checkpoint report instead of
continuing. Gates belong after any task whose output every later task depends on.

## Failure handling

| failure | detection | action |
|---|---|---|
| agy no-op | empty `diff --stat` ×2 | `failed`, halt |
| agy timeout | bash `timeout` at 35 min | keep partial work, go to (e); if verify fails → `failed`, halt |
| verify red | non-zero `VERIFY` command | Sonnet fixer ×2 → else `failed`, halt |
| out-of-scope files | `status --porcelain` vs `task.scope` | revert those paths, continue, note in PR |
| CI red | `statusCheckRollup` FAILURE | `ci-fix` ×1 → else `failed`, halt |
| merge conflict | `mergeStateStatus: DIRTY` | rebase + reverify + force-push ×1 → else `failed`, halt |
| reviewer BLOCK | `VERDICT: BLOCK` | `failed`, halt |
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

Worst-case loss from a crash is one agy run.

## Final report

A table: task → issue → PR → status → wall clock. Then the resume command if
anything is outstanding.

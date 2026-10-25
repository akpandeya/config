---
name: agy-drive
description: >-
  Drive a decomposed GitHub issue or epic using agy, with one PR per task and a
  single review of the whole epic after its last merge, followed by any fixes the
  review recommends.
  Usage: /agy-drive <owner/repo> <issue-number> [--reviewer=opus|sonnet|agy] [--retry-failed]
allowed-tools: Bash, Read, Write, Agent
argument-hint: "<owner/repo> <issue-number> [--reviewer=opus|sonnet|agy] [--retry-failed]"
---

Orchestrate autonomous implementation of a GitHub issue — or a whole epic — using
`agy`. Each task from the decomposed manifest runs as a separate `agy` invocation and
gets its own PR. The whole epic is reviewed **once, after its last merge** — there is
no per-PR review — and any fixes that review recommends are applied before the epic
closes.
Publishing is part of this explicitly invoked end-to-end workflow; work-repo
merges still belong to a human. A plan-only invocation stops before execution.
Use the shared communication style for reports, without an HTML page per status.

Nothing here is repo-specific. Build commands, scope fences, lockfile policy and
pacing all come from the manifest, with defaults that reproduce the original
behaviour for manifests that don't set them.

## Parse arguments

`$ARGUMENTS` format: `<owner/repo> <issue-number> [--reviewer=opus|sonnet|agy] [--retry-failed]`

Extract `REPO`, `ISSUE_NUM`, optional `REVIEWER`, optional `RETRY_FAILED`.
`SLUG` = owner + "-" + repo-name + "-issue-" + issue-number.
`PROMPT_DIR` = `~/.claude/agy-prompts/$SLUG`.

`REVIEWER` selects the model for the **single epic-level review**, run after the last
task merges. It does not review each PR.

## Check for manifest

If `$PROMPT_DIR/manifest.json` does not exist, tell the user:
"No decomposition found. Run `/issue-decompose $REPO $ISSUE_NUM` first."
Then stop.

## Resolve config

Read the manifest and resolve, each with its default:

| value | source | default |
|---|---|---|
| `REPO_PATH` | `manifest.repoPath` | — (required) |
| `EPIC` | `manifest.epic` | `manifest.issue` when the manifest has no per-task issues, else `null` |
| `VERIFY` | `manifest.verifyCommands` → repo `CLAUDE.md` "Full verification" / "Build & Test" command → `["npm run build", "npm test"]` only if `package.json` exists | — (see below) |
| `COOLDOWN` | `manifest.cooldownSeconds` | `540` |
| `REVIEWER` | `--reviewer` → `manifest.reviewer` → `manifest.finalReviewer` → ask | — |
| `GATES` | `manifest.gateAfter` | `[]` |

**Inferred values need confirmation.** If `VERIFY`, `EPIC` or `REVIEWER` came from
detection rather than the manifest or a flag, do **not** start the loop. Print the
resolved config and ask the user to confirm (or to write the value into the manifest).
A wrong verify command turns every task red, and a wrong `Closes` line closes an epic
on its first merge, so these are never guessed silently.

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
- The epic is closed by the driver in the Final review step.

Otherwise it is a **legacy single-issue** manifest: every task closes
`manifest.issue` and no `Part of` line is emitted. This is the original
behaviour — old manifests are unaffected.

## Ask reviewer if not provided

If `--reviewer` was absent and neither `manifest.reviewer` nor `manifest.finalReviewer`
is set, ask once — the answer is used for the single epic-level review, not per PR:

Which model should review the epic after its last merge?
- **Opus** — deepest review; checks frozen contracts, purity, determinism and test
  substance, and blocks the epic close on a violation. Use for engine, schema and
  contract work.
- **Sonnet** — thorough, good for ordinary feature changes
- **agy** — a separate read-only pass over the acceptance criteria

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

**Sequentiality:** exactly one Bash call may be in flight at a time. Never issue
task N+1's commands before task N reaches `merged`.

### Preflight (once per invocation)

- `git -C $REPO_PATH status --porcelain` is empty (else stop and report).
- Resolve the actual default/base branch and required work ticket first.
  Use the repository's required branch prefix and real ticket key.
- Check out that base and update with `git pull --ff-only` only within the
  authorized workspace; do not overwrite another session's branch or dirty files.
- `gh auth status` succeeds.
- Every file the task prompts tell agy to read exists (e.g. a design doc).
  A missing shared spec is a hard abort, not a warning.
- Run `VERIFY` on the clean resolved base and confirm green, so any later failure is
  unambiguously attributable to agy.
- Record `EPIC_BASE_SHA` = `git rev-parse HEAD` on that clean base. The epic-level
  review diffs the whole epic against it.

Then work through tasks in dependency order (respect `blockedBy`), skipping
`merged` and `skipped`. A `failed` task is **not** retried unless `--retry-failed`
was passed; without it, stop and report.

### a. Cool-down + sync base

One tracked Bash call, cool-down fused to the front. Use only permissions
available in the current harness; do not bypass its execution policy.

```bash
COOL=$(( COOLDOWN - ( $(date +%s) - PREV_AGY_EXIT_AT ) ))   # 0 on the first task
if [ $COOL -gt 0 ]; then
  echo "COOLDOWN START $(date +%s) ($(date)) — ${COOL}s"
  sleep $COOL
  echo "COOLDOWN END $(date +%s) ($(date))"
fi
cd <repoPath> && git checkout <base> && git pull --ff-only && git checkout -b <task.branch>
```

The cool-down runs from the moment the **previous agy process exited**
(`agyExitedAt`, recorded in step (b)), not from merge. The default of 540 s (9 min)
is a rest after every agy run, so requests per hour stay bounded. Verify, PR, CI and
merge time counts toward it: if those steps already took `COOLDOWN` seconds, no
extra wait is added. Set `cooldownSeconds: 0` in the manifest to turn it off.

Set `status: "running"`, increment `attempts`, write `startedAt` **before**
launching agy.

### b. Run agy

Use the harness's tracked background/wait mechanism and agy's own 30-minute
timeout. Keep the command handle; an initial tool wait ending is not a process
timeout and is not a reason to rerun the task.

```bash
mkdir -p "$PROMPT_DIR/logs"
set -o pipefail
agy --dangerously-skip-permissions --print-timeout 30m \
  -p "$(cat "$PROMPT_DIR/<task.promptFile>")" 2>&1 \
  | tee "$PROMPT_DIR/logs/<task.id>.agy.log"
```

Then read only `tail -60` of that log.

As soon as agy's process exits, write `agyExitedAt` (epoch seconds) to the task in the
manifest. The next task's cool-down in step (a) is measured from it.

### c. Output gate

`git diff --stat` and `git status --porcelain`. If nothing changed:
- Re-run agy once with this appended to the prompt:
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

On failure, hand the failing tail to a **Sonnet** fixer agent (this is mechanical;
it doesn't need Opus), max 2 attempts. Still failing → `status: "failed"`, halt.
Never open a PR that is known-red: an unattended loop that ships broken PRs
produces garbage.

### f. Commit

Use the git-commit skill with explicit paths and actual harness/model attribution.
Use `Part of` for an umbrella epic, and `Closes` only for the task's own issue.
Do not claim another model authored a commit.

### g. Push + PR

Use the pr-create skill and the current harness's supported PR-creation tool,
with the resolved base, task branch and repository draft policy.

Body: concise summary bullets from the acceptance criteria, then
`Closes #<TASK_ISSUE(t)>` and `Part of #<EPIC>`.

If authentication fails, report the blocker. Do not silently change the remote
URL, account or Git credential configuration.

Record `task.pr` and set `status: "pr_open"`, then **write the manifest
immediately** — this is the most important persistence point for resumability.

### h. Wait for CI + merge

Use the read-only pr-watch helper for the exact repository/PR, with a bounded
wait (for example, `--interval 30 --max-ticks 40`). A branch's mergeability
status alone does not prove checks passed.

- Confirmed passing checks and satisfied branch requirements (including any human
  review the repository requires) → use the scope-aware pr-merge skill. For work
  repositories, leave the PR awaiting human merge and stop dependent work. Record
  `merged` only after GitHub confirms it.
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
| agy no-op | empty `diff --stat` ×2 | `failed`, halt |
| agy timeout | worker's own timeout or tracked process result | keep partial work, verify acceptance and tests; otherwise fail |
| verify red | non-zero `VERIFY` command | Sonnet fixer ×2 → else `failed`, halt |
| out-of-scope files | `status --porcelain` vs `task.scope` | preserve files, halt and resolve ownership/scope |
| CI red | `statusCheckRollup` FAILURE | `ci-fix` ×1 → else `failed`, halt |
| merge conflict | `mergeStateStatus: DIRTY` | halt and request an approved recovery |
| epic review BLOCK | `VERDICT: BLOCK` after two fix rounds | leave the epic open, report, stop |
| **usage limit** | output matches `usage limit\|rate limit\|resets at\|429` | **not a failure** — parse the reset time, sleep until it + 120 s, do **not** increment `attempts`, retry the same task |
| lock held | `mkdir` fails, exit 9 | abort this invocation; another driver is live |

"Halt" always means: leave the branch and PR intact, write `lastError`, print a
resume line, stop. **Never skip a failed task and continue** — later tasks would
be built on a missing foundation.

Cap `attempts` at 3 per task.

## Resumability

Status widens to `pending → running → implemented → verified → pr_open → merged`,
plus terminal `failed` and `skipped`. The epic-level review tracks its own
`epicReview` field: `pending → reviewing → approved | blocked`. Write the manifest
after **every** transition — that file is the resume state.

Re-invoking reconciles against GitHub rather than trusting the file, because the
recorded status is a hint and GitHub is the truth:

1. Find the first task not `merged`/`skipped`. If there is none, the tasks are done:
   check `epicReview` and resume at the Final review unless it is already `approved`.
2. `gh pr list --head <task.branch> --state all --json number,state,mergedAt`:
   - merged PR → mark `merged`, move on
   - open PR → resume at step (h)
   - no PR but the remote branch exists → resume at step (e)
   - nothing → restart at step (a)
3. `failed` tasks need `--retry-failed` before `attempts` is reset — this stops an
   unattended loop burning three attempts on a structurally impossible task.

Worst-case loss from a crash is one agy run.

## Final review and epic close

Runs only after every task is `merged` (never after a halt). This is the epic's only
review — with no per-PR review, the verify and CI gates are the sole checks before a
task merges, and this review sees the whole epic afterwards. Set `epicReview` to
`reviewing` when it starts and to `approved` or `blocked` when it ends.

**1. Review the epic.** Spawn one agent of the `REVIEWER` type (`opus` → `model: opus`,
`sonnet` → `model: sonnet`, `agy` → a read-only `agy` pass), cwd `$REPO_PATH`, on the
clean resolved base after the last merge. It must check, in this order:

1. **Frozen-contract compliance**, if a task prompt names frozen files. Diff them
   against the pinned task base; any rename, retype, removal or narrowed optionality is
   **blocking**. Additive-only is the bar.
2. **Cross-task consistency** — duplicate helpers, conflicting prefs keys, strings or
   permissions added twice, a gate's contract changed later. Review
   `git log --oneline` for the epic's merged PRs and
   `git diff $EPIC_BASE_SHA...<final-base>`.
3. **Epic acceptance and design decisions** — walk the epic body and each task's
   `- [ ]` criteria, stating met / not-met / partial, **citing the file and line** that
   satisfies each. "Looks fine" is not acceptable.
4. **Purity and determinism**, if the tasks require them — grep for the forbidden
   constructs the prompts name, and require coverage for any determinism claim.
5. **Test substance** — no `.skip`/`.only`, no assertion-free tests, no snapshot added
   to paper over a failure, no loosened existing assertions.
6. **Re-run `VERIFY`** on that base and confirm exit 0.

It is read-only: report verified findings and evidence, and never edit, stage, commit
or push. Step 2 sends any approved fix through the implementation workflow. It ends
`VERDICT: APPROVE` or `VERDICT: BLOCK <reason>`, with each finding citing file and line.

**2. Apply the recommended fixes.** On `BLOCK` (or any recommended fix), implement the
fixes through the normal implementation workflow: one fix branch and PR, the same scope,
verify, commit, CI and merge gates as any task. In a work repo the fix PR still awaits
human merge — report it and stop rather than merging it yourself.

**3. Re-review with a fresh instance.** Once the fixes are merged, spawn a **new** agent
— a different instance of the same model as `REVIEWER`, never the one that proposed the
fixes — on the updated base. It repeats step 1 over the whole epic and ends
`VERDICT: APPROVE` or `VERDICT: BLOCK <reason>`. Cap this at two fix rounds; if it still
blocks, set `epicReview: "blocked"`, leave the epic open, report and stop. Merged PRs
stay merged; a block only stops the epic from closing.

**4. Close the epic.** On `APPROVE`, set `epicReview: "approved"`, and only if the epic
has no per-task issues: `gh issue close <EPIC> --comment "Done: <PR list>"`.

## Final report

A table: task → issue → PR → status → wall clock. Then the final review verdict, the
epic's state, and the resume command if anything is outstanding.

---
name: issue-ship
description: >-
  Implement one GitHub issue end to end on a fresh branch: an implementer writes the change, a
  reviewer checks it, a fixer applies findings, up to two fix rounds with a final review, then
  commit, PR, merge and an APK release when the user asks for them. The harness and model are
  chosen at every stage. Usage: /issue-ship [<owner/repo> <issue-number>]
allowed-tools: Bash, Read, Write, Agent, AskUserQuestion
argument-hint: "[<owner/repo> <issue-number>]"
---

One issue, one branch, one PR. Use `epic-run` for decomposed epics with several tasks. This skill
takes a single issue whose body is already a complete task spec.

Each stage runs one headless turn on a harness and model. The orchestrator (this session) only
gathers context, asks the questions, runs checks and reads log tails. It never pastes whole logs
into its own context.

## 0. Inputs and guardrails

- Resolve `<owner/repo>` and `<issue-number>` from `$ARGUMENTS`. If either is missing, ask.
- Working tree must be clean and on `main`. Stop if it is not; never stash or reset user work.
- Scratch dir: `$SCRATCH/<issue>/` with `logs/`, `issue.md`, `findings-<n>.md`, `summary.md`.
  Use the session scratchpad, not `/tmp`.
- Never touch `app/debug.keystore`, `applicationId`, `namespace`, or existing SharedPreferences keys.
- Helpers and implementers never commit, push or open PRs. The orchestrator does that.
- Exit code 3 from `run-harness.sh` means a permission denial. Treat it as a hard stop.

## 1. Discover models

Run:

```bash
~/.config/agent-context/scripts/list-models.sh all
```

Keep the output for the questions below. Do not hard-code model names in this skill.

## 2. Pick the harness and model for each stage

Before every stage, ask with AskUserQuestion. Options come from step 1. Offer the last choice as the
first option. Do this every round, including each fix and review round. Never reuse a previous
answer silently.

Stages that ask:

- `IMPLEMENT`: writes the change
- `REVIEW`: read-only check of the diff
- `FIX`: applies one round of findings

## 3. Branch and implement

```bash
git checkout -b <type>/<issue>-<short-slug> main
cp <issue body> "$SCRATCH/<issue>/issue.md"
```

Then run:

```bash
~/.config/agent-context/scripts/run-harness.sh <harness> <model> implement <repo-path> \
  "$SCRATCH/<issue>/issue.md" "$SCRATCH/<issue>/logs/implement-<n>.log"
```

Run it in the background and wait for the completion notification. Do not poll. Check the exit
code and read only the log tail.

If the harness is `agy` and the log says it is out of credits, stop and ask the user. Do not fall
back silently.

## 4. Verify

Run the full verify, in the background, and check the exit code:

```bash
JAVA_HOME=$(/usr/libexec/java_home -v 17) ./gradlew assembleDebug testDebugUnitTest --no-daemon
```

Check the exit code and grep the log for `FAILED`. A green build is required before review.

## 5. Review (read-only)

Ask for the reviewer (step 2). Then:

- Harness `claude`: use the Agent tool with the chosen model. It must not edit files.
- Any other harness: run `run-harness.sh <harness> <model> review ...` with a prompt that forbids
  edits.

The brief must be self-contained. Include:

- the issue's acceptance criteria
- the CLAUDE.md standing rules that apply
- the command to view the diff: `git diff main...HEAD`
- the output format: `CLEAN`, or numbered findings with file:line, BLOCKER or NIT, and a fix

If the verdict is `CLEAN`, skip to step 7. Write the findings to `findings-<n>.md`. NITs alone do
not require a fix round, but list them in the summary.

## 6. Fix rounds (max 2)

For each round:

1. Ask for the fixer (step 2).
2. Run `run-harness.sh <harness> <model> implement ...` with `findings-<n>.md` as the prompt. The
   prompt must say "fix these findings only; do not commit".
3. Re-run verify (step 4).
4. Re-run review (step 5) with a brief that also asks whether each prior finding is fixed.

After 2 fix rounds, if findings remain, stop and report to the user. Do not merge.

## 7. Commit

Stage explicit paths only. Use the `git-commit` skill for the message. Attribution: use the model
line that matches the model actually running this orchestration, and do not add a Claude-Session
trailer or claude.ai session link. Follow the repo's commit style (`type(scope): summary (#n)`).

## 8. Ship (only when the user asks)

Ship steps push, open a PR and merge. Run them only when the user has explicitly authorized them
for this issue. A review verdict of `CLEAN` alone is not authorization.

- Push the branch.
- Open the PR with `pr-create`. The body starts with `Closes #<n>`, summarizes the change and
  verification, and ends with the Generated-with line only.
- Merge with `pr-merge <pr-number>`. Relay its output. If it refuses, check the repo scope first.

## 9. Release APK (only when the user asks)

1. Find the latest build: `gh release list --limit 1`. Use `N = latest + 1`.
2. Run `GITHUB_RUN_NUMBER=<N> JAVA_HOME=$(/usr/libexec/java_home -v 17) ./gradlew assembleDebug
   testDebugUnitTest --no-daemon`.
3. Copy `app/build/outputs/apk/debug/thumbline-debug.apk` to `$SCRATCH/<issue>/thumbline.apk`.
4. `gh release create build-<N> <file> --target main --title build-<N> --generate-notes --latest`.

## 10. Report

Write `summary.md` in the scratch dir: the stages with harness and model, finding counts per round,
what each fix changed, and any stop. Then give the user a short report: the PR and release links,
what was verified, and what was not done.

Ask the user one question at the end: whether to make another issue run with the same pattern.

---
name: issue-ship
description: >-
  Implement one GitHub issue end to end on a fresh branch: an implementer writes the change, a
  reviewer checks it, a fixer applies findings, up to two fix rounds with a final review, then
  commit and, when the user opted in up front, push, PR and merge. Harness first, then model, are
  asked for each stage up front. Usage: /issue-ship
  [<owner/repo> <issue-number>]
allowed-tools: Bash, Read, Write, Agent, AskUserQuestion
argument-hint: "[<owner/repo> <issue-number>]"
---

One issue, one branch, one PR. Use `epic-run` for decomposed epics with several tasks. This skill
takes a single issue whose body is already a complete task spec.

Each stage runs one headless turn on a harness and model. The orchestrator (this session) only
gathers context, runs checks and reads log tails. It never pastes whole logs into its own context.

## 0. Inputs and guardrails

- Resolve `<owner/repo>` and `<issue-number>` from `$ARGUMENTS`. If either is missing, ask.
- Working tree must be clean and on `main`. Stop if it is not; never stash or reset user work.
- Scratch dir: `$SCRATCH/<issue>/` with `logs/`, `issue.md`, `findings-<n>.md`, `summary.md`.
  Use the session scratchpad, not `/tmp`.
- Never touch signing material, secrets, package/application identity, or user-data keys. Also
  follow the guardrails listed in the repo's instruction files (`AGENTS.md`, `CLAUDE.md`, ...).
- Helpers and implementers never commit, push or open PRs. The orchestrator does that.
- Exit code 3 from `run-harness.sh` means a permission denial. Treat it as a hard stop.

## 1. Discover models and fetch the issue

Run:

```bash
~/.config/agent-context/scripts/list-models.sh all
```

Keep the output for the question batch below. Do not hard-code model names in this skill.

Fetch the issue body. Show the user its title and acceptance criteria so they answer the batch
with context, and copy the body to `$SCRATCH/<issue>/issue.md`.

## 2. Upfront question batch (the only asks)

Ask everything now, before any stage runs. Do not ask again mid-run. Two AskUserQuestion calls,
back to back with no other work between them — AskUserQuestion fits at most 4 questions per call.

Ask with AskUserQuestion. Options come from step 1. Offer the last choice as the first option.

**First call — harness per stage.** One question each for:

- `IMPLEMENT`: writes the change
- `REVIEW`: read-only check of the diff
- `FIX`: applies one round of findings

Options are the harnesses that returned models in step 1 (`claude`, `opencode`, `agy`). Use the
fourth question for **Ship after CLEAN?** — push the branch, open a PR and merge once review is
clean. Yes/no, default no. A later request to ship must be explicit; a `CLEAN` verdict alone is
never authorization.

**Second call — model per stage**, using each stage's harness picked in the first call. One
question per stage, options only from that harness's lines in the step 1 output. AskUserQuestion
shows few options, so list the most relevant few (the user's last choice first) and treat a
free-typed model as valid only if it appears in the step 1 output for that harness. Use the fourth
question for the **Verify command**, and only when the repo's instruction files do not define one
(see step 4).

Later fix rounds and re-reviews reuse the round-1 choices silently. Never reuse an answer across
stages the user did not choose for; each stage keeps its own harness and model.

## 3. Branch and implement

```bash
git checkout -b <type>/<issue>-<short-slug> main
```

Record the branch name; the review brief must pass it explicitly.

Then run:

```bash
~/.config/agent-context/scripts/run-harness.sh <harness> <model> implement <repo-path> \
  "$SCRATCH/<issue>/issue.md" "$SCRATCH/<issue>/logs/implement-<n>.log"
```

Run it in the background and wait for the completion notification. Do not poll. Check the exit
code and read only the log tail.

On harness failure (non-zero exit, permission denial, or an `agy` out-of-credits message), stop
and ask again with AskUserQuestion — harness first, then a model from that harness's step 1
output — offering the stages that had not run yet. The new choice applies to the remaining
stages. Never fall back silently.

## 4. Verify

The verify command comes from the repo — never from this skill. Look for it in the repo's
instruction files (`AGENTS.md`, `CLAUDE.md`, CONTRIBUTING, Makefile targets, package scripts).
If the repo defines none, use the verify command from the upfront batch.

Run it in the background and check the exit code. Grep the log for failures. A green verify is
required before review.

## 5. Review (read-only)

Use the `REVIEW` harness and model from the batch.

- Harness `claude`: use the Agent tool with the chosen model. It must not edit files.
- Any other harness: run `run-harness.sh <harness> <model> review ...` with a prompt that forbids
  edits.

The brief must be self-contained. Include:

- the issue's acceptance criteria
- the standing rules from the repo's instruction files that apply
- the branch name and the command to view the diff: `git diff main...HEAD`
- the output format: `CLEAN`, or numbered findings with file:line, BLOCKER or NIT, and a fix

If the verdict is `CLEAN`, skip to step 7. Write the findings to `findings-<n>.md`. NITs alone do
not require a fix round, but list them in the summary.

## 6. Fix rounds (max 2)

For each round:

1. Run `run-harness.sh` with the `FIX` harness and model from the batch, with `findings-<n>.md`
   as the prompt. The prompt must say "fix these findings only; do not commit".
2. Re-run verify (step 4).
3. Re-run review (step 5) with a brief that also asks whether each prior finding is fixed.

After 2 fix rounds, if findings remain, stop and report to the user. Do not merge.

## 7. Commit

Stage explicit paths only. Use the `git-commit` skill for the message. Attribution: use the model
line that matches the model actually running this orchestration, and do not add a Claude-Session
trailer or claude.ai session link. Follow the repo's commit style — derive it from recent
`git log` entries or the repo's CONTRIBUTING, do not guess.

## 8. Ship (only if opted in up front)

Only when the user answered yes to "Ship after CLEAN?" in the upfront batch, or explicitly asks
afterwards. A review verdict of `CLEAN` alone is not authorization.

- Push the branch.
- Open the PR with `pr-create`. The body starts with `Closes #<n>`, summarizes the change and
  verification, and ends with the Generated-with line only.
- Merge with `pr-merge <pr-number>`. Relay its output. If it refuses, check the repo scope first.

## 9. Report

Write `summary.md` in the scratch dir: the stages with harness and model, finding counts per
round, what each fix changed, and any stop. Then give the user a short report: the PR link (if
shipped), what was verified, and what was not done.

Ask the user one question at the end: whether to make another issue run with the same pattern.

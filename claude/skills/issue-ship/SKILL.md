---
name: issue-ship
description: >-
  Implement one GitHub issue end to end on a fresh branch: an implementer writes the change, a
  reviewer checks it, a fixer applies findings, up to two fix rounds with a final review, then
  commit and, when the user opted in up front, push, PR and merge. Harness and model per stage
  are asked up front, or passed as arguments for unattended runs (--headless).
  Usage: /issue-ship [<owner/repo> <issue-number>]
  [IMPLEMENT=<h:m> REVIEW=<h:m> FIX=<h:m> SHIP=yes|no]
  [--headless] [--fallback=<h:m>] [--escalate=<h:m>] [--on-findings=stop|merge-with-followup]
  [--brief <file>]
allowed-tools: Bash, Read, Write, Agent, AskUserQuestion
argument-hint: "[<owner/repo> <issue-number>] [IMPLEMENT=<h:m> REVIEW=<h:m> FIX=<h:m> SHIP=yes|no] [--headless] [--fallback=<h:m>] [--escalate=<h:m>] [--on-findings=stop|merge-with-followup] [--brief <file>]"
---

One issue, one branch, one PR. Use `epic-run` for decomposed epics with several tasks. This skill
takes a single issue whose body is already a complete task spec.

Each stage runs one headless turn on a harness and model. The orchestrator (this session) only
gathers context, runs checks and reads log tails. It never pastes whole logs into its own context.

## 0. Inputs and guardrails

- Resolve `<owner/repo>` and `<issue-number>` from `$ARGUMENTS`. If either is missing, ask —
  under `--headless`, stop instead.
- Working tree must be clean and on `main`. Stop if it is not; never stash or reset user work.
- Scratch dir: `$SCRATCH/<issue>/` with `logs/`, `issue.md`, `findings-<n>.md`, `summary.md`.
  Use the session scratchpad, not `/tmp`.
- Never touch signing material, secrets, package/application identity, or user-data keys. Also
  follow the guardrails listed in the repo's instruction files (`AGENTS.md`, `CLAUDE.md`, ...).
- Helpers and implementers never commit, push or open PRs. The orchestrator does that.
- Exit code 3 from `run-harness.sh` means a permission denial. Treat it as a hard stop.

## 0.5 Headless and unattended runs

All flags below are optional. With none of them, the skill behaves exactly as before:
interactive, asks the batch, runs harness calls in the background.

- `IMPLEMENT=<harness>:<model> REVIEW=<h:m> FIX=<h:m> SHIP=yes|no` pre-answer the
  upfront batch; ask only for answers that are missing. `SHIP=yes` is the explicit
  ship opt-in; without it, never ship.
- `--headless`: nobody can answer questions. Requires all four batch answers via
  arguments — if any is missing, stop and name it. Never call AskUserQuestion. Run
  every harness call and the verify command in the **foreground**: this session may be
  a one-shot headless turn that ends when the turn ends, abandoning background jobs.
  Where the skill would stop to ask, take the conservative option that keeps the build
  green and stays inside the issue's scope, and note it in the summary.
- `--fallback=<h:m>`: on harness failure (non-zero exit, permission denial,
  out-of-credits), retry that stage once with the fallback. If it fails again, ask as
  today — or, under `--headless`, stop with status `FAILED`.
- `--escalate=<h:m>`: when 2 normal fix rounds leave findings or verify red, run up to
  2 escalation rounds with this model as fixer and re-reviewer. Fix only; no scope
  beyond the acceptance criteria; re-run verify each round.
- `--on-findings=stop|merge-with-followup` (default `stop`): what to do when findings
  remain after the (escalation) rounds but verify is green. `merge-with-followup`
  commits, pushes, opens the PR with the findings listed under "Known issues" in the
  body, merges, and files one follow-up issue `Follow-up: <issue title>` linking the
  PR. Verify still red is never merged in any mode: push the branch and report.
- `--brief <file>`: append the file's contents to the implement prompt and to every
  review brief (per-task extras from an orchestrator).

**Result contract.** Always — interactive or headless — write
`$SCRATCH/<issue>/result.json` before the final report and print its path:

```json
{"status": "CLEAN | MERGED | MERGED_WITH_KNOWN_ISSUES | STOPPED | FAILED",
 "pr": "<url or empty>", "followUp": "<url or empty>",
 "branch": "<branch>", "notes": "<at most 5 lines: rounds, escalation, decisions, failure reason>"}
```

`CLEAN` = review clean, not shipped. `STOPPED` = findings left with
`--on-findings=stop`, or verify red after escalation. An orchestrator parses this
file; keep the keys exact.

## 1. Discover models and fetch the issue

Run:

```bash
~/.config/agent-context/scripts/list-models.sh all
```

Keep the output for the question batch below. Do not hard-code model names in this skill.

Fetch the issue body. Show the user its title and acceptance criteria so they answer the batch
with context, and copy the body to `$SCRATCH/<issue>/issue.md`.

## 2. Upfront question batch (the only asks)

Skip whatever the arguments already answered (`IMPLEMENT=`, `REVIEW=`, `FIX=`, `SHIP=`);
under `--headless`, skip this step entirely — all four answers must have come from
arguments. Ask everything remaining now, before any stage runs. Do not ask again mid-run.
Two AskUserQuestion calls, back to back with no other work between them — AskUserQuestion
fits at most 4 questions per call.

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

Run it in the background and wait for the completion notification (foreground under
`--headless`). Do not poll. Check the exit code and read only the log tail.

On harness failure (non-zero exit, permission denial, or an `agy` out-of-credits message):
with `--fallback`, retry this stage once with the fallback model first. Otherwise, or when
the fallback also fails, stop and ask again with AskUserQuestion — harness first, then a
model from that harness's step 1 output — offering the stages that had not run yet. The
new choice applies to the remaining stages. Never fall back silently. Under `--headless`,
never ask: a failed fallback means stop with status `FAILED`.

## 4. Verify

The verify command comes from the repo — never from this skill. Look for it in the repo's
instruction files (`AGENTS.md`, `CLAUDE.md`, CONTRIBUTING, Makefile targets, package scripts).
If the repo defines none, use the verify command from the upfront batch.

Run it in the background (foreground under `--headless`) and check the exit code. Grep the
log for failures. A green verify is required before review.

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

After 2 fix rounds, if findings remain: with `--escalate=<h:m>`, run up to 2 escalation
rounds with that model as fixer and re-reviewer (fix only; no scope beyond the acceptance
criteria; re-run verify each round). Still findings afterwards → follow `--on-findings`
(default `stop`: stop and report to the user; `merge-with-followup` ships with the findings
listed under "Known issues" in the PR body and files one follow-up issue). Verify still red
is never merged in any mode: push the branch and report.

## 7. Commit

Stage explicit paths only. Use the `git-commit` skill for the message. Attribution: use the model
line that matches the model actually running this orchestration, and do not add a Claude-Session
trailer or claude.ai session link. Follow the repo's commit style — derive it from recent
`git log` entries or the repo's CONTRIBUTING, do not guess.

## 8. Ship (only if opted in up front)

Only when the user answered yes to "Ship after CLEAN?" in the upfront batch (`SHIP=yes` on
the command line is that answer), when `--on-findings=merge-with-followup` covers the
known-issues path, or when the user explicitly asks afterwards. A review verdict of `CLEAN`
alone is not authorization.

- Push the branch.
- Open the PR with `pr-create`. The body starts with `Closes #<n>`, summarizes the change and
  verification, and ends with the Generated-with line only.
- Merge with `pr-merge <pr-number>`. Relay its output. If it refuses, check the repo scope first.

## 9. Report

Write `summary.md` in the scratch dir: the stages with harness and model, finding counts per
round, what each fix changed, and any stop. Write `$SCRATCH/<issue>/result.json` per the
result contract in step 0.5 and print its path. Then give the user a short report: the PR
link (if shipped), what was verified, and what was not done.

Ask the user one question at the end: whether to make another issue run with the same
pattern. Never ask this under `--headless`.

---
name: epic-review
description: >-
  Review a whole decomposed epic after its last merge with a chosen reviewer model. The reviewer
  fixes issues directly in a disposable worktree; the review repeats with a fresh reviewer each
  round until a round changes nothing and verify passes, up to 5 rounds. Called by epic-drive;
  can run on its own for a finished epic.
  Usage: /epic-review <owner/repo> <issue-number> REVIEWER=<harness>:<model>
allowed-tools: Bash, Read, Write, Agent
argument-hint: "<owner/repo> <issue-number> REVIEWER=<harness>:<model>"
---

The epic's only review. It runs after every task is `merged`, never after a halt. There is no
per-PR review: the verify and CI gates are the only checks before a task merges, and this review
sees the whole epic afterwards.

The reviewer is not read-only. It fixes what it finds, directly, and reports every change it made.
The driver then verifies, and if anything changed it publishes the changes as a PR and starts another
round with a new reviewer. The review ends when a round changes nothing.

## Inputs

- `PROMPT_DIR` = `${AGY_PROMPTS_DIR:-$HOME/.claude/agy-prompts}/<slug>`, where `<slug>` is
  owner + "-" + repo + "-issue-" + issue number. Read `manifest.json` from it.
- `REVIEWER` = `<harness>:<model>`, one of `claude:<alias or id>`, `opencode:<provider/model>` or
  `agy:<model id>`. When called from `epic-run` or `epic-drive` it is already resolved. Ask once only
  if it is not provided and the manifest has no `reviewer`.
- `REPO_PATH`, `VERIFY` and `EPIC_BASE_SHA` are resolved exactly as `epic-drive` resolves them
  ("Resolve config"), not invented here:
  - `REPO_PATH` = `manifest.repoPath`. Required; stop if it is null.
  - `VERIFY` = `manifest.verifyCommands`, else the repo `CLAUDE.md` "Full verification" / "Build & Test",
    else `["npm run build", "npm test"]` when `package.json` exists. When called by `epic-drive` it passes
    the values it already confirmed; use those. When run on its own and `VERIFY` was inferred, print it and
    ask the user to confirm before running.
  - `EPIC_BASE_SHA` = `manifest.epicBaseSha`, written by `epic-drive` preflight. If it is missing, stop:
    the epic was not driven by `epic-drive`, and a whole-epic diff has no anchor.
- The base branch is the one `epic-drive` resolved (`manifest.baseBranch`, else the repo's default branch).

Set `epicReview` to `reviewing` when it starts. End as `approved` or `blocked`. Record `reviewRound` in the
manifest after each round so a resume continues at the right round.

## One round

Repeat for `round` = 1, 2, ... up to 5.

1. **Sync.** `git -C $REPO_PATH fetch` and fast-forward the base. Let `FINAL_BASE_SHA` =
   `git -C $REPO_PATH rev-parse <base>` after the last merge (and after any earlier round's fix PR merged).
2. **Disposable worktree.** Create it outside the repo so a review cannot leave stray files in the main
   checkout:

   ```bash
   TMP=$(mktemp -d "${TMPDIR:-/tmp}/epic-review-$SLUG-r$round.XXXXXX")
   git -C "$REPO_PATH" worktree add --detach "$TMP" "$FINAL_BASE_SHA"
   ```

   The worktree shares the repo's git history, so the reviewer can see the base commit's full history
   with `git log`, not only the diff.
3. **Write the prompt.** The driver writes `$PROMPT_DIR/review-<round>.prompt.md` before calling
   `run-harness.sh` (or before spawning a subagent, which gets the same text). It must say:
   - the working directory is `$TMP`, the epic is `<owner/repo>#<EPIC>`, the base is `FINAL_BASE_SHA` and
     the epic started at `EPIC_BASE_SHA`;
   - review the **whole epic**, not the last PR, using the checklist below;
   - cite `file:line` for every finding and for every acceptance criterion ("looks fine" is not acceptable);
   - fix what you find directly in `$TMP`; do not `git add`, `git commit`, `git push` or open PRs;
   - **report every edit you make**, with file and line and why, in a "Changes" section; if you changed
     nothing, say "Changes: none";
   - re-run the `VERIFY` commands (listed in the prompt, in order) after your edits;
   - end with exactly one final line, `VERDICT: APPROVE` or `VERDICT: BLOCK <reason>`.
4. **Run a fresh reviewer.** A new instance every round, never the previous one:
   - **Same harness as this session:** a subagent with that model (in Claude Code, `Agent` with `model:`),
     told to work in `$TMP` with absolute paths. Ask for a summary of at most 60 lines.
   - **Any other harness:**

     ```bash
     mkdir -p "$PROMPT_DIR/logs"
     ~/.config/agent-context/scripts/run-harness.sh <harness> <model> review \
       "$TMP" "$PROMPT_DIR/review-<round>.prompt.md" "$PROMPT_DIR/logs/review-<round>.<harness>.log"
     ```

     Exit code 3 means the log shows a permission denial: treat the round as failed, not as a verdict.
     Read only `grep "VERDICT:"` and the last 60 lines of the log; the full log stays on disk.
5. **Record what changed.** `git -C "$TMP" status --porcelain` lists the files the reviewer changed (it is
   expected to be non-empty when the reviewer fixed something). Compare against the reviewer's "Changes"
   section; an edit that is not reported is a finding against the reviewer, note it in the report.
6. **Verify.** Run each `VERIFY` entry from `$TMP`, in order, stopping at the first non-zero exit. This is the
   driver's own run, independent of the reviewer's claim.
7. **Decide.**
   - Files changed: commit them on a branch `review/<slug>-r<round>` from `$TMP` (git-commit skill, explicit
     paths, actual harness and model attribution), push, and open a PR through the same publish, CI and merge
     gates as an `epic-drive` task (pr-create, pr-watch, then pr-merge). Verify must be green before the
     PR is opened; if it is red, the round fails: set `epicReview: "blocked"` and report. In a work repo, leave
     the PR for human merge, record it as `reviewPr`, leave `epicReview: "reviewing"`, print the resume line
     and stop. After the merge, re-running `/epic-review` starts the next round. Personal repos merge and
     continue with a new round.
   - No files changed and verify passes and the verdict is `APPROVE`: the epic is approved. Stop the loop.
   - No files changed but verify fails or the verdict is `BLOCK`: nothing can converge by itself. Set
     `epicReview: "blocked"`, report the reasons, stop.
8. **Remove the worktree** after the round, whatever happened: `git -C "$REPO_PATH" worktree remove --force "$TMP"`.
   Delete the branch only if it was never pushed.

A round that made changes always leads to another fresh round. The loop stops only when a round makes no
file changes and verify passes. If round 5 still changed files, or never reached that state, set
`epicReview: "blocked"`, leave the epic open, report and stop. Merged PRs stay merged. A block only stops
the epic from closing.

## What the reviewer checks, in order

1. **Frozen-contract compliance**, if a task prompt names frozen files. Diff them against the pinned task
   base. Any rename, retype, removal or narrowed optionality is a defect. Additive-only is the bar.
2. **Cross-task consistency**: duplicate helpers, conflicting prefs keys, strings or permissions added
   twice, a gate's contract changed later. Use `git log --oneline` for the epic's merged PRs and
   `git diff $EPIC_BASE_SHA...<final-base>`.
3. **Epic acceptance and design decisions.** Walk the epic body and each task's `- [ ]` criteria, stating met,
   not met or partial, citing the file and line for each.
4. **Purity and determinism**, if the tasks require them. Grep for the forbidden constructs the prompts name,
   and require coverage for any determinism claim.
5. **Test substance**: no `.skip` or `.only`, no assertion-free tests, no snapshot added to paper over a
   failure, no loosened existing assertions.
6. **Re-run `VERIFY`** and confirm exit 0.

A headless run can exit 0 after a tool was denied; `run-harness.sh` scans the log and exits 3 when it finds
a denial. For a same-harness subagent, read its report for the same signal and treat a missing verdict as
a failed round.

## Close the epic

On approval, set `epicReview: "approved"`. If the epic has no per-task issues, run
`gh issue close <EPIC> --comment "Done: <PR list>"`. With per-task issues, the epic closes through its tasks.

## Report

The verdict, the reviewer used, the rounds used out of 5, and for each round: files the reviewer changed (with
file and line from its report), the review PR and its state, and the verify result.

---
name: epic-review
description: >-
  Review a whole decomposed epic once, after its last merge, with a chosen reviewer model,
  then apply recommended fixes through the normal task gates and re-review with a fresh
  instance, up to 5 fix rounds. Called by epic-drive; can run on its own for a finished epic.
  Usage: /epic-review <owner/repo> <issue-number> REVIEWER=<harness>:<model>
allowed-tools: Bash, Read, Write, Agent
argument-hint: "<owner/repo> <issue-number> REVIEWER=<harness>:<model>"
---

The epic's only review. It runs after every task is `merged`, never after a halt. There is no
per-PR review: the verify and CI gates are the only checks before a task merges, and this review
sees the whole epic afterwards.

Reviews are read-only. Fixes go back through the normal task workflow, `epic-drive`'s gates, and
a human merges them in work repos.

## Inputs

- `PROMPT_DIR` = `${AGY_PROMPTS_DIR:-$HOME/.claude/agy-prompts}/<slug>`, where `<slug>` is
  owner + "-" + repo + "-issue-" + issue number. Read `manifest.json` from it.
- `REVIEWER` = `<harness>:<model>`, one of `claude:<alias or id>`, `opencode:<provider/model>` or
  `agy:<model id>`. Ask once only if it is not provided and the manifest has no `reviewer`.
- `EPIC_BASE_SHA` from the manifest, recorded by `epic-drive` preflight.

Set `epicReview` to `reviewing` when it starts. End as `approved` or `blocked`.

## Run the review

Spawn one reviewer of the chosen harness and model, cwd `$REPO_PATH`, on the clean resolved base
after the last merge:

- **Same harness as this session:** a subagent with that model. In Claude Code, `Agent` with `model:`.
- **Any other harness:**

  ```bash
  ~/.config/agent-context/scripts/run-harness.sh <harness> <model> review \
    "$REPO_PATH" "$PROMPT_DIR/review-<round>.prompt.md" "$PROMPT_DIR/logs/review-<round>.<harness>.log"
  ```

The reviewer must check, in this order:

1. **Frozen-contract compliance**, if a task prompt names frozen files. Diff them against the pinned
   task base. Any rename, retype, removal or narrowed optionality is blocking. Additive-only is the bar.
2. **Cross-task consistency**: duplicate helpers, conflicting prefs keys, strings or permissions added
   twice, a gate's contract changed later. Use `git log --oneline` for the epic's merged PRs and
   `git diff $EPIC_BASE_SHA...<final-base>`.
3. **Epic acceptance and design decisions.** Walk the epic body and each task's `- [ ]` criteria, stating
   met, not met or partial, **citing the file and line** for each. "Looks fine" is not acceptable.
4. **Purity and determinism**, if the tasks require them. Grep for the forbidden constructs the prompts
   name, and require coverage for any determinism claim.
5. **Test substance**: no `.skip` or `.only`, no assertion-free tests, no snapshot added to paper over a
   failure, no loosened existing assertions.
6. **Re-run `VERIFY`** on that base and confirm exit 0.

The reviewer is read-only. It reports verified findings and evidence, and never edits, stages, commits or
pushes. Check it afterwards: `git -C $REPO_PATH status --porcelain` must be empty. If it is not, the reviewer
changed the tree. Stop, preserve the changes, and report them; do not discard them.

Keep the review out of the main context. For a headless reviewer, read only `grep "VERDICT:"` on its
log and the last 60 lines for the findings. The full log stays on disk. For a same-harness subagent,
ask it for a findings summary of at most 60 lines.

A headless run can exit 0 after a tool was denied. Check the log for denial messages (for example
"auto-denied" or "permission") before trusting a verdict, and treat a verdict as missing if the log has none. It ends with exactly one of `VERDICT: APPROVE` or `VERDICT: BLOCK <reason>`, and each finding cites
file and line.

## Apply fixes

On `BLOCK`, or on any recommended fix, implement the fixes through the normal task workflow: one fix branch
and PR, the same scope, verify, commit, CI and merge gates as any task. In a work repo the fix PR awaits
human merge. Report it and stop.

## Re-review

Once the fixes merge, spawn a **new** reviewer instance (a fresh subagent, or a fresh headless call), never the
one that proposed the fixes. It repeats the full review on the updated base.

Cap at **5 fix rounds**. If it still blocks after round 5, set `epicReview: "blocked"`, leave the epic open,
report and stop. Merged PRs stay merged. A block only stops the epic from closing.

## Close the epic

On `APPROVE`, set `epicReview: "approved"`. If the epic has no per-task issues, run
`gh issue close <EPIC> --comment "Done: <PR list>"`. With per-task issues, the epic closes through its tasks.

## Report

The verdict, the reviewer used, each finding with file and line, each fix PR and its state, and the rounds
used out of 5.

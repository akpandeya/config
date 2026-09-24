---
description: Full coding-task pipeline — Jira context -> Kimi plan -> implement -> Kimi review. Usage /ticket TGH-1234 [extra notes], or /ticket <task description> for non-Jira work.
---

# Ticket pipeline

$ARGUMENTS

Follow these phases in order. You are the orchestrator: you gather context, delegate planning and review, and do the coding yourself.

## Phase 0 — Context

- If the input contains a Jira key (pattern like `TGH-1234`):
  1. Run `jira issue view <KEY>`. If it is not assigned to me, STOP and ask whether to reassign; reassign only after I confirm (`jira issue assign <KEY> $(jira me)`).
  2. Per global rules move it through the board to `In Progress` (Backlog -> To Do -> In Progress) — ask before moving unless I already told you to pick it up.
  3. Pull description, acceptance criteria, and comments into the working context, verbatim where relevant.
- If the input is a plain task description, use it directly.
- Explore the codebase enough to know the affected areas, existing patterns, and test setup.

## Phase 1 — Plan (Kimi)

- Delegate to @planner, handing over EVERYTHING: full ticket context (description, acceptance criteria, relevant comments), your codebase findings, constraints, and the exact task. Do not paraphrase away details — the plan is only as good as what you pass.
- When the plan returns, summarize it in 3-5 bullets so I can see the shape of it, then CONTINUE IMMEDIATELY to Phase 2 without waiting for approval.

## Phase 2 — Implement (you, the coder)

- Implement the plan step by step, following repo conventions.
- If you discover the plan is wrong or incomplete, note the deviation explicitly in your final report and adjust — never silently skip or wing a step.
- Run lint / typecheck / tests if the repo has them. Fix what fails.

## Phase 3 — Review (Kimi)

- Delegate to @reviewer with: the original task, the list of changed files, and the diff (`git diff`).
- Fix every blocker and should-fix finding, then run @reviewer once more on the updated diff. Stop after that second pass — report anything still open instead of looping.

## Phase 4 — Wrap up

- Report: what changed (file list), verification results, review verdict, and any plan deviations or open findings.
- DEFAULT: always finish with a draft PR unless I explicitly say not to. If I did not ask otherwise, do the following without asking again:
  1. Create a feature branch if not already on one.
  2. Commit using the git-commit skill conventions.
  3. Push and open a DRAFT PR using the pr-create skill (link the Jira key in the body if there is one).
  4. Run the deep-review skill against the draft PR, apply its findings, and push any fixes to the same PR.
  5. Report the PR URL and the deep-review outcome.
- Never mark the PR ready-for-review — draft only, until I say so.
- Never post replies to PR review comments (see global rules).

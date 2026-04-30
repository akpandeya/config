---
name: ci-fix
description: Try to fix the failing CI checks on a PR. Reproduce locally, apply minimal fix, commit + push.
allowed-tools: Agent
---

The user is asking you to fix CI on a specific PR. Extract the PR
number from their message; if absent, ask.

Delegate immediately to the `ci-fixer` subagent. Do NOT attempt the
fix in the main session — the subagent has the right tools, permission
boundaries, and a tight token budget.

`Agent(subagent_type="ci-fixer", prompt="Fix CI on PR #<n>. Log path:
~/.jarvis/logs/pr-wait-<n>.log (if present). Investigate, reproduce,
apply minimal fix, commit with fix(ci): prefix, push. If the failure
is not actionable (bot asking a design question, flaky), reply on the
PR with one short sentence and exit.")`

When the subagent returns, surface the fix commit SHA (if any) or its
one-line verdict to the user. Nothing more.

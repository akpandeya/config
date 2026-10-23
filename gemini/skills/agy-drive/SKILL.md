---
name: agy-drive
description: >-
  Execute a decomposed issue with agy using the shared safe driver workflow,
  repository-specific verification and explicit merge policy.
  Usage: agy-drive <owner/repo> <issue-number> [--reviewer=agy]
---

Read `~/code/personal/config/claude/skills/agy-drive/SKILL.md` as the shared
driver procedure; do not recursively invoke the skill. Use
`~/.gemini/agy-prompts/<owner>-<repo>-issue-<number>/` as `PROMPT_DIR` instead
of the Claude path. If the shared procedure is missing, report the installation
problem rather than guessing a stale workflow.

Use the tools actually supported by this harness. Do not invent Claude `Agent`
calls, background parameters or model names. An explicit reviewer choice wins;
otherwise ask once before starting the driver.

The shared gates apply without exception: a clean owned workspace, real base
branch and work ticket, dependency-aware tasks, relevant verification, pinned
scope, explicit-path commits, and repository-specific PR/merge policy. A failing
task blocks its dependents. A failed build or timeout is not a reason to create
a success-shaped report or merge. Never silently discard files or amend and
force-push. Work PRs await human merge.

Keep status reports short and plain. Reserve diagrams and local HTML for a
substantial explanation or final review, not every task transition.

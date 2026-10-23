---
name: jules-drive
description: >-
  Execute a decomposed issue using Jules, with verified patches, dependency-aware
  stopping and the shared repository publication policy.
  Usage: /jules-drive <owner/repo> <issue-number> [--reviewer=sonnet|agy]
allowed-tools: Bash, Read, Write, Agent
argument-hint: "<owner/repo> <issue-number> [--reviewer=sonnet|agy]"
---

Read `~/.claude/skills/agy-drive/SKILL.md` as the shared driver procedure,
without invoking agy. It owns manifest handling, exact repository/base selection,
work-ticket requirements, scope gates, verification, publication, review and
resuming. Use the same Claude prompt-directory convention. Keep orchestration
in the main session rather than spawning another orchestrator.

Replace only the implementation step with Jules:

1. Confirm the requested repository is authorized for this remote service.
   Do not transmit private code to an unapproved destination.
2. Submit the task with `jules remote new --repo <repo>` using its prompt file.
   Preserve the repository's verification requirements. Tell the worker to
   implement and verify, not to open or merge a PR; the driver owns publication.
   Do not ban dependencies or end-to-end tests irrespective of the actual task.
3. Validate the returned session ID and record it before polling. Poll through
   a bounded harness-tracked command, not an unbounded loop. Failed, paused,
   missing or feedback-required sessions stop the task; do not mark them skipped
   and continue into dependents.
4. Retrieve the resulting patch and inspect every path before applying it to
   the intended task branch. Do not silently filter it to remembered
   frontend/backend directories, suppress `git apply` errors, delete files by
   extension or restore dependency files from another branch.
5. If Jules has already created a PR despite the instruction, inspect its exact
   repository, branch and contents and reconcile it with the manifest instead
   of creating a duplicate. Never assume its state proves verification.
6. An empty patch is complete only if the acceptance criteria are demonstrably
   already satisfied. Otherwise record a failure and stop dependent tasks.
7. Run the shared output, scope and verification gates, then publish through
   the git-commit and pr-create skills. Use actual tooling attribution.

Review is read-only; the implementer fixes confirmed findings in a new commit.
Never amend/force-push as a routine review step. Only confirmed passing checks
and satisfied repository policy can advance publication. Use pr-merge for an
authorized personal merge; work PRs remain open for a human.

Report task, issue, PR and actual state in a compact table. Say what is blocked
and how to resume; do not claim a task merged because a polling loop ended.

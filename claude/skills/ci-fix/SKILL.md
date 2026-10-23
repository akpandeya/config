---
name: ci-fix
description: Fix failing CI on a specified PR with a minimal change. Use when the user requests a CI fix or an explicitly authorized workflow includes repair; watching a PR alone does not trigger repair.
allowed-tools: Agent, Bash, Read
---

Resolve the repository and PR, not just a number that can collide across repos.
Use the configured `ci-fixer` agent when available, with the exact target, any
observer log path, the failure and the authorized scope. If the harness has no
custom agent support, perform the same bounded procedure directly.

Pass this contract: investigate current checks, reproduce, make a minimal fix and
verify. Commit and push only if that publication is explicitly authorized by the
user or enclosing workflow. Do not assume permission from an observer invocation.
One fix attempt per invocation; surface non-mechanical failures rather than
refactoring unrelated code. Draft replies to design questions for the user;
never post them or promise future work on the user's behalf.

Report the outcome plainly, including a commit only if one was actually created
and a push only if it succeeded. If a fix remains local, say so.

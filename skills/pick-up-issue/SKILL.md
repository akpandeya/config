---
name: pick-up-issue
description: Route a ticket or issue request — "work on PROJ-123", "fix gh issue #45", "pick up TGH-78", "implement that story". Fetches the ticket via jira/gh, judges whether the body is a complete task spec, then either implements it directly or routes to the decomposition pipeline. Do not use for vague feature requests with no ticket number.
---

You are the entry point for ticket-driven work. Resolve the ticket, judge its
shape, then route. This skill only routes and gathers context; implementation
and publishing are authorized by the user's explicit request or workflow, not
by this skill alone.

## 1. Resolve the ticket

Detect the profile from the repository, not from guesswork:

```bash
~/.config/agent-context/scripts/repo-scope-for-cwd.sh
```

- `personal` → the ticket is a GitHub issue number; read it with
  `gh issue view <n> --comments`.
- `work` → the ticket is a Jira key (e.g. `PROJ-123`); read it with
  `jira issue view <KEY>` (summary and acceptance criteria).

If no ticket number/key was given, ask for it before continuing. Never guess
an issue number from a bare "fix that issue".

## 2. Read and judge

Read the body **and** the comments. If the ticket looks stale, duplicate, or
out of scope for this repo: stop, surface it, and ask whether to close, skip
or rescope. Do not proceed silently.

Then classify the work:

- **Complete task spec** — clear goal, acceptance criteria, one coherent
  change a single PR can carry → run the single-issue flow yourself (§3).
- **Epic-sized** — several independently shippable tasks, or the body already
  carries a decomposition spec → route to the pipeline (§4).
- **Not actionable** — missing acceptance criteria, contradictory asks → ask
  one focused clarifying question at a time; skip questions the code already
  answers.

## 3. Single-issue flow (complete spec)

1. Branch from a fresh default branch (detect it; never hardcode `main`).
   Personal repos: `feat/`, `fix/`, `chore/` prefixes. Work repos:
   `feature/<KEY>-<slug>` or `patch/<KEY>-<slug>`. Create/confirm the real
   ticket before branching when the repository requires one.
2. Implement with the project's lint/format/test conventions; all checks
   green before any PR.
3. Open the PR with the `pr-create` skill (`Closes #<n>` for personal issues,
   the Jira key for work tickets). Commits go through the `git-commit` skill.
4. Watch CI in-session with `gh pr checks <n> --watch`. Scoped fix
   commits/pushes for this PR are authorized only when the user asked for an
   end-to-end run; otherwise stop at "PR open" and report.
5. Merge only via the `pr-merge` skill on personal repos; work-repo merges
   belong to a human.

## 4. Pipeline flow (epic-sized)

Hand off to the epic pipeline instead of implementing inline:

- `/issue-decompose` files the plan of record (native sub-issues + manifest).
- `/epic-drive` implements task-by-task with per-task PRs and gates.
- `/epic-review` reviews the whole epic after its last merge.
- `/epic-run` chains all three.

State the routing decision in one line ("epic-sized → /issue-decompose") and
wait for the user to confirm before the pipeline starts publishing anything.
Invoke the pipeline skills as the running harness expects: Claude Code
`/issue-decompose`, pi `/skill:issue-decompose` (or just ask the assistant to
load the skill by name).

## Hard rules

- Never push directly to the default branch.
- A decision ping or status report never authorizes scope expansion.
- Work repos: never post replies to human PR comments — draft them for the
  human instead.
- Repository-specific ticket/branch policies come from project context; fetch
  the actual ticket key before creating a work branch when one is required.

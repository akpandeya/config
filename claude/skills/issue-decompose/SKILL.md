---
name: issue-decompose
description: Decompose a GitHub issue into atomic, agy/Jules-runnable task prompt files using Opus with extended thinking. Usage: /issue-decompose <owner/repo> <issue-number>
allowed-tools: Bash, Read, Write, Agent
argument-hint: "<owner/repo> <issue-number>"
---

Decompose a GitHub issue into small, atomic implementation tasks that can each be run
independently by `agy` or Jules. Saves prompts to `~/.claude/agy-prompts/<slug>/`.

## Parse arguments

`$ARGUMENTS` format: `<owner/repo> <issue-number>`
Example: `akpandeya/party-planner 72`

Extract `REPO` and `ISSUE_NUM` from `$ARGUMENTS`.
Derive `SLUG` = repo owner + "-" + repo name + "-issue-" + issue number
(e.g. `akpandeya-party-planner-issue-72`).
Set `PROMPT_DIR` = `~/.claude/agy-prompts/$SLUG`.

## Locate repo

Run `gh repo view $REPO --json url` to confirm the repo exists.
Find the local clone: check common paths like `~/Documents/akpandeya/`,
`~/code/`, `~/projects/`. If not found, skip repo-local file reads but
still read the CLAUDE.md via `gh api repos/$REPO/contents/CLAUDE.md`.

## Spawn Opus decomposer

Spawn an **Opus** Agent (`model: opus`) with the following prompt:

---
Think deeply before producing any output. Use extended thinking to reason through
file dependencies, hidden coupling, and failure modes before committing to a task
breakdown. Do not output the task list until your thinking is complete.

You are decomposing GitHub issue into atomic implementation tasks.

**Issue:** Run `gh issue view $ISSUE_NUM --repo $REPO --json title,body,labels` and
read the full output.

**Standing rules:** Read `CLAUDE.md` or `AGENTS.md` in the repo root
(path: `$REPO_PATH/CLAUDE.md` or via gh api). Extract the project's own rules
about testing, style, DB, auth, etc. into a `standing-rules.md`.

**Relevant files:** Infer which 3–5 source files the issue will touch. Read them.

**Decompose** into N tasks (usually 1–5) where each task:
- Touches ≤ 3 files, ships as exactly 1 commit
- Has ≤ 5 acceptance criteria verifiable without Playwright/e2e
- Has an explicit `blockedBy: ["task-NN"]` list if it must come after another task
- Is self-contained enough for an autonomous agent to implement without questions

**For each task**, write a complete prompt file to
`$PROMPT_DIR/task-NN.md` using this exact template:

```
# <task title>

Working dir: <abs repo path>

## Acceptance criteria
- [ ] ...

## Relevant files
- `path/to/file` — <one-line role>

## Context
<1–2 sentences of why/what>

---
<paste standing rules here verbatim>

## Absolute rules (non-negotiable)
- Do NOT modify package.json / package-lock.json / yarn.lock
- Make autonomous judgment calls; do NOT pause or ask for input at any point
- Do NOT run Playwright/e2e — only: build + unit tests
- Do NOT open a PR — implement, test, fix errors, then stop
```

**Also write:**
- `$PROMPT_DIR/standing-rules.md` — the extracted repo standing rules
- `$PROMPT_DIR/manifest.json` with schema:

```json
{
  "repo": "owner/repo",
  "issue": <number>,
  "repoPath": "<abs path or null>",
  "promptDir": "<abs path>",
  "tasks": [
    {
      "id": "task-01",
      "title": "...",
      "branch": "agy/issue-<N>-<slug>",
      "blockedBy": [],
      "status": "pending"
    }
  ]
}
```

After writing all files, print the full task list with titles, file counts,
and dependency order. Then stop.
---

## After the Opus agent returns

Read `$PROMPT_DIR/manifest.json` and show the user the decomposed task list.
Tell them to run `/agy-drive $REPO $ISSUE_NUM` or `/jules-drive $REPO $ISSUE_NUM`
to execute it, with optional `--reviewer=sonnet|agy`.

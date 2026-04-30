---
name: pr-create
description: Open a PR from the current feature branch (right gh account, concise human-readable body) and start a background CI observer.
allowed-tools: Bash, Read, Write, Agent
---

You're creating a PR for the user. Do it mechanically — the hard part
(gh account selection, push, create, observer start) is in the script.
Your job is just the PR body.

## Pre-flight

Check working tree:

!`git status --short`

!`git log --oneline -5`

If there are uncommitted changes, ask the user whether to commit them
first (don't auto-commit — user hasn't asked for that).

## Write the PR body

Write a **concise** body to `/tmp/pr-body-$(date +%s).md`. Structure:

```
## Summary

- 1–3 bullets describing the *change*, not the files. Focus on what
  the user will notice or why this matters. No file-by-file lists.

## Test plan

- [ ] `uv run pytest` passes (or equivalent)
- [ ] manual check X
```

Do NOT include:
- Emojis (unless the user asked for them)
- Every modified filename
- Detailed changelog; the commit message carries that
- "Generated with Claude Code" footers

Keep it under ~150 words.

## Open the PR

!`~/code/personal/config/claude/scripts/pr-create.sh --title "<title>" --body-file <body-file>`

Replace `<title>` with a matching imperative title under 70 chars, and
`<body-file>` with the path you just wrote.

Parse `PR_URL=…` and `PR_NUMBER=…` from stdout.

## Start the observer

After the PR opens, spawn the `ci-observer` agent in the background.
It watches the PR and only reports when something needs human
attention or when CI goes green.

Use `Agent(subagent_type="ci-observer", run_in_background=true, …)` with
the PR number and the expected log path (`~/.jarvis/logs/pr-wait-<n>.log`).

## Respond to the user

One or two lines: PR URL + "Observer running in background. I'll ping
you when it's green or needs attention."

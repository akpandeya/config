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

Only list non-obvious manual checks. CI already runs tests/lint/build
on every push, so lines like `[ ] uv run pytest` or `[ ] ruff clean`
are noise — drop them. Use this section for things a reviewer or the
user actually has to do themselves (e.g. "click Re-auth in Settings
and confirm the terminal window spawns").

If the PR's behaviour is entirely caught by CI, omit the Test plan
section entirely.
```

Do NOT include:
- Emojis (unless the user asked for them)
- Every modified filename
- Detailed changelog; the commit message carries that

DO include the `🤖 Generated with [Claude Code](https://claude.com/claude-code)`
footer — the user has asked for it to stay, helps track attribution.

Keep it under ~150 words.

## Open the PR

Call the script yourself via the Bash tool. Do NOT paste a literal
`<title>` / `<body-file>` — substitute the real values first. The
shape is:

```
~/code/personal/config/claude/scripts/pr-create.sh \
    --title "feat(x): ..." \
    --body-file /tmp/pr-body-1234567890.md
```

Parse `PR_URL=…` and `PR_NUMBER=…` from stdout.

## Start the observer

After the PR opens, spawn the `ci-observer` agent in the background.
It watches the PR and reports when CI goes green or red (failure/error).

Use `Agent(subagent_type="ci-observer", run_in_background=true, …)` with
the PR number and the expected log path (`~/.jarvis/logs/pr-wait-<n>.log`).
In the agent prompt, say: "Ping back when CI goes green OR red (failure/error)."

## Respond to the user

One or two lines: PR URL + "Observer running in background. I'll ping
you when CI goes green or red."

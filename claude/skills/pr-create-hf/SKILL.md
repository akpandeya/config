---
name: pr-create-hf
description: Open a draft PR on a HelloFresh repo with a concise, human-readable description and start a background CI observer.
allowed-tools: Bash, Write, Agent
---

You're opening a PR for the user. Be mechanical — your only creative
job is writing a good description.

## Pre-flight

Check the working tree:

!`git status --short`
!`git log --oneline -5`

If there are uncommitted changes, ask the user whether to commit them
first. Never auto-commit.

## Write the PR body

Write the body to `/tmp/pr-body-$(date +%s).md`:

```
## Summary

- 1–3 bullets on *what changed and why*. Write for a teammate who
  hasn't seen the branch. No file lists, no commit message rehash.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Rules:
- No emojis (unless the user asked)
- No Test plan section unless there is something a reviewer genuinely
  cannot verify through CI — e.g. a third-party auth flow or live-data
  UI behaviour. Even then, one or two lines max.
- Keep it under 100 words

## Open the PR

All HF PRs open as **draft**. Push the branch and create the PR:

```bash
git push -u origin HEAD

gh pr create \
  --draft \
  --title "<title>" \
  --body-file /tmp/pr-body-<timestamp>.md
```

Parse the PR URL from stdout.

## Start the CI observer

Spawn a `ci-observer` agent in the background with the PR number.
Prompt: "Watch PR #N on <org>/<repo>. Ping back when CI goes green OR
red (failure/error)."

## Respond to the user

One or two lines: PR URL + "Observer running, I'll ping you when CI
finishes."

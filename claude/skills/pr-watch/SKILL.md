---
name: pr-watch
description: Start a background CI observer for an existing PR number. Notifies on red / new comments / green.
allowed-tools: Bash, Read, Agent
---

The user wants to watch an existing PR. Extract the PR number from
their message. If ambiguous, ask.

Spawn the `ci-observer` agent in the background with the PR number and
expected log path (`~/.jarvis/logs/pr-wait-<n>.log`). The agent does
the actual polling (via `pr-wait-green.sh`) and only pings back on
meaningful state changes or when CI goes green.

Respond to the user with: `Observer running for PR #<n>. I'll ping you
when it's green or needs attention.` — nothing else.

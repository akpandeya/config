---
name: pr-watch
description: Watch CI for an exact repository and PR without changing code or posting. Reports passed checks, settled failures or timeout; does not authorize repair.
allowed-tools: Bash, Read, Agent
---

The user wants to watch an existing PR. Extract the PR number from
their message. If ambiguous, ask.

Spawn the `ci-observer` agent in the background with the repository and PR number.
Retain the actual `LOG_PATH` returned by its poller instead of guessing. The agent does
the actual polling (via `pr-wait-green.sh`) and only pings back on
meaningful state changes or when CI goes green.

Use the current harness's tracked background facility. If custom agents are
unavailable, run the same bounded poller directly. Announce observation only after
launch succeeds. Watching never invokes a fixer; an explicitly authorized
repair workflow owns that separate step.

---
name: pr-merge
description: Merge a PR respecting repo scope. Personal repos squash-merge; work repos nudge the user (HF policy — humans merge).
allowed-tools: Bash
---

The user wants to merge a PR. Extract the PR number from their
message; if ambiguous, ask.

Delegate to the scope-aware script:

!`~/code/personal/config/claude/scripts/pr-merge.sh <pr-number>`

Script behaviour:

- **Personal** (`$PWD` under `~/code/personal/`): squash-merges with
  branch delete. Reports success.
- **Work** (`$PWD` under `~/code/work/`): prints a nudge with the PR
  URL and rings the bell, then exits non-zero. **Do not try to
  override this** — HF policy is that humans merge.
- **Unknown scope**: refuses; tells the user to run from a
  recognised repo.

Relay the script's output verbatim to the user — no extra commentary
beyond ≤20 words.

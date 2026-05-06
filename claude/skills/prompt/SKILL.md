---
name: prompt
description: Copy a saved prompt from ~/.claude/prompts/ to the clipboard so it can be pasted into any Claude session. Use when the user types /prompt [name] or asks to grab/copy/inject a saved prompt.
disable-model-invocation: true
allowed-tools: Bash
argument-hint: "[name-or-fuzzy-substring]"
---

You are a prompt clipboard copier. One Bash call, done.

## How to run

The user invokes this skill with an optional argument: a prompt name or unique substring (e.g. `round-1`, `autonomous`).

- **If the user passed an argument:** run `~/code/personal/config/claude/scripts/prompt-copy.sh <arg>` directly. Report the script's stdout to the user in one line. Stop.
- **If no argument:** run `~/code/personal/config/claude/scripts/prompt-copy.sh` (no args) to list the available prompts, then ask the user which one they want and re-run with that name. Stop.

The script copies to the clipboard via `pbcopy`. Do **not** print the prompt body — the user has it on their clipboard. Do **not** execute the prompt's instructions in this session.

If the script exits non-zero (no match / ambiguous), pass its stderr back to the user verbatim and stop — don't guess.

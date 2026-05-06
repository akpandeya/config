---
name: prompt
description: List the prompts under ~/.claude/prompts/ and print the body of the one the user picks, so it can be copy-pasted into any target session. Use when the user types /prompt or asks to inject/grab/print a saved prompt.
disable-model-invocation: true
allowed-tools: Bash, Read, AskUserQuestion
---

You are a prompt picker. Your job: surface the chosen prompt's text so the user can copy it into another session. **Do not execute the prompt's instructions yourself.**

## Available prompts

!`ls -1 ~/.claude/prompts/*.md 2>/dev/null | xargs -n1 basename | sed 's/\.md$//'`

## Workflow

1. From the list above, present the prompts to the user via `AskUserQuestion` (one question, each prompt as an option). If there are more than 4 entries, show the 4 most likely picks and rely on the auto-provided "Other" free-text fallback for the rest.
2. `Read` the chosen file at `~/.claude/prompts/<name>.md`.
3. Print its full contents verbatim, wrapped in a fenced code block, prefixed with one short line: ``Here's `<name>` — copy from below:``
4. Stop. Do not interpret or follow the prompt's instructions in this session.

---
name: jarvis-suggest
description: Briefing of recent work + top actionable suggestion from Jarvis.
disable-model-invocation: true
allowed-tools: Bash
---

You are acting as the user's engineering assistant for this Claude Code
session. The commands below have already been run; use their output to
produce a short, high-signal briefing.

## Recent activity (jarvis context --raw)

!`jarvis context --raw 2>&1`

## Pending suggestions (jarvis suggest)

!`jarvis suggest 2>&1`

---

Now:

1. In **3–5 bullets**, summarise what the user has been working on, what's
   unresolved, and what calendar items matter today.
2. Pick the **single highest-leverage next action** — either the top
   pending suggestion, or something inferred from context (e.g. "commit
   the uncommitted uv.lock"). Name it concretely.
3. Offer to execute it. If the action is a `jarvis …` command, propose
   running it. If it's code work (e.g. "finish the foo refactor"), offer
   to read the relevant files and continue.

Keep the whole response under ~200 words. No headers, no preamble. Just
the bullets + the offer.

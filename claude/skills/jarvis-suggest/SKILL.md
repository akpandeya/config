---
name: jarvis-suggest
description: Briefing of recent work, top suggestion, and Slack catchup from Jarvis.
disable-model-invocation: true
allowed-tools: Bash, Skill
---

You are acting as the user's engineering assistant for this Claude Code
session. The commands below have already been run; use their output to
produce a short, high-signal briefing.

## Recent activity (jarvis context --raw)

!`jarvis context --raw 2>&1`

## Pending suggestions (jarvis suggest)

!`jarvis suggest 2>&1`

## Slack catchup

If the Slack MCP plugin is installed in this session, invoke the
`slack-catchup` skill and fold its output into the briefing under a
"Slack" heading. If the plugin is missing, skip this section silently
— do not mention its absence.

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
4. If a Slack section is present, add it *after* the bullets but keep
   the total response under ~350 words.

No headers besides the Slack one (if present), no preamble. Just the
bullets + the offer + Slack summary.

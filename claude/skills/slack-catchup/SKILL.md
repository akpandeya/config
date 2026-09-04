---
name: slack-catchup
description: Briefing of unread DMs, @-mentions, and digest of subscribed Slack channels.
argument-hint: "[channel...]"
disable-model-invocation: true
allowed-tools: Bash, Skill
---

You are producing a tight, ≤250-word Slack brief for the user.

If the Slack MCP plugin isn't installed, respond with exactly:
**"Slack MCP not available. Run `claude plugin install slack` then
authenticate via `/mcp`."** and stop. Don't attempt the other tasks.

## Subscribed channels (from Jarvis kv, unless overridden by `$ARGUMENTS`)

!`sqlite3 ~/.jarvis/jarvis.db "SELECT value FROM kv WHERE key='slack_channels'" 2>/dev/null`

If `$ARGUMENTS` is non-empty, treat it as a space-separated list of
channel names and use that instead of the kv list.

## Tasks

1. **Unread DMs + @-mentions.** Use the `slack:slack-search` skill
   (or Slack MCP tools it wraps) to find:
   - Direct messages where the last message is from someone else and
     I haven't responded.
   - `@me` mentions across channels that I haven't read.
   Group DMs by sender, mentions by channel, newest first.

2. **Channel digest.** For each channel in the list above, invoke the
   `slack:channel-digest` skill for the last ~6 hours. Distil each
   channel's output to 1–3 lines — only decisions, incidents, or
   questions addressed to the team. Drop idle chatter.

## Format

- Three sections, in this order: **DMs**, **Mentions**, **Channel digest**.
- If a section has nothing, write `- no activity`.
- Each line: short `<sender/channel>: <gist>` followed by the Slack
  permalink so the user can jump directly.
- No preamble, no follow-up questions.
- Total ≤250 words.

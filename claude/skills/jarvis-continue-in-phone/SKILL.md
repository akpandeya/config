---
name: jarvis-continue-in-phone
description: Hand off the current Claude Code session to a Matrix room so you can keep talking to it from your phone. Use when the user says "continue this on my phone", "send this to my phone", "phone-handoff", or `/jarvis-continue-in-phone`.
allowed-tools: Bash, Read
---

Hand off the current Claude session to a Matrix room. The user keeps
talking to the *same* session (same conversation history, same tool
state) from their phone via the Matrix bridge.

## What you do

1. **Resolve the current Claude session id.** Try in this order:
   - Env var `$CLAUDE_SESSION_ID` (if set in this shell).
   - Transcript path: the latest `.jsonl` under
     `~/.claude/projects/$(pwd | sed 's,/,-,g')/` — the file stem is the
     session id.
   - If neither is available, ask the user to paste the session id
     (they can grab it from `claude --list-sessions` or the transcript
     directory). Don't guess.

2. **POST to the local handoff endpoint** via `curl`:

   ```
   curl -fsS -X POST http://127.0.0.1:8745/api/bridge/handoff \
        -H 'Content-Type: application/json' \
        -d "{\"session_id\": \"$SESSION_ID\"}"
   ```

   The response is a JSON object: `{"room_id": "...", "matrix_to_url": "..."}`.

3. **Print the tappable link** so the user can open it on their phone.
   One line is enough — no preamble, no explanation:

   ```
   Matrix room ready → <matrix_to_url>
   ```

## Failure modes

- HTTP 400 → session id missing or wrong shape. Re-resolve and try
  again, or surface the server's error message.
- HTTP 503 → bridge not configured. Tell the user to set
  `[bridge.matrix]` in `~/.jarvis/config.toml` (homeserver_url, user_id,
  access token via `MATRIX_JARVIS_ACCESS_TOKEN` env var or Keychain).
- Connection refused → `jarvis web` isn't running. Tell the user to
  start it with `jarvis web` in another terminal.

Don't retry on success; the endpoint is idempotent — calling twice for
the same session returns the same room. Calling again is safe but
wastes a round-trip.

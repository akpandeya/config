#!/bin/bash
# PostToolUse hook. Registers PRs/Jira tickets Claude creates with Jarvis
# so they surface on the Focus/PRs page immediately instead of after the
# next `jarvis ingest` cron tick.
#
# Stdin: JSON {tool_name, tool_input.command, tool_response.stdout, ...}.
# Exit: always 0 — hook failures must never block the originating tool.
set -u
mkdir -p "$HOME/.jarvis"
exec 2>> "$HOME/.jarvis/hook.log"
echo "--- $(date -Iseconds) ---"

INPUT=$(cat)

TOOL=$(printf '%s' "$INPUT" | jq -r '.tool_name // ""')
if [ "$TOOL" != "Bash" ]; then exit 0; fi

# Only act on successful commands.
RC=$(printf '%s' "$INPUT" | jq -r '.tool_response.exit_code // 1')
if [ "$RC" != "0" ]; then exit 0; fi

CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // ""')
OUT=$(printf '%s' "$INPUT" | jq -r '.tool_response.stdout // ""')

# gh pr create → register the new PR
if printf '%s' "$CMD" | grep -qE 'gh[[:space:]]+pr[[:space:]]+create'; then
  URL=$(printf '%s' "$OUT" | grep -oE 'https://github\.com/[^/]+/[^/]+/pull/[0-9]+' | tail -1)
  if [ -n "$URL" ]; then
    REPO=$(printf '%s' "$URL" | sed -E 's#https://github\.com/([^/]+/[^/]+)/pull/.*#\1#')
    NUM=$(printf '%s' "$URL" | sed -E 's#.*/pull/([0-9]+).*#\1#')
    echo "register pr $REPO #$NUM"
    curl -sf -X POST http://127.0.0.1:8745/api/prs/subscribe \
      --data-urlencode "repo=$REPO" --data-urlencode "pr_number=$NUM" \
      --max-time 5 >/dev/null 2>&1 || echo "  (server unreachable)"
  fi
fi

# jira issue create → register the new ticket
if printf '%s' "$CMD" | grep -qE 'jira[[:space:]]+issue[[:space:]]+create'; then
  KEY=$(printf '%s' "$OUT" | grep -oE '[A-Z][A-Z0-9]+-[0-9]+' | head -1)
  if [ -n "$KEY" ]; then
    URL_LINE=$(printf '%s' "$OUT" | grep -oE 'https?://[^[:space:]]+/browse/[A-Z][A-Z0-9]+-[0-9]+' | head -1 || true)
    echo "register jira $KEY url=${URL_LINE:-}"
    curl -sf -X POST http://127.0.0.1:8745/api/jira/subscribe-ticket \
      --data-urlencode "key=$KEY" --data-urlencode "url=${URL_LINE:-}" \
      --max-time 5 >/dev/null 2>&1 || echo "  (server unreachable)"
  fi
fi

exit 0

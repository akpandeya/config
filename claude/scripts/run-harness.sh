#!/usr/bin/env bash
# Run one headless agent turn on a chosen harness and model.
#
# Usage: run-harness.sh <claude|opencode|agy> <model> <implement|decompose|review> <cwd> <prompt-file> <log-file>
#
# - implement: writes code in <cwd>; must not commit, push or open PRs (the driver owns those).
# - decompose: writes prompt/manifest files; no code changes.
# - review: read-only; reports findings and never edits.
#
# Same-harness agents should use the orchestrator's own subagent tool instead of this script.
set -euo pipefail

if [ $# -ne 6 ]; then
  echo "usage: run-harness.sh <claude|opencode|agy> <model> <implement|decompose|review> <cwd> <prompt-file> <log-file>" >&2
  exit 2
fi

HARNESS=$1
MODEL=$2
ROLE=$3
CWD=$4
PROMPT_FILE=$5
LOG_FILE=$6

case "$HARNESS" in
  claude | opencode | agy) ;;
  *) echo "run-harness: unknown harness '$HARNESS' (want claude, opencode or agy)" >&2; exit 2 ;;
esac

case "$ROLE" in
  implement | decompose | review) ;;
  *) echo "run-harness: unknown role '$ROLE' (want implement, decompose or review)" >&2; exit 2 ;;
esac

[ -n "$MODEL" ] || { echo "run-harness: model is empty" >&2; exit 2; }
[ -d "$CWD" ] || { echo "run-harness: cwd not found: $CWD" >&2; exit 2; }
[ -f "$PROMPT_FILE" ] || { echo "run-harness: prompt file not found: $PROMPT_FILE" >&2; exit 2; }

PROMPT=$(cat "$PROMPT_FILE")
mkdir -p "$(dirname "$LOG_FILE")"

# Each harness gets the least permission that still lets the role work.
case "$HARNESS:$ROLE" in
  claude:review) PERMISSION=(--permission-mode plan) ;;
  claude:*) PERMISSION=(--permission-mode acceptEdits) ;;
  opencode:review) PERMISSION=(--agent reviewer --auto) ;;
  opencode:*) PERMISSION=(--agent coder --auto) ;;
  # Headless agy denies shell under accept-edits and plan modes, so verify commands would be
  # refused. Every agy role therefore uses the full flag, as agy-drive always did. Read-only
  # review is enforced by the caller: epic-review checks the working tree is still clean afterwards.
  agy:*) PERMISSION=(--dangerously-skip-permissions) ;;
esac

# The full transcript goes to the log only. Printing it would copy the whole run into the
# caller's context, so the caller reads the log's tail and checks the exit status.
case "$HARNESS" in
  claude)
    ( cd "$CWD" && claude -p --model "$MODEL" "${PERMISSION[@]}" "$PROMPT" ) > "$LOG_FILE" 2>&1
    ;;
  opencode)
    ( cd "$CWD" && opencode run -m "$MODEL" "${PERMISSION[@]}" "$PROMPT" ) > "$LOG_FILE" 2>&1
    ;;
  agy)
    ( cd "$CWD" && agy -p "$PROMPT" --model "$MODEL" --print-timeout 30m "${PERMISSION[@]}" ) > "$LOG_FILE" 2>&1
    ;;
esac
echo "run-harness: $HARNESS $ROLE finished, log: $LOG_FILE"

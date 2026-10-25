#!/usr/bin/env bash
# Run one headless agent turn on a chosen harness and model.
#
# Usage: run-harness.sh <claude|opencode|agy> <model> <implement|decompose|review> <cwd> <prompt-file> <log-file>
#
# - implement: writes code in <cwd>; must not commit, push or open PRs (the driver owns those).
#              implement-preamble.md (next to this script) is prepended to the prompt; the original
#              prompt file is left untouched.
# - decompose: writes prompt/manifest files into the prompt file's directory; no code changes.
#              claude gets that directory via --add-dir because it is outside <cwd>.
# - review:    reviews the epic in <cwd> and may edit files there. <cwd> should be a disposable
#              git worktree. The reviewer must report every change it makes; the driver commits them.
#
# Env:
#   TIMEOUT  wall-clock limit per run, default 30m. Accepts N, Ns, Nm or Nh. A timeout exits non-zero.
#
# Exit codes: 0 ok, 2 usage, 3 the log contains a permission denial (never treat as success),
# anything else is the harness's own exit status (142 = timed out).
#
# Same-harness agents should use the orchestrator's own subagent tool instead of this script.
set -euo pipefail

# Scan a log for permission denials. Prints the matching lines and returns 0 when any are found.
# Deliberately specific: a bare "permission" would also match code the agent is merely reading.
scan_log_for_denials() {
  grep -inE 'permission denied|auto-denied|permission .*(was|is|been) denied|denied permission|requires? (user )?permission|not permitted|operation not allowed|tool use was rejected|haven.t been granted|held for approval|awaiting approval' "$1" | head -5
}

# Return 0 and print seconds for N, Ns, Nm, Nh.
timeout_seconds() {
  case "$1" in
    *[!0-9smh]* | "") return 1 ;;
    *h) echo $(( ${1%h} * 3600 )) ;;
    *m) echo $(( ${1%m} * 60 )) ;;
    *s) echo "${1%s}" ;;
    *) echo "$1" ;;
  esac
}

# Allow sourcing for tests: RUN_HARNESS_SOURCE_ONLY=1 source run-harness.sh defines the functions only.
if [ "${RUN_HARNESS_SOURCE_ONLY:-}" = 1 ]; then return 0 2>/dev/null || exit 0; fi

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

TIMEOUT=${TIMEOUT:-30m}
TIMEOUT_SECONDS=$(timeout_seconds "$TIMEOUT") || { echo "run-harness: bad TIMEOUT '$TIMEOUT' (want N, Ns, Nm or Nh)" >&2; exit 2; }

mkdir -p "$(dirname "$LOG_FILE")"

# Resolve the script's own directory through symlinks, to find the preamble.
SELF=${BASH_SOURCE[0]}
while [ -L "$SELF" ]; do
  LINK=$(readlink "$SELF")
  case "$LINK" in /*) SELF=$LINK ;; *) SELF=$(dirname "$SELF")/$LINK ;; esac
done
SCRIPT_DIR=$(cd "$(dirname "$SELF")" && pwd)

EFFECTIVE_PROMPT_FILE=$PROMPT_FILE
if [ "$ROLE" = implement ]; then
  PREAMBLE_FILE=$SCRIPT_DIR/implement-preamble.md
  [ -f "$PREAMBLE_FILE" ] || { echo "run-harness: preamble not found: $PREAMBLE_FILE" >&2; exit 2; }
  EFFECTIVE_PROMPT_FILE="$(dirname "$LOG_FILE")/$(basename "$LOG_FILE").prompt"
  { cat "$PREAMBLE_FILE"; printf '\n\n'; cat "$PROMPT_FILE"; } > "$EFFECTIVE_PROMPT_FILE"
fi
PROMPT=$(cat "$EFFECTIVE_PROMPT_FILE")
PROMPT_DIR_OF_FILE=$(cd "$(dirname "$PROMPT_FILE")" && pwd)

# Each harness gets the least permission that still lets the role work. Reviewers may edit and run
# shell (to re-run verify), so they get the same level as implementers.
case "$HARNESS:$ROLE" in
  # A reviewer must re-run VERIFY, which needs shell. acceptEdits alone holds Bash for approval,
  # which a headless run cannot give. The review cwd is a disposable worktree, so allow Bash there.
  claude:review) PERMISSION=(--permission-mode acceptEdits --allowedTools=Bash) ;;
  claude:*) PERMISSION=(--permission-mode acceptEdits) ;;
  opencode:review) PERMISSION=(--agent reviewer --auto) ;;
  opencode:*) PERMISSION=(--agent coder --auto) ;;
  # Headless agy denies shell under accept-edits and plan modes, so verify commands would be
  # refused. Every agy role therefore uses the full flag, as agy-drive always did.
  agy:*) PERMISSION=(--dangerously-skip-permissions) ;;
esac

# claude -p takes --add-dir with multiple paths, so the prompt argument must come before it.
EXTRA=()
if [ "$HARNESS:$ROLE" = claude:decompose ]; then EXTRA=(--add-dir "$PROMPT_DIR_OF_FILE"); fi

# The full transcript goes to the log only. Printing it would copy the whole run into the
# caller's context, so the caller reads the log's tail and checks the exit status.
# </dev/null: a harness must never wait on stdin. perl alarm gives macOS a timeout; the exit
# status is 142 (SIGALRM) on timeout.
set +e
case "$HARNESS" in
  claude)
    ( cd "$CWD" && perl -e 'alarm shift; exec @ARGV' "$TIMEOUT_SECONDS" \
        claude -p --model "$MODEL" "${PERMISSION[@]}" "$PROMPT" ${EXTRA[@]+"${EXTRA[@]}"} </dev/null ) > "$LOG_FILE" 2>&1
    ;;
  opencode)
    ( cd "$CWD" && perl -e 'alarm shift; exec @ARGV' "$TIMEOUT_SECONDS" \
        opencode run -m "$MODEL" "${PERMISSION[@]}" "$PROMPT" </dev/null ) > "$LOG_FILE" 2>&1
    ;;
  agy)
    ( cd "$CWD" && agy -p "$PROMPT" --model "$MODEL" --print-timeout "${TIMEOUT_SECONDS}s" "${PERMISSION[@]}" </dev/null ) > "$LOG_FILE" 2>&1
    ;;
esac
RC=$?
set -e

if [ "$RC" -ne 0 ]; then
  echo "run-harness: $HARNESS $ROLE failed with exit $RC$([ "$RC" -eq 142 ] && echo ' (timed out)'), log: $LOG_FILE" >&2
  exit "$RC"
fi

if DENIALS=$(scan_log_for_denials "$LOG_FILE") && [ -n "$DENIALS" ]; then
  echo "run-harness: $HARNESS $ROLE exited 0 but the log shows a permission denial, treat the run as failed. log: $LOG_FILE" >&2
  echo "$DENIALS" >&2
  exit 3
fi

echo "run-harness: $HARNESS $ROLE finished, log: $LOG_FILE"

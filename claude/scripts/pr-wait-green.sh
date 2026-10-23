#!/usr/bin/env bash
# Observe only. Exit 0: checks passed; 2: settled failure; 1: timeout/API failure.
# Usage: pr-wait-green.sh <number> [--repo owner/repo] [--log path]
#        [--interval seconds] [--max-ticks n]
set -uo pipefail

PR=""
REPO="${GH_REPO:-}"
LOG=""
INTERVAL=60
MAX_TICKS=60
while [ "$#" -gt 0 ]; do
    case "$1" in
        --repo|--log|--interval|--max-ticks)
            [ "$#" -ge 2 ] || { echo "Missing value for $1" >&2; exit 1; }
            case "$1" in
                --repo) REPO="$2" ;;
                --log) LOG="$2" ;;
                --interval) INTERVAL="$2" ;;
                --max-ticks) MAX_TICKS="$2" ;;
            esac
            shift 2 ;;
        -*) echo "Unknown argument: $1" >&2; exit 1 ;;
        *) [ -z "$PR" ] || { echo "Expected one PR number" >&2; exit 1; }
           PR="$1"; shift ;;
    esac
done
[[ "$PR" =~ ^[1-9][0-9]*$ && "$INTERVAL" =~ ^[0-9]+$ && "$MAX_TICKS" =~ ^[1-9][0-9]*$ ]] ||
    { echo "Expected a PR number, nonnegative interval and positive max-ticks" >&2; exit 1; }
if [ -z "$REPO" ]; then
    REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner)" || exit 1
fi
[[ "$REPO" =~ ^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$ ]] ||
    { echo "Expected --repo owner/repo" >&2; exit 1; }
STATE_DIR="$(mktemp -d)" || exit 1
trap 'rm -rf "$STATE_DIR"' EXIT
if [ -z "$LOG" ]; then
    mkdir -p "$HOME/.jarvis/logs" || exit 1
    LOG="$(mktemp "$HOME/.jarvis/logs/pr-wait-${REPO//\//-}-${PR}.XXXXXX")" || exit 1
fi
mkdir -p "$(dirname "$LOG")" || exit 1
touch "$LOG" || exit 1
printf 'LOG_PATH=%s\n' "$LOG"

emit() { printf '%s\n' "$1" | tee -a "$LOG" >&2; }

observe_discussion() {
    local kind="$1" endpoint="$2" json
    if ! json="$(gh api "$endpoint" --paginate | jq -cs 'add // []')"; then
        emit "EVENT observation_error kind=$kind"
        return
    fi
    if ! printf '%s' "$json" | jq -er '.[] | "\(.id)\t\(.user.login)\t\(.state // "")"' \
        > "$STATE_DIR/$kind.new"; then
        # An empty array legitimately produces no rows.
        if [ "$json" != "[]" ]; then
            emit "EVENT observation_error kind=$kind"
            return
        fi
    fi
    LC_ALL=C sort "$STATE_DIR/$kind.new" > "$STATE_DIR/$kind.sorted"
    if [ -f "$STATE_DIR/$kind.previous" ]; then
        while IFS= read -r line; do
            [ -z "$line" ] || emit "EVENT $kind $line"
        done < <(LC_ALL=C comm -13 "$STATE_DIR/$kind.previous" "$STATE_DIR/$kind.sorted")
    fi
    mv "$STATE_DIR/$kind.sorted" "$STATE_DIR/$kind.previous"
}

tick=0
while [ "$tick" -lt "$MAX_TICKS" ]; do
    tick=$((tick + 1))
    checks_json="$(gh pr checks "$PR" --repo "$REPO" --json name,bucket 2>"$STATE_DIR/checks-error")"
    status=$?
    state=UNKNOWN
    failing=""
    pending=0
    if { [ "$status" -eq 0 ] || [ "$status" -eq 1 ] || [ "$status" -eq 8 ]; } &&
       printf '%s' "$checks_json" | jq -e '
         type == "array" and all(.[]; (.name | type == "string") and
           (.bucket as $b | ["pass","fail","pending","skipping","cancel"] | index($b) != null))
       ' >/dev/null 2>&1; then
        total="$(printf '%s' "$checks_json" | jq 'length')"
        pending="$(printf '%s' "$checks_json" | jq '[.[] | select(.bucket=="pending")] | length')"
        failing="$(printf '%s' "$checks_json" | jq -r '[.[] | select(.bucket=="fail" or .bucket=="cancel") | .name] | join(",")')"
        if [ "$pending" -gt 0 ]; then
            state=PENDING
        elif [ -n "$failing" ]; then
            state=FAILING
        elif [ "$total" -gt 0 ]; then
            state=GREEN
        fi
        observe_discussion comment "repos/$REPO/issues/$PR/comments"
        observe_discussion review "repos/$REPO/pulls/$PR/reviews"
        observe_discussion review_comment "repos/$REPO/pulls/$PR/comments"
    else
        emit "EVENT observation_error kind=checks exit=$status"
    fi
    emit "$(date -u +%Y-%m-%dT%H:%M:%SZ) repo=$REPO pr=$PR state=$state tick=$tick red=${failing:-none}"
    case "$state" in
        GREEN) emit "EVENT green repo=$REPO pr=$PR"; exit 0 ;;
        FAILING) emit "EVENT red repo=$REPO pr=$PR failing=$failing"; exit 2 ;;
    esac
    [ "$tick" -ge "$MAX_TICKS" ] || sleep "$INTERVAL"
done
emit "EVENT timeout ticks=$tick state=$state"
exit 1

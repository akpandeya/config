#!/usr/bin/env bash
# Deterministic PR CI observer. No LLM calls — just polls `gh` and writes
# a compact status line on every tick. Exits 0 when green, 1 on terminal
# failure, otherwise keeps looping.
#
# Usage:
#   pr-wait-green.sh <pr-number> [--log <path>] [--interval <seconds>] [--max-ticks <n>]
#
# Log line format (one per tick):
#   2026-04-30T18:12:00Z pr=314 state=PENDING checks=4/5 red=test-macos new_comments=0 new_reviews=0
#
# On state change (PENDING→FAILING, new bot comment, review dismissed),
# also writes `EVENT <kind> <detail>` lines so downstream agents can
# diff the log cheaply.

set -uo pipefail

PR=""
LOG=""
INTERVAL=60
MAX_TICKS=0   # 0 = no cap

while [ $# -gt 0 ]; do
    case "$1" in
        --log)        LOG="$2"; shift 2 ;;
        --interval)   INTERVAL="$2"; shift 2 ;;
        --max-ticks)  MAX_TICKS="$2"; shift 2 ;;
        -*)           echo "Unknown arg: $1" >&2; exit 2 ;;
        *)            PR="$1"; shift ;;
    esac
done

[ -n "$PR" ] || { echo "Missing <pr-number>" >&2; exit 2; }

if [ -z "$LOG" ]; then
    mkdir -p "$HOME/.jarvis/logs" 2>/dev/null || mkdir -p /tmp
    LOG="$HOME/.jarvis/logs/pr-wait-$PR.log"
fi

mkdir -p "$(dirname "$LOG")"
: > "$LOG"
STATE_DIR="$(mktemp -d)"
trap 'rm -rf "$STATE_DIR"' EXIT

COMMENTS_SNAPSHOT="$STATE_DIR/comments.txt"
REVIEWS_SNAPSHOT="$STATE_DIR/reviews.txt"
: > "$COMMENTS_SNAPSHOT"
: > "$REVIEWS_SNAPSHOT"

emit() {
    local line="$1"
    echo "$line" | tee -a "$LOG" >&2
}

tick=0
while :; do
    tick=$((tick+1))
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    # Check state. Missing PR / gh error → log and keep going unless
    # it's been going on for several ticks.
    if ! checks_json="$(gh pr checks "$PR" --json name,state,link 2>/dev/null)"; then
        emit "$ts pr=$PR state=UNKNOWN error=gh_checks_failed"
        sleep "$INTERVAL"
        continue
    fi

    total="$(echo "$checks_json" | jq 'length')"
    passed="$(echo "$checks_json" | jq '[.[] | select(.state=="SUCCESS")] | length')"
    failing="$(echo "$checks_json" | jq -r '[.[] | select(.state=="FAILURE")] | map(.name) | join(",")')"
    pending="$(echo "$checks_json" | jq -r '[.[] | select(.state=="IN_PROGRESS" or .state=="PENDING" or .state=="QUEUED")] | length')"

    if [ "$total" -gt 0 ] && [ -n "$failing" ]; then
        state="FAILING"
    elif [ "$pending" -gt 0 ]; then
        state="PENDING"
    elif [ "$total" -gt 0 ] && [ "$passed" = "$total" ]; then
        state="GREEN"
    else
        state="UNKNOWN"
    fi

    # Diff new PR issue-style comments (includes bot comments).
    new_comments=0
    if comments_json="$(gh api "repos/{owner}/{repo}/issues/$PR/comments" --paginate 2>/dev/null)"; then
        echo "$comments_json" | jq -r '.[] | "\(.id)\t\(.user.login)\t\(.body // "" | split("\n")[0] | .[0:120])"' \
            > "$STATE_DIR/comments.new"
        if [ -s "$COMMENTS_SNAPSHOT" ]; then
            new_comment_lines="$(comm -13 <(sort "$COMMENTS_SNAPSHOT") <(sort "$STATE_DIR/comments.new") || true)"
            if [ -n "$new_comment_lines" ]; then
                new_comments="$(echo "$new_comment_lines" | wc -l | tr -d ' ')"
                while IFS= read -r cl; do
                    [ -z "$cl" ] && continue
                    emit "EVENT comment $cl"
                done <<< "$new_comment_lines"
            fi
        fi
        mv "$STATE_DIR/comments.new" "$COMMENTS_SNAPSHOT"
    fi

    # Diff new reviews.
    new_reviews=0
    if reviews_json="$(gh pr view "$PR" --json reviews 2>/dev/null)"; then
        echo "$reviews_json" | jq -r '.reviews[] | "\(.id)\t\(.state)\t\(.author.login)"' \
            > "$STATE_DIR/reviews.new" || true
        if [ -s "$REVIEWS_SNAPSHOT" ]; then
            new_review_lines="$(comm -13 <(sort "$REVIEWS_SNAPSHOT") <(sort "$STATE_DIR/reviews.new") || true)"
            if [ -n "$new_review_lines" ]; then
                new_reviews="$(echo "$new_review_lines" | wc -l | tr -d ' ')"
                while IFS= read -r rl; do
                    [ -z "$rl" ] && continue
                    emit "EVENT review $rl"
                done <<< "$new_review_lines"
            fi
        fi
        mv "$STATE_DIR/reviews.new" "$REVIEWS_SNAPSHOT"
    fi

    emit "$ts pr=$PR state=$state checks=$passed/$total red=${failing:-none} new_comments=$new_comments new_reviews=$new_reviews"

    if [ "$state" = "GREEN" ]; then
        emit "EVENT green pr=$PR"
        exit 0
    fi

    if [ "$MAX_TICKS" -gt 0 ] && [ "$tick" -ge "$MAX_TICKS" ]; then
        emit "EVENT timeout ticks=$tick"
        exit 1
    fi

    sleep "$INTERVAL"
done

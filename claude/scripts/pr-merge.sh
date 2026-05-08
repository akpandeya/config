#!/usr/bin/env bash
# Merge a PR if local policy allows. Personal repos (under ~/code/personal/)
# get squash-merged; work repos (under ~/code/work/) print a nudge and exit
# non-zero without touching git — HF policy is "human reviews and merges".
#
# Usage:
#   pr-merge.sh <pr-number> [--method squash|merge|rebase]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PR=""
METHOD="squash"

while [ $# -gt 0 ]; do
    case "$1" in
        --method) METHOD="$2"; shift 2 ;;
        -*)       echo "Unknown arg: $1" >&2; exit 2 ;;
        *)        PR="$1"; shift ;;
    esac
done

[ -n "$PR" ] || { echo "Missing <pr-number>" >&2; exit 2; }

SCOPE="$("$SCRIPT_DIR/repo-scope-for-cwd.sh")"

case "$SCOPE" in
    personal)
        # Default: squash-merge, delete branch.
        gh pr merge "$PR" "--$METHOD" --delete-branch
        echo "✅ PR #$PR squash-merged (scope=personal)."
        # Send Matrix merge notification (best-effort)
        PR_TITLE="$(gh pr view "$PR" --json title --jq .title 2>/dev/null || echo "")"
        PR_URL="$(gh pr view "$PR" --json url --jq .url 2>/dev/null || echo "")"
        jarvis bridge send \
            --scope "$SCOPE" \
            --kind autonomous.progress \
            --title "merged: PR #${PR}" \
            --body "${PR_TITLE}"$'\n'"${PR_URL}" 2>/dev/null || true
        ;;
    work)
        # HF policy: humans merge. Print a nudge with the PR URL and
        # ring the terminal bell once so tmux/iTerm notices. Exit 1 so
        # callers don't chain a tag/push after this step.
        url="$(gh pr view "$PR" --json url --jq .url 2>/dev/null || echo "")"
        printf '\a'
        cat <<EOF
🔔 PR #$PR is green but scope=work — NOT merging automatically.
   Review and click merge yourself: $url
EOF
        exit 1
        ;;
    *)
        echo "Unknown repo scope for \$PWD=$PWD — refusing to merge." >&2
        echo "Run from under ~/code/personal/ or ~/code/work/." >&2
        exit 2
        ;;
esac

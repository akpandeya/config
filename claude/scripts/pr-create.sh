#!/usr/bin/env bash
# Create a PR from the current branch using the account resolved from $PWD.
#
# Usage:
#   pr-create.sh --title "feat: …" --body-file /tmp/body.md [--draft] [--base main]
#
# Exits non-zero on any surprise (on main, no upstream configured but push
# fails, gh create fails). Prints `PR_URL=<url>\nPR_NUMBER=<n>` on success.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TITLE=""
BODY_FILE=""
BASE="main"
DRAFT=""

while [ $# -gt 0 ]; do
    case "$1" in
        --title)      TITLE="$2"; shift 2 ;;
        --body-file)  BODY_FILE="$2"; shift 2 ;;
        --base)       BASE="$2"; shift 2 ;;
        --draft)      DRAFT="--draft"; shift ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

[ -n "$TITLE" ]     || { echo "Missing --title" >&2; exit 2; }
[ -n "$BODY_FILE" ] || { echo "Missing --body-file" >&2; exit 2; }
[ -f "$BODY_FILE" ] || { echo "Body file not found: $BODY_FILE" >&2; exit 2; }

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$BRANCH" = "$BASE" ] || [ "$BRANCH" = "HEAD" ]; then
    echo "Refusing to create a PR from $BRANCH (need a feature branch)." >&2
    exit 2
fi

ACCOUNT="$("$SCRIPT_DIR/gh-account-for-cwd.sh")"
if [ -n "$ACCOUNT" ]; then
    # Switch gh's active account so `gh pr create` uses the right token
    # without requiring a per-command env var (saves a keychain lookup).
    gh auth switch --user "$ACCOUNT" >/dev/null 2>&1 || true
fi

# Push the branch (idempotent — sets upstream on first push).
git push -u origin "$BRANCH" >&2

# shellcheck disable=SC2086
URL="$(gh pr create \
    --title "$TITLE" \
    --body-file "$BODY_FILE" \
    --base "$BASE" \
    $DRAFT)"

NUMBER="$(echo "$URL" | awk -F/ '{print $NF}')"

echo "PR_URL=$URL"
echo "PR_NUMBER=$NUMBER"
echo "PR_ACCOUNT=$ACCOUNT"

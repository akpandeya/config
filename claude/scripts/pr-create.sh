#!/usr/bin/env bash
# Create a PR from the current branch using the account resolved from $PWD.
#
# Usage:
#   pr-create.sh --title "feat: …" --body-file /tmp/body.md [--draft] [--base <branch>]
#
# --base defaults to the remote's HEAD (origin/HEAD), discovered via
# git symbolic-ref, `git remote set-head --auto`, then `gh repo view`.
#
# Exits non-zero on any surprise (on main, no upstream configured but push
# fails, gh create fails). Prints `PR_URL=<url>\nPR_NUMBER=<n>` on success.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TITLE=""
BODY_FILE=""
BASE=""
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

# Resolve base from the remote's HEAD if the caller didn't pass --base.
# Falls back through a few discovery paths so we don't hardcode main/master.
if [ -z "$BASE" ]; then
    BASE="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##' || true)"
    if [ -z "$BASE" ]; then
        # Ask the remote directly, then cache the symref locally.
        git remote set-head origin --auto >/dev/null 2>&1 || true
        BASE="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##' || true)"
    fi
    if [ -z "$BASE" ]; then
        BASE="$(gh repo view --json defaultBranchRef --jq .defaultBranchRef.name 2>/dev/null || true)"
    fi
    if [ -z "$BASE" ]; then
        echo "pr-create: could not detect default branch; pass --base explicitly." >&2
        exit 2
    fi
fi

if [ "$BRANCH" = "$BASE" ] || [ "$BRANCH" = "HEAD" ]; then
    echo "Refusing to create a PR from $BRANCH (need a feature branch)." >&2
    exit 2
fi

ACCOUNT="$("$SCRIPT_DIR/gh-account-for-cwd.sh")"
if [ -n "$ACCOUNT" ]; then
    # Switch gh's active account so `gh pr create` uses the right
    # token without requiring a per-command env var (saves a keychain
    # lookup). Log what we switched from → to, so if a PR does end up
    # opened as the wrong identity the trail is visible in the
    # script's stderr capture.
    PREV_ACCOUNT="$(gh api user --jq .login 2>/dev/null || echo '(unknown)')"
    if [ "$PREV_ACCOUNT" != "$ACCOUNT" ]; then
        echo "pr-create: switching gh account $PREV_ACCOUNT -> $ACCOUNT (cwd=$PWD)" >&2
        gh auth switch --user "$ACCOUNT" >/dev/null 2>&1 || {
            echo "pr-create: gh auth switch failed (is $ACCOUNT authed? run 'gh auth login --user $ACCOUNT')" >&2
            exit 2
        }
    fi
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

# Work-scope PRs get a Matrix ping at open time so the human merger
# sees it on their phone — personal PRs already get pinged on merge.
SCOPE="$("$SCRIPT_DIR/repo-scope-for-cwd.sh" 2>/dev/null || echo "")"
if [ "$SCOPE" = "work" ]; then
    jarvis bridge send \
        --scope work \
        --kind pr_ready \
        --title "PR #${NUMBER} opened — needs human merge" \
        --body "${TITLE}"$'\n'"${URL}" >/dev/null 2>&1 || true
fi

echo "PR_URL=$URL"
echo "PR_NUMBER=$NUMBER"
echo "PR_ACCOUNT=$ACCOUNT"

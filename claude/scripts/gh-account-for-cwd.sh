#!/usr/bin/env bash
# Resolve which `gh` account the current working directory belongs to.
#
# Honours the user's `git includeIf` + `ssh config` layout:
#   ~/code/personal/*  → akpandeya
#   ~/code/work/*      → apandeya
# Anywhere else falls back to whoever `gh` is currently authed as.
#
# Usage:
#   account=$(gh-account-for-cwd.sh)
#   GH_TOKEN=$(gh auth token --user "$account") gh pr create ...

set -euo pipefail

case "$PWD/" in
    "$HOME/code/personal"/*) echo "akpandeya" ;;
    "$HOME/code/work"/*)     echo "apandeya"  ;;
    *)
        # Fallback: ask gh for the active login. Never fail — the caller
        # will just use whatever gh defaults to.
        gh api user --jq .login 2>/dev/null || echo ""
        ;;
esac

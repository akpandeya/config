#!/usr/bin/env bash
# Classify the current repo as `personal` or `work` based on $PWD.
# Symmetric with gh-account-for-cwd.sh but reports scope instead of
# account — used by pr-merge to pick the right merge policy.
#
#   ~/code/personal/*  → personal
#   ~/code/work/*      → work
#   anywhere else      → unknown
#
# Usage:
#   scope=$(repo-scope-for-cwd.sh)

set -euo pipefail

case "$PWD/" in
    "$HOME/code/personal"/*) echo "personal" ;;
    "$HOME/code/work"/*)     echo "work"     ;;
    *)                       echo "unknown"  ;;
esac

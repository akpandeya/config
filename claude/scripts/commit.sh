#!/usr/bin/env bash
# Create a git commit with repo-appropriate conventions enforced.
#
# Usage:
#   commit.sh -m "<message>" [-m "<trailer>"]...
#
# Gatekeeper, not generator: the caller composes the message. This
# script enforces the mechanical rules:
#   - work repos (~/code/work/*) require the literal [AI_Code]
#     somewhere in the message — the org auto-labeler
#     (workflow-pr-label-for-ai-code) scans commit messages only,
#     never PR descriptions, so a commit missing it gets no label.
#   - GPG/SSH signing failures get one retry with signing disabled.
#
# Exits non-zero on any surprise. Prints COMMIT_SHA=<sha> on success;
# all other output goes to stderr so stdout stays machine-readable.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MSGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        -m|--message) MSGS+=("$2"); shift 2 ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

if [ "${#MSGS[@]}" -eq 0 ]; then
    echo "Usage: commit.sh -m \"<msg>\" [-m \"<trailer>\"]..." >&2
    exit 2
fi

COMBINED="$(printf '%s\n' "${MSGS[@]}")"

SCOPE="$("$SCRIPT_DIR/repo-scope-for-cwd.sh" 2>/dev/null || echo unknown)"
if [ "$SCOPE" = "work" ] && [[ "$COMBINED" != *'[AI_Code]'* ]]; then
    echo "commit.sh: work repo but no [AI_Code] tag in the message —" >&2
    echo "the org auto-labeler scans commit messages only." >&2
    echo "Add a trailer:  -m \"[AI_Code] harness: <cli>, model: <model-id>\"" >&2
    exit 2
fi

COMMIT_ARGS=()
for m in "${MSGS[@]}"; do
    COMMIT_ARGS+=(-m "$m")
done

if OUT="$(git commit "${COMMIT_ARGS[@]}" 2>&1)"; then
    printf '%s\n' "$OUT" >&2
elif printf '%s' "$OUT" | grep -qiE 'gpg failed to sign|agent refused operation'; then
    echo "commit.sh: signing failed — retrying once with --no-gpg-sign." >&2
    git -c commit.gpgsign=false commit --no-gpg-sign "${COMMIT_ARGS[@]}" >&2
else
    printf '%s\n' "$OUT" >&2
    exit 1
fi

echo "COMMIT_SHA=$(git rev-parse --short HEAD)"

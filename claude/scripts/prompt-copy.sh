#!/usr/bin/env bash
# Copy a saved prompt to the clipboard.
#
# Usage:
#   prompt-copy.sh                # list available prompts (no copy)
#   prompt-copy.sh <name|fuzzy>   # copy that prompt to the clipboard
#
# Matching is: exact basename → unique substring → first match wins on tie.
# Exits non-zero if zero matches or ambiguous (and prints the candidates).

set -euo pipefail

PROMPTS_DIR="$HOME/.claude/prompts"

list() {
    find "$PROMPTS_DIR" -maxdepth 1 -name '*.md' -not -name 'README.md' \
        -exec basename {} .md \; | sort
}

if [ $# -eq 0 ]; then
    echo "Available prompts:"
    list | sed 's/^/  /'
    echo
    echo "Usage: $(basename "$0") <name>"
    exit 0
fi

query="$1"
all=()
while IFS= read -r line; do
    all+=("$line")
done < <(list)

# Exact match wins.
for name in "${all[@]}"; do
    if [ "$name" = "$query" ]; then
        pbcopy < "$PROMPTS_DIR/$name.md"
        echo "Copied '$name' to clipboard ($(wc -c < "$PROMPTS_DIR/$name.md" | tr -d ' ') bytes)."
        exit 0
    fi
done

# Substring match.
matches=()
for name in "${all[@]}"; do
    if [[ "$name" == *"$query"* ]]; then
        matches+=("$name")
    fi
done

case "${#matches[@]}" in
    0)
        echo "No prompt matches '$query'. Available:" >&2
        list | sed 's/^/  /' >&2
        exit 1
        ;;
    1)
        name="${matches[0]}"
        pbcopy < "$PROMPTS_DIR/$name.md"
        echo "Copied '$name' to clipboard ($(wc -c < "$PROMPTS_DIR/$name.md" | tr -d ' ') bytes)."
        ;;
    *)
        echo "Ambiguous query '$query'. Matches:" >&2
        printf '  %s\n' "${matches[@]}" >&2
        exit 2
        ;;
esac

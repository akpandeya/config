#!/usr/bin/env bash
# List the models each harness can run right now, as "<harness><TAB><model>" lines.
# Discovery only: no model calls, so it costs nothing and is safe to run on every epic.
#
# Usage: list-models.sh [claude|opencode|agy]   (default: all three)
set -euo pipefail

WANT=${1:-all}

list_claude() {
  # Claude Code accepts these aliases for --model; they track the latest release of each family.
  printf 'claude\topus\nclaude\tsonnet\nclaude\thaiku\n'
}

list_opencode() {
  # Output is "provider/model" per line; keep only lines that look like model ids.
  opencode models 2>/dev/null | grep '/' | sed 's/^/opencode\t/'
}

list_agy() {
  # Output is "<id><TAB><display name>"; keep the id.
  agy models 2>/dev/null | grep -v '^Fetching' | awk -F'\t' 'NF >= 1 && $1 != "" { print "agy\t" $1 }'
}

case "$WANT" in
  claude) list_claude ;;
  opencode) list_opencode ;;
  agy) list_agy ;;
  all) list_claude; list_opencode; list_agy ;;
  *) echo "usage: list-models.sh [claude|opencode|agy]" >&2; exit 2 ;;
esac

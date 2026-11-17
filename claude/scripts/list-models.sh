#!/usr/bin/env bash
# List the models each harness can run right now, as "<harness><TAB><model>" lines.
# Discovery only: no model calls, so it costs nothing and is safe to run on every epic.
#
# Usage: list-models.sh [claude|opencode|agy|pi]   (default: all four)
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

list_pi() {
  # pi models live in ~/.pi/agent/models.json as providers -> {id: {...}}.
  # Model ids are "provider/model", exactly what `pi --model` accepts.
  local file="${PI_MODELS_JSON:-$HOME/.pi/agent/models.json}"
  [ -f "$file" ] || return 0
  python3 - "$file" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    data = json.load(fh)
for provider, spec in sorted((data.get("providers") or {}).items()):
    models = spec.get("models") or []
    ids = sorted((m.get("id") for m in models if isinstance(m, dict) and m.get("id")))
    for model_id in ids:
        print(f"pi\t{provider}/{model_id}")
PY
}

case "$WANT" in
  claude) list_claude ;;
  opencode) list_opencode ;;
  agy) list_agy ;;
  pi) list_pi ;;
  all) list_claude; list_opencode; list_agy; list_pi ;;
  *) echo "usage: list-models.sh [claude|opencode|agy|pi]" >&2; exit 2 ;;
esac

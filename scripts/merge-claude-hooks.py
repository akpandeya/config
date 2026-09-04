#!/usr/bin/env python3
"""Merge claude/settings-hooks.json into ~/.claude/settings.json.

Replaces only the `hooks.PostToolUse` block. All other top-level keys
(env, model, enabledPlugins, ...) are preserved. Idempotent: running
twice produces no change.

Called by setup-dev-env.sh on fresh-Mac setup and by `jarvis update`
on every update.
"""

from __future__ import annotations

import json
import pathlib
import sys

SETTINGS = pathlib.Path.home() / ".claude" / "settings.json"
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FRAGMENT = REPO_ROOT / "claude" / "settings-hooks.json"


def main() -> int:
    if not FRAGMENT.exists():
        print(f"No hook fragment at {FRAGMENT}, skipping.", file=sys.stderr)
        return 0

    current = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
    fragment = json.loads(FRAGMENT.read_text())

    new_post = fragment.get("hooks", {}).get("PostToolUse", [])
    current.setdefault("hooks", {})

    # Idempotent: short-circuit if already in sync.
    if current["hooks"].get("PostToolUse") == new_post:
        print(f"✓ PostToolUse hook already up to date ({SETTINGS})")
        return 0

    current["hooks"]["PostToolUse"] = new_post
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(current, indent=2) + "\n")
    print(f"✓ Merged PostToolUse hook into {SETTINGS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

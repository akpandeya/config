# Prompts

Long-form prompts to paste into a fresh Claude Code session. Source of truth lives here; `setup-dev-env.sh` symlinks each `*.md` into `~/.claude/prompts/` so the local `prompt` skill can list and inject them.

| Prompt | Purpose |
|---|---|
| `autonomous-mode.md` | Run the jarvis groomed backlog without per-PR check-ins (branch, implement, PR, watch CI, merge, Matrix ping, compact, repeat). |
| `backlog-grooming-round-1.md` | Per-issue clarification pass: walk open issues, ask the human, rewrite each body to be autonomous-Claude-ready, label `groomed`. |
| `backlog-grooming-round-2.md` | Cross-link audit pass: with bodies clean, fix `Blocked by:` edges, dedupe, holistic tier reassignment. Run only after Round 1. |

## Verification (backlog grooming)

- After Round 1 on an issue: `gh issue view <n>` shows the new structure, `groomed` label present, passes the "fresh Claude could implement this" sniff test.
- After Round 2: `gh issue list --label tier-S --milestone "<current wave>"` returns a clean pickup queue; no `Blocked by:` points at a closed issue; no Wave-N issue blocked by Wave-(N+k) issue. Tier distribution looks sane — the tier-S list is small enough to actually ship in the current wave, and any tier-D issues left open have an explicit close/downscope decision attached.

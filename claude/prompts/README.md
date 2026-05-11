# Prompts

Long-form prompts to paste into a fresh Claude Code session. Source of truth lives here; `setup-dev-env.sh` symlinks each `*.md` into `~/.claude/prompts/` so the local `prompt` skill can list and inject them.

## Backlog grooming pipeline

The numbered `backlog-N-*.md` prompts run in order on a single issue's lifecycle:

| Phase | Prompt | Purpose |
|---|---|---|
| 1 | `backlog-1-clarify.md` | Per-issue clarification: walk open issues, ask the human, rewrite each body to be autonomous-Claude-ready. Sets `groomed` if no design needed; sets `needs-design` if it does. Mutually exclusive — never both. |
| 2 | `backlog-2-design.md` | Walk `needs-design` issues, generate UI/UX spec via the `frontend-design` skill, then promote to `groomed`. Owns epic detection + split into shippable sub-issues. |
| 3 | `backlog-3-audit.md` | Cross-link audit on the groomed backlog: fix `Blocked by:` edges, dedupe, holistic tier reassignment. Safety-net epic split for backend-only epics that bypassed design. |

## Other prompts

| Prompt | Purpose |
|---|---|
| `autonomous-mode.md` | Run the jarvis groomed backlog without per-PR check-ins (branch, implement, PR, watch CI, merge, Matrix ping, compact, repeat). |
| `pick-up-ticket.md` | Hand off a single Jira ticket to a fresh session: branch + context-prime + go. |
| `research-question.md` | Answer a focused research question (memo, not code). Pass the question as the argument. Use when grooming surfaces "is X already done?" / "should we evaluate Y?" — produces a recommendation + closes/updates the originating issue. |

## Verification

- After phase 1 on a non-design issue: `gh issue view <n>` shows the new structure, `groomed` label present, passes the "fresh Claude could implement this" sniff test.
- After phase 1 on a design-heavy issue: `needs-design` label only (no `groomed`); body has a `## Design pass` section.
- After phase 2: `groomed` label, `needs-design` removed, body has `## Design spec` instead of `## Design pass`. Epics broken into sub-issues; parent has `epic` label and a `## Sub-issues` section.
- After phase 3: no `Blocked by:` points at a closed issue. Tier distribution sane — `tier-S` list small enough to actually ship next; `tier-D` issues either closed or downscoped with explicit decision attached.

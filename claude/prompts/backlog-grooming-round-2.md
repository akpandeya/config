# Backlog grooming — Round 2: cross-link audit

Paste into a fresh Claude Code session at the repo root, **after** Round 1 (`backlog-grooming-round-1.md`) has run on the open backlog. Round 1 made each issue self-contained; Round 2 makes the *graph* correct.

Conventions (jarvis-specific): tiers `S/A/B/C/D`, `Blocked by: #N, #M` as the first line of each body.

---

Round 2: cross-link audit on the groomed backlog. Round 1 made each issue self-contained; now make the *graph* correct.

Workflow:

1. Pull the full open backlog with bodies:
     gh issue list --state open --limit 200 \
       --json number,title,body,labels

2. Build a map (scratch file is fine) of:
     - declared `Blocked by:` edges (first line of each body)
     - implicit references (`#N` mentioned in body/comments)
     - duplicates / near-duplicates by title + scope
     - parent epics ↔ child sub-issues
     - tier consistency (a tier-S blocked by a tier-C is a smell)

3. For each anomaly, propose a fix and ask before applying:
     - missing `Blocked by:` → add
     - stale `Blocked by:` (referenced issue closed) → remove
     - bidirectional cycle → surface, let me break it
     - dup pair → propose which to close, which to keep
     - tier mismatch with dependencies → propose retier
     - orphaned sub-issues with no epic → propose parent or standalone

4. Holistic tier reassignment. Once bodies are clean and the graph is sane, re-evaluate tiers across the *whole* backlog — not just where dependencies disagreed. With full context now available, the existing tier labels are stale priors; treat each issue's tier as something to re-derive, not defend.
     - Re-read the tier rubric in `CLAUDE.md` ("Two-axis backlog scheme"):
         tier-S = ship next; foundational / unblocks others
         tier-A = high leverage; ship after tier-S
         tier-B = good, not urgent
         tier-C = nice but deprioritized
         tier-D = close or downscope (grooming candidates)
     - For every open issue, propose a tier based on its groomed body, scope, and strategic value — independent of its current label.
     - Present a single diff table (issue → current tier → proposed tier → one-line justification) for every issue where the proposal differs.
     - Walk the diff with me one row at a time; on approval apply via
         gh issue edit <n> --remove-label tier-X --add-label tier-Y
       No silent batch updates.

5. Apply approved edits via `gh issue edit` / `gh issue comment` / `gh issue close --reason "not planned"`. One change at a time; no silent batch updates.

6. End with a short report: edges added, edges removed, dups closed, tier reassignments applied, remaining smells you didn't auto-fix.

Constraints:
- Read-only on code. Backlog edits only.
- Never close without my OK.
- If Round 1 wasn't run on an issue (no `groomed` label), skip it and list at the end — Round 2 assumes bodies are already clean.

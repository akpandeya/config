Round 3: cross-link audit on the groomed backlog. Round 1 made each issue self-contained; now make the *graph* correct.

Read `CLAUDE.md` first (especially the backlog/roadmap section and the "Two-axis backlog scheme" tier rubric) before doing anything else.

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
     - **leftover epic that wasn't split by the design pass** → split now (see step 3a)
     - missing or wrong `Model:` annotation when the issue is clearly out of band for the default tier (huge refactor with no `Model: opus`, or a trivial mechanical edit with no `Model: haiku`) → propose adding/removing the second metadata line. Same format as `Blocked by:` — line 2 of the body, value is `haiku` / `sonnet` / `opus` or a full Anthropic model ID. Omit the line when the default tier fits; the annotation is autopilot's most-specific routing signal and overrides both the CLI flag and the config tier default.

3a. **Epic safety net.** Design pass owns the primary epic-split (it runs before round-2). Round-2's job here is the safety net: catch any epic that slipped through because it didn't go through design pass at all (e.g. backend-only epic that round-1 marked `groomed` directly). An issue is an epic when ANY of:
     - body explicitly says "epic" or "break into sub-issues" in scope/non-goals
     - acceptance criteria span 3+ distinct surfaces (backend primitive + several UI surfaces + new page) where each could merge independently
     - estimated PR would touch 10+ files across unrelated modules
     - implementation guide reads as a "phase 1 / phase 2 / phase 3" plan
   When detected:
     - Propose a split into 2–5 sub-issues, each with its own Problem / Scope / ACs and a `Blocked by:` line pointing at any prior sub-issue.
     - Present the proposed split as: titles + 1-line scopes + dependency order. Wait for my approval before filing.
     - On approval: file each sub-issue with `gh issue create`. Each sub-issue inherits `groomed` if it doesn't need design; otherwise inherits `needs-design`. Carry an appropriate tier per sub-issue (often the parent's tier; sometimes the foundational sub-issue jumps to tier-S).
     - Update the parent issue body: add a `## Sub-issues` section listing the children with `Closes #N` keywords (so closing all sub-issues auto-closes the parent), and trim the parent's scope to "umbrella tracking — see sub-issues".
     - Add the `epic` label to the parent. Remove `groomed` from the parent (the epic itself isn't directly implementable).
     - The parent stays open until all sub-issues are closed.

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

6. End with a short report: edges added, edges removed, dups closed, tier reassignments applied, remaining smells you didn't auto-fix. Include a count of issues skipped because they lack the `groomed` label — if it's large, suggest running Round 1 first.

Constraints:
- Read-only on code. Backlog edits only.
- Never close without my OK.
- If previous round wasn't run on an issue (no `groomed` label), skip it — Round 3 assumes bodies are already clean.

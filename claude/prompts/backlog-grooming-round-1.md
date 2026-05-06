# Backlog grooming — Round 1: per-issue clarification

Paste into a fresh Claude Code session at the repo root. Goal: walk the GitHub backlog interactively so every open issue ends up **autonomous-Claude-ready** — a fresh Claude session given only the issue body + repo access could implement it without asking the human follow-up questions.

Conventions (jarvis-specific, see `CLAUDE.md` → "Three-axis backlog scheme"): tiers `S/A/B/C/D`, milestones `Wave 1…5`, `Blocked by: #N, #M` as the first line of the body. Adapt for other repos.

Run Round 1 first. When all open issues are groomed, switch to `backlog-grooming-round-2.md` for the cross-link audit.

---

You are grooming the backlog one issue at a time. Goal: make every open issue autonomous-Claude-ready — a fresh Claude session with only the issue body + repo access should be able to implement it without asking follow-ups.

Source of truth: read CLAUDE.md first (esp. the backlog/roadmap section). Issues are the backlog, not docs.

Workflow — repeat until no ungroomed open issues remain:

1. Pick the next open issue: highest tier, current milestone, missing the `groomed` label. Use:
     gh issue list --state open --search '-label:groomed' \
       --json number,title,labels,milestone --limit 50
   Show me the candidate; let me confirm or skip before you dive in.

2. Read the issue: `gh issue view <n>` plus all comments.

3. Read the code it touches. Use Explore subagents for anything non-trivial. Identify: which files/modules, existing utilities to reuse, related specs, prior art in git log.

4. Diagnose what's missing. A ready issue has:
     - Problem — one paragraph, why this exists
     - Scope — bulleted, concrete
     - Non-goals — what NOT to do
     - Acceptance criteria — testable, checkbox list
     - File pointers — paths the implementer should start from
     - Spec ref — if behaviour-bearing
     - First line: `Blocked by: #N, #M` (omit if none)
     - Tier label + milestone present

5. Ask me the minimum questions to fill gaps. Use AskUserQuestion, batch related questions, max 3-4 per issue. Skip questions you can answer from code reading. Push back if my answer feels under-specified — surface the tradeoff, don't rubber-stamp.

6. Rewrite the issue body. Show me the proposed new body before writing. On approval:
     gh issue edit <n> --body-file <tmp>
     gh issue edit <n> --add-label groomed

7. If during reading you discover the issue is stale, duplicate, or now irrelevant: STOP, surface it, ask whether to close / merge / downscope. Don't auto-close.

8. Move to the next issue. Keep going until I say stop or the queue is empty.

Constraints:
- Don't push commits, don't open PRs, don't change code — backlog only.
- Don't retier or re-milestone without explicit ask.
- One issue at a time. No batch rewrites in Round 1.

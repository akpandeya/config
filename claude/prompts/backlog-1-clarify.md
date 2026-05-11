You are grooming the backlog one issue at a time. Goal: make every open issue autonomous-Claude-ready — a fresh Claude session with only the issue body + repo access should be able to implement it without asking follow-ups.

Source of truth: read CLAUDE.md first (esp. the backlog/roadmap section). Issues are the backlog, not docs.

Workflow — repeat until no ungroomed open issues remain:

1. Pick the next open issue: highest tier, missing the `groomed` label. Use:
     gh issue list --state open --json number,title,labels --limit 50 \
       | jq '[.[] | select(.labels | map(.name) | contains(["groomed"]) | not)]'
   Show me the candidate; let me confirm or skip before you dive in.
   If the issue's `Blocked by:` line references open issues, note it — groom the blockers first or flag for the user.

2. Read the issue: `gh issue view <n>` plus all comments.

2a. **Stale/duplicate check** — before investing any effort: is this issue stale, superseded, or a duplicate of something else? If yes: STOP, surface it, ask whether to close / merge / downscope. Don't auto-close. Only continue to step 3 if the issue is clearly still live.

3. Read the code it touches. Use Explore subagents for anything non-trivial. Identify: which files/modules, existing utilities to reuse, related specs, prior art in git log.

4. Diagnose what's missing. A ready issue has:
     - **Title** — short, declarative, reads well as a roadmap line. The auto-filed feedback titles are usually narrative ("AI summary is probably using stand up mentions in thread") — rewrite to imperative/declarative ("Exclude standup mentions from AI summary input"). Keep under ~70 chars. Always rewrite the title alongside the body; don't leave the original wording in place just because it's already there.
     - Problem — one paragraph, why this exists
     - Scope — bulleted, concrete
     - Non-goals — what NOT to do
     - Acceptance criteria — testable, checkbox list
     - File pointers — paths the implementer should start from
     - Spec ref — if behaviour-bearing
     - First line: `Blocked by: #N, #M` (use `Blocked by: —` if none)
     - Optional second metadata line: `Model: <name>` (e.g. `Model: haiku`, `Model: sonnet`, `Model: opus`, or a full Anthropic model ID). Include this ONLY when a non-default tier is clearly appropriate for the issue — large/risky refactors → `opus`, cheap mechanical edits → `haiku`. Omit the line entirely when the default tier is fine; autopilot falls through to the CLI flag and the config default. Never invent values; pick from the documented tiers or paste a full model ID. The annotation is autopilot's most-specific routing signal — it overrides both the CLI `--model` flag and the configured `heavy` tier.
     - Tier label present

5. Ask me as many questions as needed to fill gaps. Use AskUserQuestion, batch related questions, max 3-4 per issue. Skip questions you can answer from code reading. Push back if my answer feels under-specified — surface the tradeoff, don't rubber-stamp.

5a. **Design-heavy?** If the issue carries non-trivial UI/UX judgement that's better handled in a dedicated design pass (multiple plausible layouts, novel components, mockups worth comparing, end-to-end flow redesigns), do NOT design it inline. Pin down everything else (problem, scope, non-goals, acceptance criteria, file pointers), but leave the *visual/interaction* spec to the design pass. Add the `needs-design` label and a `## Design pass` section to the body listing what specifically needs designing. Light UI ("add a list/section to an existing settings page", "add a button that calls an endpoint") does NOT need this label. When in doubt, ask me.

6. Rewrite the title AND the body. Show me both before writing. On approval:
     gh issue edit <n> --title "<new title>" --body-file <tmp>
     # If the issue is design-heavy (step 5a):
     gh issue edit <n> --add-label needs-design
     # ELSE (no design pass needed) — only then is it autonomous-ready:
     gh issue edit <n> --add-label groomed
   The `groomed` label means "autonomous-Claude-ready". Issues that still need a design pass are NOT autonomous-ready — the design pass adds `groomed` after resolving the visuals. Never apply both `groomed` and `needs-design` at once.

7. Move to the next issue without approval. Keep going until I say stop or the queue is empty. You can continue going until you need my input.

You can start now and keep selecting any issue you like and keep going from there.

Constraints:
- Don't push commits, don't open PRs, don't change code — backlog only.
- Don't retier without explicit ask.
- One issue at a time. No batch rewrites in Round 1.

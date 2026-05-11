You are running a **design pass** on the backlog — turning groomed-but-visually-unspecified issues into autonomous-implementation-ready specs with concrete UI/UX direction. This runs after `backlog-grooming-round-1` and before implementation.

Source of truth: read CLAUDE.md first. Issues already groomed have problem/scope/ACs; your job is to add the visual + interaction spec.

## Pickup query

Filter to issues that need design and aren't yet groomed (i.e. round-1 left them blocked on visuals):

```
gh issue list --state open --label needs-design --json number,title,labels --limit 50 \
  | jq '[.[] | select(.labels | map(.name) | contains(["groomed"]) | not)]'
```

Pick the top candidate yourself — don't ask which one. Prioritisation: highest tier first (S → A → B → C → D, untiered last), and prefer smaller scope on ties. State the pick in one sentence and dive in. If the queue is empty, stop.

Note: `needs-design` and `groomed` are mutually exclusive on open issues. Round-1 grooming applies `needs-design` and *withholds* `groomed` for design-heavy issues. The design pass resolves the visuals, then promotes the issue to autonomous-ready by removing `needs-design` and adding `groomed`.

## Workflow per issue

1. Read the full issue: `gh issue view <n>` + all comments. Pay attention to the `## Design pass` section — that's the brief.

1a. **Is this an epic?** Design pass owns epic-splitting (round-1 produces the issue with `needs-design`; design pass runs *before* round-2, so round-2 audits a clean backlog of small issues). An issue is an epic when ANY of:
     - body explicitly says "epic" or "break into sub-issues" in scope/non-goals
     - acceptance criteria span 3+ distinct surfaces (backend primitive + several UI surfaces + new page) where each could merge independently
     - design would naturally produce a multi-phase plan
   If detected:
     - STOP the design pass — don't design the whole thing as one spec.
     - Propose a split: 2–5 sub-issues, each with its own Problem / Scope / ACs and `Blocked by:` line. Titles + 1-line scopes + dependency order.
     - Wait for my approval, then file with `gh issue create`. Carry `needs-design` on sub-issues that genuinely need design (often the UI ones); leave `groomed` off for those, add `groomed` directly for the backend-primitive sub-issues that don't need design.
     - Update the parent: add `## Sub-issues` section with `Closes #N` keywords, add the `epic` label, trim parent scope to umbrella tracking. Remove `needs-design` from the parent (the epic itself doesn't get designed; its sub-issues do).
     - Move on to the next item in the design queue. The new design-needing sub-issues will surface for design pass on their own turn.

2. Read the code it touches (use Explore subagents for non-trivial flows). Identify: existing components, design tokens / Tailwind utilities in use, routing/state patterns, prior art for similar screens. Do NOT redesign things outside the issue scope.

3. **Use the `frontend-design` skill** for layout/visual work. Generate 2-3 alternative directions when the design space is genuinely open; one direction when constraints already narrow it. Ask me to pick before going deep on one.

4. Surface concrete artifacts:
   - ASCII or markdown mockups of the screen(s) / component(s).
   - Interaction notes: keybindings, focus order, empty states, error states, loading states, undo affordances.
   - Component decomposition: which existing components to reuse, which to add, where they live.
   - Data shape: what the API needs to return / accept for the UI to work, even if backend ACs already exist.
   - Accessibility: tab order, aria labels for non-trivial controls.

5. Push back where ACs and visuals conflict. If the design pass exposes a missed requirement or a flawed AC, fix the issue body — don't paper over it.

6. Append a `## Design spec` section to the issue body with the resolved direction (mockups + interaction notes + component plan). Keep what's already in the body; replace only the `## Design pass` brief with `## Design spec`. If round 1 omitted the optional `Model: <name>` metadata line and the design pass surfaces a clear reason to route this issue to a non-default model tier (`haiku` / `sonnet` / `opus`, or a full Anthropic model ID), insert it as the second metadata line — immediately after `Blocked by:`. Omit when the default tier still fits. Show me before writing. On approval:
   ```
   gh issue edit <n> --body-file <tmp>
   gh issue edit <n> --remove-label needs-design
   gh issue edit <n> --add-label groomed
   ```
   Promoting to `groomed` (with `needs-design` removed) is the signal that the issue is now autonomous-Claude-ready.

7. Move to the next issue without re-confirming. Keep going until I stop you or the queue is empty.

## Constraints

- Don't push commits, don't open PRs, don't write code — backlog only.
- Don't retier or re-scope ACs without flagging the change explicitly.
- Use the `frontend-design` skill when generating mockups; don't roll your own from scratch.
- One issue at a time. No batch rewrites.

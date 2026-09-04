You are running unattended overnight on the **jarvis repo**. Ship as many `groomed` GitHub issues as you can, in dependency-aware order. You are **autonomous** — never pause for user input. If the user happens to wake up and chimes in, just incorporate it and keep going.

If a skill or tool misbehaves (ci-observer short-circuits, pr-watch hangs, etc.), find a workaround (e.g. `gh pr checks <n> --watch`) and carry on. Don't get stuck.

# Step 1 — Build the queue (dependency tree first, tier second)

```bash
gh issue list --label groomed --state open --json number,title,body,labels --limit 200
```

For each issue:
- Parse the first body line `Blocked by: #N, #M` (case-insensitive; `—`/`-`/`none` means no blockers).
- Tier from labels (`tier-S` < `tier-A` < … < `tier-D`).

Build a DAG. Then:
1. If a blocker is **closed** or **not in the groomed set**, treat it as resolved (closed) or external (skip the dependent + ping).
2. Topologically sort. **Dependency wins over tier** — a blocker is always scheduled before its dependents.
3. Tie-break inside a topo level by tier, then issue number.
4. Cycles → ping Matrix, skip every issue in the cycle.

Write the ordered queue to `~/.jarvis/night-run/$(date -u +%Y%m%dT%H%M%S)/plan.md` and ping Matrix once with the kickoff list.

# Step 2 — Work the queue, one ticket at a time

For each issue:

1. **Pickup ping** — `kind=autonomous.pickup`, title `Picked up #<N> — <title>`, body `tier <X> · <branch>`.
2. **Branch** from fresh default branch: `feat/night-run/<N>-<slug>` (slug ≤ 40 chars). If branch already exists, skip + ping.
3. **Explore** before coding (Explore subagent) — find relevant files, specs, prior art.
4. **Implement.** Keep diffs minimal. SDD: new modules need a spec in `docs/specs/`; tag tests `@pytest.mark.spec("module.F<n>")`. Run `uv run ruff check . && uv run ruff format . && uv run pytest` until green.
5. **PR** via `pr-create` skill, body includes `Closes #<N>`. After non-draft PR opens → ping `kind=pr_ready` with `#N · <title> · <url>`.
6. **CI** via `pr-watch` then `ci-fix`. Up to 5 attempts. Ping after each red. After 5 stuck → ping `CI stuck — needs human review` and move on. Don't block the rest of the queue on one ticket.
7. **Merge** via `pr-merge` (personal repo, squash). Then ping `Done: #<N>`.
8. **Refresh queue** — re-run the `gh issue list` query. Newly-unblocked issues get inserted at the right topo position. Issues closed mid-run get dropped.

# Step 3 — Highlight decisions

Whenever you make a call that isn't explicit in the ticket, or the ticket itself contains a weird/questionable decision, ping Matrix **before** acting:

```bash
jarvis bridge send --scope personal --kind manual \
  --title "⚠️ Decision: #<N> — <what you're doing or what's odd>" \
  --body "Reason: <one line>"
```

Examples that warrant this:
- Ticket doesn't mention how to handle X but the codebase forces a choice.
- Ticket asks for behaviour that contradicts an existing spec.
- You're touching something cross-cutting the ticket didn't mention (schema, deps, CI, release scripts).

This is the part the user will scan first in the morning — don't bury surprises in commit messages.

# Step 4 — Summaries

Send a short summary ping when something meaningful happens (not after every step):
- Kickoff: queue list.
- Mid-run checkpoint every ~3 ticket transitions: shipped so far / stuck / remaining.
- Final digest when the queue is empty or kill-switch trips: ✅ shipped, ⏭ skipped (with one-line reasons), ⚠ stuck PRs needing review.

Also write `~/.jarvis/night-run/<ts>/digest.md` at the end.

# Hard rules

- Never push to main; PR + CI required for everything.
- No `--no-verify`, no force-push.
- Don't touch `scripts/release.sh` or cut a release.
- Check `~/.jarvis/night-run.disabled` before each ticket — if it exists, ping `kill switch` and stop cleanly.
- Don't mock the database in tests (integration tests must hit real sqlite).
- Skip + ping (don't guess) for: stale tickets, duplicates, ambiguous acceptance criteria, "discuss with X" notes.

Now: read `CLAUDE.md` and `docs/specs/CONSTITUTION.md`, build the queue, and go. Do not wait for my input after this.

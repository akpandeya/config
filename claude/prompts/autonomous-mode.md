# Autonomous mode — jarvis repo

Paste into a fresh Claude Code session in `~/code/personal/jarvis`.

---

You are running in **autonomous mode** on the jarvis repo. Work the groomed backlog without per-PR check-ins.

**Pickup rule:** must carry the `groomed` label, then earliest wave first, then tier within the wave (S → A → B → C → D), then zero open blockers (first body line `Blocked by: #N` must be empty or all #N closed).

```bash
# Discover current wave milestone names:
gh api repos/:owner/:repo/milestones --jq '.[].title'

# Walk the groomed queue in priority order:
for wave in "Wave 1 — Now triage" "Wave 2 — Soon" "Wave 3 — Provenance & Now polish" "Wave 4 — Claude ergonomics" "Wave 5 — Tier-C batch"; do
  for tier in tier-S tier-A tier-B tier-C; do
    gh issue list --state open --label groomed --label "$tier" --milestone "$wave" \
      --json number,title,body \
      --jq '.[] | "\(.number)\t\(.title)\t\(.body | split("\n")[0])"'
  done
done
```

Skip anything without `groomed` — that's user grooming work, not autonomous-mode work. Skip blocked issues.

For each issue you pick:

1. `gh issue view <n>` — read it including the `Blocked by:` line.
2. Branch from fresh `main`: `git checkout main && git pull && git checkout -b <prefix>/<short-slug>` (`feat/`, `fix/`, etc.).
3. Implement. Add/update spec in `docs/specs/` if it's a new module (SDD — see CONSTITUTION.md). Tag tests with `@pytest.mark.spec("module.F<n>")`.
4. `uv run ruff check . && uv run ruff format . && uv run pytest` — must be green.
5. Open PR with `Closes #<n>` in the body. Use the `pr-create` skill.
6. Watch CI via the `pr-watch` skill. ci-observer is suspect — verify it actually blocks; if it short-circuits, fall back to `gh pr checks <n> --watch`.
7. When green, squash-merge (personal repo — use `pr-merge` skill).
8. **After merge: send a Matrix progress ping** using:

   ```bash
   uv run python <<'PY'
   from jarvis.bridge import BridgeEvent, configure_default_matrix, default_router
   from jarvis.config import JarvisConfig
   configure_default_matrix(JarvisConfig.load())
   default_router().send(BridgeEvent(
       kind="autonomous.progress",
       scope="personal",
       title="PR #<N> merged: <issue title>",
       body="<2–3 lines on what changed and which issue closed>",
   ))
   PY
   ```

9. **Compact the conversation** before picking the next issue:

   ```
   /compact Keep: the autonomous-mode rules from the original prompt, the Matrix heredoc, and the running list of merged PRs (#N — title). Drop: per-file diffs, tool output, exploration transcripts from the just-merged issue.
   ```

10. Loop to the next groomed issue.

**Stop conditions:**
- No unblocked groomed issues remain → send final summary and stop.
- A PR's CI fails twice in a row on a non-trivial issue → stop and ask.
- Anything destructive or cross-cutting (schema migration, dep bump, branch-protection change) → stop and ask.

**Final Matrix summary** (send when stopping for any reason, same heredoc form):
- One line per merged PR: `#N — <title>`
- Total count merged
- Any issues skipped (with reason: blocked / failed CI / out-of-scope)
- Time window of the run

**Repo rules to honor without prompting:**
- Never push to main; PR + CI required.
- No `--no-verify`, no force-push.
- Don't bump `pyproject.toml` by hand — only `scripts/release.sh`. No releases this run unless an issue requires it.

Begin by walking the groomed queue with the loop above and stating which issue you're picking and why.

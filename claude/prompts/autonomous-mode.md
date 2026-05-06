You are running in **autonomous mode** on the jarvis repo. Work the groomed backlog without per-PR check-ins.

**Pickup rule:** must carry the `groomed` label, then highest tier first (S → A → B → C → D), then zero open blockers (first body line `Blocked by: #N` must be empty/`—` or all #N closed).

**Start by collecting the batch (no code yet).** Walk the groomed queue and gather up to 5 issues:

```bash
for tier in tier-S tier-A tier-B tier-C; do
  gh issue list --state open --label groomed --label "$tier" \
    --json number,title,body \
    --jq '.[] | "\(.number)\t\(.title)\t\(.body | split("\n")[0])"'
done
```

Skip anything without `groomed` — that's user grooming work, not autonomous-mode work. Skip blocked issues. Stop collecting once you have 5.

Once you have the list, **announce it on Matrix before touching any code**:

```bash
uv run python <<'PY'
from jarvis.bridge import BridgeEvent, configure_default_matrix, default_router
from jarvis.config import JarvisConfig
configure_default_matrix(JarvisConfig.load())
default_router().send(BridgeEvent(
    kind="autonomous.start",
    scope="personal",
    title="Autonomous run starting — <N> issues queued",
    body="<bulleted list: #N <title> for each issue collected, no URLs>",
))
PY
```

Then work through each issue in order:

0. **Ping Matrix** — issue URL and title so it's tappable:

   ```bash
   uv run python <<'PY'
   from jarvis.bridge import BridgeEvent, configure_default_matrix, default_router
   from jarvis.config import JarvisConfig
   configure_default_matrix(JarvisConfig.load())
   default_router().send(BridgeEvent(
       kind="autonomous.issue_start",
       scope="personal",
       title="Starting: <issue title>",
       body="<https://github.com/owner/repo/issues/N>",
   ))
   PY
   ```
1. `gh issue view <n>` — read it including the `Blocked by:` line.
2. Branch from fresh `main`: `git checkout main && git pull && git checkout -b <prefix>/<short-slug>` (`feat/`, `fix/`, etc.).
3. Implement. Add/update spec in `docs/specs/` if it's a new module (SDD — see CONSTITUTION.md). Tag tests with `@pytest.mark.spec("module.F<n>")`.
4. `uv run ruff check . && uv run ruff format . && uv run pytest` — must be green.
5. Open PR with `Closes #<n>` in the body. Use the `pr-create` skill.
6. Watch CI via the `pr-watch` skill. ci-observer is suspect — verify it actually blocks; if it short-circuits, fall back to `gh pr checks <n> --watch`.
7. When green, squash-merge (personal repo — use `pr-merge` skill).
8. **After merge: ping Matrix** with PR link and title:

   ```bash
   uv run python <<'PY'
   from jarvis.bridge import BridgeEvent, configure_default_matrix, default_router
   from jarvis.config import JarvisConfig
   configure_default_matrix(JarvisConfig.load())
   default_router().send(BridgeEvent(
       kind="autonomous.progress",
       scope="personal",
       title="Merged: <PR title>",
       body="<PR URL>  ·  Closes #<n>",
   ))
   PY
   ```
9. Loop to the next issue in the batch.

**Stop conditions:**
- All issues in the batch merged → send final summary and stop.
- User sends any message in this session → finish the in-flight issue, send final summary, stop.
- No unblocked groomed issues remain → send final summary and stop.
- A PR's CI fails twice in a row on a non-trivial issue → stop and ask.
- Anything destructive or cross-cutting (schema migration, dep bump, branch-protection change) → stop and ask.

**Final Matrix summary** (send when stopping for any reason):

```bash
uv run python <<'PY'
from jarvis.bridge import BridgeEvent, configure_default_matrix, default_router
from jarvis.config import JarvisConfig
configure_default_matrix(JarvisConfig.load())
default_router().send(BridgeEvent(
    kind="autonomous.done",
    scope="personal",
    title="Autonomous run done — <N> merged (up to 5)",
    body="""
**What changed:**
<1–2 sentences per merged issue: what is functionally different in the codebase, no PR links or issue numbers>

**What to test:**
- <bullet per key scenario a human should smoke-test manually>

**Skipped:** <#N — reason> (omit this section if nothing was skipped)
""",
))
PY
```

**Repo rules to honor without prompting:**
- Never push to main; PR + CI required.
- No `--no-verify`, no force-push.
- Don't bump `pyproject.toml` by hand — only `scripts/release.sh`. No releases this run unless an issue requires it.

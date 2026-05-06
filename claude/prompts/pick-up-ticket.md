Pick up and implement a single ticket end-to-end.

**Detect profile first:**

```bash
SCOPE=$(~/.claude/scripts/repo-scope-for-cwd.sh)
```

- `personal` → ticket is a GitHub issue number; read with `gh issue view <n> --comments`
- `work` → ticket is a Jira key (e.g. `PROJ-123`); read with `jira issue view <KEY>`

If no ticket was given, ask the user for the number / key before continuing.

---

## Step 1 — Read the ticket and the code

Read the ticket in full (including all comments). Then **always explore the relevant code** via an Explore subagent before forming any opinion — never assume from the ticket text alone. Identify: which files/modules, existing utilities to reuse, related specs, prior art in git log.

If the ticket looks stale, duplicate, or out-of-scope for this repo: stop, surface it, ask the user whether to close / skip / rescope. Don't proceed silently.

## Step 2 — Clarify

Ask the minimum questions to fill genuine gaps (max 3–4, batched). Push back if an answer feels under-specified — surface the tradeoff, don't rubber-stamp.

Skip questions you can answer from code reading.

## Step 3 — Announce start

```bash
# personal
jarvis bridge send --scope personal --kind manual \
  --title "Starting: <title>" \
  --body "<https://github.com/owner/repo/issues/N>"

# work
jarvis bridge send --scope work --kind manual \
  --title "Starting: <KEY> — <title>" \
  --body "<Jira URL>"
```

## Step 4 — Branch

Detect the default branch (don't hardcode `main` or `master`):

```bash
BASE="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##' || true)"
[ -z "$BASE" ] && git remote set-head origin --auto 2>/dev/null && \
  BASE="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##' || true)"
[ -z "$BASE" ] && BASE="$(gh repo view --json defaultBranchRef --jq .defaultBranchRef.name 2>/dev/null || true)"
git checkout "$BASE" && git pull && git checkout -b <prefix>/<short-slug>
```

Use `feat/`, `fix/`, `chore/` prefixes as appropriate.

## Step 5 — Implement

Follow the project's `CLAUDE.md` for lint, format, and test commands. Add/update specs if the project tracks them. All checks must be green before opening a PR.

Send intermittent progress pings **only at meaningful milestones** (core logic done, tests passing — not on every file edit):

```bash
jarvis bridge send --scope "$SCOPE" --kind autonomous.progress \
  --title "Progress: <title>" \
  --body "<what just landed>"
```

## Step 6 — Open PR

Use the `pr-create` skill. Include `Closes #<n>` (personal) or the Jira key in the PR body (work).

## Step 7 — Notify PR ready

```bash
jarvis bridge send --scope "$SCOPE" --kind pr_ready \
  --title "PR ready: <PR title>" \
  --body "<PR URL>$([ "$SCOPE" = work ] && echo '\nSuggested reviewers: <from CLAUDE.md or git log>')"
```

## Step 8 — CI

Watch CI via the `pr-watch` skill. If it goes red, use the `ci-fix` skill. Attempt up to **5 times** (both personal and work):

```bash
# after each failed attempt:
jarvis bridge send --scope "$SCOPE" --kind pr_ci_red \
  --title "CI attempt <N>/5 failed: <PR title>" \
  --body "<failure summary>"

# after 5 failures — stop:
jarvis bridge send --scope "$SCOPE" --kind pr_ci_red \
  --title "CI stuck after 5 attempts: <PR title>" \
  --body "<PR URL> — needs human attention"
```

## Step 9 — Human review comments

**Never reply directly to human PR comments** (personal or work). Instead:

- Read all comments; compose a draft response and/or action list for each.
- Send the drafts via bridge and wait for the human to act:

```bash
jarvis bridge send --scope "$SCOPE" --kind manual \
  --title "Review notes: <PR title>" \
  --body "<drafted responses and action items per comment>"
```

- For actionable feedback: implement the fix, push, then notify again.

## Step 10 — Done

When CI is green and the PR is merged (personal: use `pr-merge` skill; work: human merges):

```bash
# personal
jarvis bridge send --scope personal --kind manual \
  --title "Done: <title>" \
  --body "Merged <PR URL>"

# work
jarvis bridge send --scope work --kind manual \
  --title "Done: <KEY> — <title>" \
  --body "PR merged (or awaiting human merge): <PR URL>"
```

---

**Hard rules:**
- Never push directly to the default branch.
- No `--no-verify`, no force-push.
- Never post replies to human PR comments — compose drafts and notify only.

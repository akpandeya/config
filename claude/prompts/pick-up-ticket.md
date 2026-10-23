---
persona: autopilot
---

Pick up and implement a single ticket end-to-end.

This explicit workflow authorizes implementation, relevant CI repair, publication
and the notifications described below. It does not override plan-only mode,
repository policy or a narrower user request. Pinging a decision is not consent
to expand scope. Work merges still require a human.

**Detect profile first:**

```bash
SCOPE=$(~/.claude/scripts/repo-scope-for-cwd.sh)
```

- `personal` → ticket is a GitHub issue number; read with `gh issue view <n> --comments`
- `work` → ticket is a Jira key (e.g. `PROJ-123`); read with `jira issue view <KEY>`

If no ticket was given, ask the user for the number / key before continuing.

---

## Step 1 — Read the ticket and the code

Read the ticket and relevant code before forming an opinion. Trace a continuous
flow directly; delegate only substantial independent investigation when useful.
Identify affected files, reusable helpers, specs and prior art.

If the ticket looks stale, duplicate, or out-of-scope for this repo: stop, surface it, ask the user whether to close / skip / rescope. Don't proceed silently.

## Step 2 — Clarify

Ask one focused question at a time for genuine gaps. Explain the tradeoff plainly.

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
test -n "$BASE" && git checkout "$BASE" && git pull --ff-only && git checkout -b <prefix>/<short-slug>
```

- **Personal:** use `feat/`, `fix/`, `chore/` prefixes as appropriate.
- **Work:** use `feature/<JIRA-KEY>-<short-slug>` or `patch/<JIRA-KEY>-<short-slug>` (feature for new functionality, patch for fixes).
- Check status and workspace ownership before switching. Preserve unrelated
  local changes. Resolve/create the real work ticket before creating the branch.

## Step 5 — Implement

Follow the project's `CLAUDE.md` for lint, format, and test commands. Add/update specs if the project tracks them. All checks must be green before opening a PR.

Send intermittent progress pings **only at meaningful milestones** (core logic done, tests passing — not on every file edit):

```bash
jarvis bridge send --scope "$SCOPE" --kind autonomous.progress \
  --title "Progress: <title>" \
  --body "<what just landed>"
```

## Step 6 — Open PR

Use the `pr-create` skill. Include `Closes #<n>` (personal) or the Jira key in the PR body (work). All PR bodies must include the signature footer `\n\n> _posted by autopilot_`.

## Step 7 — Notify PR ready

```bash
jarvis bridge send --scope "$SCOPE" --kind pr_ready \
  --title "PR ready: <PR title>" \
  --body "<PR URL>$([ "$SCOPE" = work ] && echo '\nSuggested reviewers: <from CLAUDE.md or git log>')"
```

## Step 8 — CI

Watch CI via the read-only `pr-watch` skill. This end-to-end workflow separately
authorizes `ci-fix` for the exact PR, including scoped commits/pushes. Attempt up
to **5 times**; merely invoking pr-watch elsewhere never authorizes repair.

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

- **Personal:** treat comments as input — implement the fix directly, or draft a reply if clarification is needed before acting.
- **Work:** never reply directly to PR comments. Read all comments, compose a draft response and/or action list for each, and send via bridge so the human can post it:

```bash
jarvis bridge send --scope "$SCOPE" --kind manual \
  --title "Review notes: <PR title>" \
  --body "<drafted responses and action items per comment>"
```

For actionable feedback on either profile: implement the fix, push, then notify again.

## Step 10 — Done

When CI is green, report the actual state: merged only after confirmation
(personal: pr-merge); work PRs may instead be ready for human review/merge.

```bash
# personal
jarvis bridge send --scope personal --kind manual \
  --title "Done: <title>" \
  --body "Merged <PR URL>"

# work
jarvis bridge send --scope work --kind manual \
  --title "Ready for human review: <KEY> — <title>" \
  --body "Draft PR; awaiting human review and merge: <PR URL>"
```

---

**Hard rules:**
- Never push directly to the default branch.
- No `--no-verify`, no force-push.
- Work only: never post replies to human PR comments — compose drafts and notify via bridge.
- Before actions outside the authorized scope, ask for approval and stop that
  action. A decision ping can explain a routine in-scope choice, not authorize it:
  ```bash
  jarvis bridge send --scope "$SCOPE" --kind manual \
    --title "⚠️ Decision: <what you are about to do>" \
    --body "Reason: <one line why>"
  ```
- All PR bodies and any issue/PR comments authored by you must include the signature footer `\n\n> _posted by autopilot_`.

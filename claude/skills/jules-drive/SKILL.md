---
name: jules-drive
description: Drive a decomposed GitHub issue to completion using Jules — Haiku orchestrates, Jules implements each task via jules remote new, PR created per task with optional Sonnet or agy review. Usage: /jules-drive <owner/repo> <issue-number> [--reviewer=sonnet|agy]
allowed-tools: Bash, Read, Write, Agent
argument-hint: "<owner/repo> <issue-number> [--reviewer=sonnet|agy]"
---

Orchestrate autonomous implementation of a GitHub issue using Jules. Each task
from the decomposed manifest is dispatched via `jules remote new`, polled until
complete, and the patch applied + reviewed + merged before the next task starts.

## Parse arguments

`$ARGUMENTS` format: `<owner/repo> <issue-number> [--reviewer=sonnet|agy]`

Extract `REPO`, `ISSUE_NUM`, and optionally `REVIEWER` from `$ARGUMENTS`.
`SLUG` = owner + "-" + repo-name + "-issue-" + issue-number.
`PROMPT_DIR` = `~/.claude/agy-prompts/$SLUG`.

## Check for manifest

If `$PROMPT_DIR/manifest.json` does not exist, tell the user:
"No decomposition found. Run `/issue-decompose $REPO $ISSUE_NUM` first."
Then stop.

## Ask reviewer if not provided

If `--reviewer` was not in `$ARGUMENTS`, ask:

Who should review each PR before merging?
- **Sonnet** — spawns a Sonnet code-review agent; thorough, best for complex changes (~2 min per PR)
- **agy** — runs a second autonomous agy pass to check acceptance criteria and fix issues (~3–5 min per PR)

## Spawn Haiku orchestrator

Spawn a **Haiku** Agent (`model: haiku`) with the full manifest contents and
this orchestration prompt:

---
You are a Haiku orchestrator. Drive each task in the manifest to completion
using the Jules CLI. Work through tasks in dependency order (respect `blockedBy`).
Skip tasks already `status: merged`. Update manifest status as you go.

**Repo path:** read from manifest `repoPath`.
**Repo remote:** `$REPO`
**Reviewer:** `$REVIEWER` (sonnet or agy)
**Prompt dir:** `$PROMPT_DIR`
**Cool-down:** `sleep 900` between tasks (skip after the last task)

For each pending task:

### a. Sync main
```bash
cd <repoPath>
git checkout main && git pull --ff-only
```

### b. Dispatch to Jules
Append these standing rules to the task prompt before dispatching:

```
IMPORTANT JULES RULES (non-negotiable):
- Do NOT run or wait for Playwright/e2e tests — only npm run build + unit tests
- Do NOT pause for human feedback at any point — make autonomous judgment calls
- Do NOT modify package.json / package-lock.json / yarn.lock
- Open a PR titled: <task title>; body must end with "Closes #$ISSUE_NUM"
- Run npm run build and unit tests before opening the PR
```

```bash
SID=$(cat $PROMPT_DIR/<task.id>.md | jules remote new --repo $REPO 2>&1 | grep "^ID:" | awk '{print $2}')
echo "Jules session: $SID"
gh issue comment $ISSUE_NUM --repo $REPO \
  --body "Jules session \`$SID\` dispatched for <task.id>: <task.title>"
```

### c. Poll Jules (every 5 min)
```bash
while true; do
  STATUS=$(jules remote list --session 2>/dev/null | grep "$SID" | \
    grep -oE "Completed|Awaiting User Feedback|Paused|Failed|In Progress|Planning" | head -1)
  echo "$(date): $STATUS"
  if echo "$STATUS" | grep -qE "Completed|Awaiting|Paused|Failed"; then break; fi
  sleep 300
done
```

If status is **Failed** or **Paused** with no usable output: log warning, mark
task as `status: skipped`, continue to next task.

If status is **Awaiting User Feedback**: Jules is blocked. Try to pull the patch
anyway and proceed — the "Awaiting" state often means Jules finished but didn't
auto-open a PR.

### d. Pull Jules patch
```bash
jules remote pull --session $SID > /tmp/jules_<task.id>.patch
```

Check if Jules already opened a PR:
```bash
gh pr list --repo $REPO --head <some-branch> --state open --json number,headRefName
```
If Jules opened a PR, use it. If not, apply patch manually.

### e. Apply patch (selective — skip junk)
```bash
cd <repoPath>
git checkout -b <task.branch>
# Apply only real source files; skip Python scripts, lockfiles, dev_output.log
git apply /tmp/jules_<task.id>.patch \
  --include="frontend/src/**" \
  --include="backend/src/**" \
  --include="backend/db.js" \
  --include="mocks/**" \
  --include="e2e/**" 2>/dev/null || true
# Restore lockfiles if touched
git checkout main -- package-lock.json package.json 2>/dev/null || true
git checkout main -- frontend/package-lock.json frontend/package.json 2>/dev/null || true
# Remove any .py patch scripts Jules left
find . -maxdepth 2 -name "*.py" -newer package.json -delete 2>/dev/null || true
rm -f dev_output.log
```

If `git diff --stat` shows nothing changed: log warning, skip task, continue.

### f. Verify build + tests
```bash
cd <repoPath>/frontend && npm run build && npm run test -- --run
cd <repoPath>/backend && npm test
```
Fix small errors inline if possible.

### g. Commit
```bash
git add <changed files>
git commit -m "<task title>

Jules session $SID

Closes #$ISSUE_NUM

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

### h. Push + PR (if Jules didn't open one)
```bash
git push -u origin <task.branch>
gh pr create --base main --head <task.branch> \
  --title "<task title>" \
  --body "$(cat <<'EOF'
## Summary
<bullet points from acceptance criteria>

## Test plan
- [x] Frontend build: clean
- [x] Unit tests: pass

Jules session: `$SID`
Closes #$ISSUE_NUM

🤖 Generated with Claude Code
EOF
)"
```

### i. Review

**If reviewer = sonnet:**
Spawn a Sonnet Agent (`model: sonnet`) with this prompt:
"Review the open PR on branch `<task.branch>` in repo `<repoPath>`.
Read `git diff main...<task.branch>`. Check each acceptance criterion from
the task file `$PROMPT_DIR/<task.id>.md`. Run `npm run build` and unit tests.
Fix any issues directly in the working tree, then `git add && git commit --amend
--no-edit && git push --force-with-lease`. Report what you fixed."

**If reviewer = agy:**
```bash
agy --dangerously-skip-permissions --print-timeout 15m -p "
Review the changes on git branch <task.branch> in <repoPath>.
Read: git diff main...<task.branch>
Check every acceptance criterion in $PROMPT_DIR/<task.id>.md.
Run: cd frontend && npm run build && npm run test -- --run && cd ../backend && npm test
Fix any issues. If you made fixes: git add <files> && git commit --amend --no-edit && git push --force-with-lease.
Report what you found and fixed. Then stop.
"
```

### j. Wait for CI + merge
```bash
for i in $(seq 1 10); do
  STATUS=$(gh pr view --json mergeStateStatus -q '.mergeStateStatus')
  if [ "$STATUS" = "CLEAN" ]; then break; fi
  sleep 15
done
gh pr merge --squash --delete-branch
```

### k. Update manifest + cool-down
Update `$PROMPT_DIR/manifest.json` task status to `"merged"`.
If more tasks remain: `sleep 900`.

---

After all tasks complete, print a summary table of task → Jules session → PR number → status.
---

## After Haiku returns

Report the final summary to the user.

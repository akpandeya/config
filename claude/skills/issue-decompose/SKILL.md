---
name: issue-decompose
description: >-
  Decompose a GitHub issue into atomic tasks, filed as native sub-issues of the
  decomposed issue (the visible plan of record), with manifest + task files saved
  for drivers. The decomposer harness and model are chosen by the caller; defaults
  to Opus with extended thinking in Claude Code. Honors a verbatim agent-tasks spec
  in the issue body.
  Usage: /issue-decompose <owner/repo> <issue-number> [DECOMPOSER=<harness>:<model>] [--dry-run]
allowed-tools: Bash, Read, Write, Agent
argument-hint: "<owner/repo> <issue-number> [DECOMPOSER=<harness>:<model>] [--dry-run]"
---

Decompose a GitHub issue into small, atomic implementation tasks that can each be run independently
by any implementer harness. Each task is filed as a native sub-issue of the decomposed issue — the
sub-issue body is the task spec and the plan you can review on GitHub before anything runs. Driver
inputs (manifest + task files) are saved to
`${AGENT_PROMPTS_DIR:-$HOME/.local/share/agent-prompts}/<slug>/`
(harness-neutral XDG data home, same convention as nvim's py-scratch/sql-scratch).

Run `/epic-run` to decompose, implement and review in one go. Run this skill alone only to re-decompose
or to inspect the task list.

## Parse arguments

`$ARGUMENTS`: `<owner/repo> <issue-number> [DECOMPOSER=<harness>:<model>] [--dry-run]`

Example: `akpandeya/party-planner 72 DECOMPOSER=claude:opus`

- `REPO`, `ISSUE_NUM`, and `SLUG` = owner + "-" + repo name + "-issue-" + issue number.
- `PROMPT_DIR` = `${AGENT_PROMPTS_DIR:-$HOME/.local/share/agent-prompts}/$SLUG`.
- `DECOMPOSER` defaults to `claude:opus` when absent.
- `--dry-run`: run the decomposer, then print the sub-issues that would be filed
  (titles, `blockedBy`, target parent) and stop. Create nothing on GitHub; leave
  every `task.issue` unset.

## Locate repo

Run `gh repo view $REPO --json url` to confirm the repo exists. Find the local clone under the usual
project folders and set `REPO_PATH` to its absolute path.

`repoPath` is **required** in the manifest, because `epic-drive` and `epic-review` run git and the verify
commands there. If no clone is found, stop and ask the user for the path. The only exception is
decomposing without a clone (reading `CLAUDE.md` or `AGENTS.md` through
`gh api repos/$REPO/contents/CLAUDE.md`): then `repoPath` may be `null`, but the manifest is not runnable
until the user sets it, and `epic-drive` refuses a null `repoPath`.

## Run the decomposer

If `$PROMPT_DIR/manifest.json` already exists (a re-decompose), copy it to
`$PROMPT_DIR/manifest.prev.json` first — the decomposer rewrites the manifest from
scratch, and the publish step restores prior sub-issue numbers from the previous one.

Use the decomposer prompt below. It is the same prompt on every harness.

- **Same harness as this session, and a Claude model:** spawn an Agent with the model from
  `DECOMPOSER`, and with extended thinking requested.
- **Same harness, non-Claude model (e.g. OpenCode):** use that harness's subagent with the model.
- **Any other harness:**

  ```bash
  ~/.config/agent-context/scripts/run-harness.sh <harness> <model> decompose \
    "$REPO_PATH" "$PROMPT_DIR/decompose.prompt.md" "$PROMPT_DIR/logs/decompose.<harness>.log"
  ```

  Write the prompt below to `$PROMPT_DIR/decompose.prompt.md` first, and create `$PROMPT_DIR/logs` before
  the run. **Substitute `$ISSUE_NUM`, `$REPO` and `$PROMPT_DIR` with their actual values before writing
  the file**: the headless harness does not know these variables, so the literal text would stay
  unsubstituted in the prompt. The decomposer's cwd is `$REPO_PATH`, and `$PROMPT_DIR` is outside it:
  `run-harness.sh` passes the prompt file's directory to Claude with `--add-dir` so the decomposer can write
  there.

### Decomposer prompt

---
Think deeply before producing any output. Reason through file dependencies, hidden coupling and
failure modes before committing to a task breakdown. Do not output the task list until your reasoning
is complete.

You are decomposing GitHub issue into atomic implementation tasks.

**Issue:** Run `gh issue view $ISSUE_NUM --repo $REPO --json title,body,labels` and read the full output.

**FIRST, check for a verbatim task spec.** Inspect the issue body. If it contains the marker
`<!-- agent-decompose: verbatim -->` or an `## agent-tasks` heading, you are in **VERBATIM MODE**: the author
has already decomposed the work, and you MUST NOT re-derive, split, merge, reorder, drop or invent tasks.
Transcribe each task block **1:1** into one task file, preserving the author's boundaries exactly. Each
task block looks like:

```
### task-NN — <title>
- files: `path/a`, `path/b`
- blockedBy: none            # or a comma list like: task-01, task-02
- acceptance:
  - [ ] criterion 1
  - [ ] criterion 2
- context: 1–2 sentences for an autonomous agent.
```

In verbatim mode, use the block's `title`, `files`, `blockedBy`, `acceptance` and `context` verbatim in
the task-file template below, one `task-NN.md` per block, numbered exactly as authored. You may read the
named `files` only to enrich the `## Context` line. Still extract `standing-rules.md` from `CLAUDE.md` or
`AGENTS.md` and write `manifest.json`, one entry per block, with the authored `blockedBy`. Then STOP and skip
the normal-mode steps below.

If neither marker is present, proceed in normal mode.

**Standing rules:** Read `CLAUDE.md` or `AGENTS.md` in the repo root. Extract the project's own rules about
testing, style, DB and auth into `standing-rules.md`.

**Relevant files:** Infer which 3–5 source files the issue will touch. Read them.

**Decompose** (normal mode only) into N tasks, usually 1–5, where each task:
- has one coherent responsibility, with file boundaries derived from the code;
- has concrete acceptance criteria and the repository's verification;
- has an explicit `blockedBy: ["task-NN"]` list if it must come after another task;
- is self-contained enough for an autonomous agent to implement without questions.

**For each task**, write `$PROMPT_DIR/task-NN.md` with this template:

```
# <task title>

Working dir: <abs repo path>

## Acceptance criteria
- [ ] ...

## Relevant files
- `path/to/file` — <one-line role>

## Context
<1–2 sentences of why/what>

---
<paste standing rules here verbatim>

## Absolute rules (non-negotiable)
- Change dependency manifests only when the task requires it; update matching lockfiles
- Make routine implementation decisions, but stop for unresolved scope or destructive actions
- Run the repository's relevant verification, including end-to-end tests when required
- Do NOT open a PR. Implement, test, fix errors, then stop
```

**Also write:**
- `$PROMPT_DIR/standing-rules.md`, the extracted repo standing rules.
- `$PROMPT_DIR/manifest.json`:

```json
{
  "repo": "owner/repo",
  "issue": <number>,
  "repoPath": "<abs path or null>",
  "promptDir": "<abs path>",
  "tasks": [
    {
      "id": "task-01",
      "title": "...",
      "branch": "<type>/<N>-<slug>",
      "blockedBy": [],
      "status": "pending"
    }
  ]
}
```

`type` is `feat`, `fix`, `chore` or `docs` by the task's nature (default `feat`); `N` is the
decomposed issue's number (the publish step rewrites it to the task's own sub-issue number).
Branch naming matches issue-ship's `<type>/<issue>-<slug>`, so task branches and single-issue
branches look alike.

After writing all files, print the task list with titles, file counts and dependency order. Then stop.
---

## Publish sub-issues

Work through the manifest tasks **in order**. This step writes to GitHub; with `--dry-run`,
skip it entirely and instead print the list it would file (titles, `blockedBy`, parent
`#$ISSUE_NUM`) before showing the task list.

**Idempotency.** `task.issue` in the manifest means "already filed" — never create a
second issue for it. First restore state on a re-decompose: for every task id present in
`manifest.prev.json` with an `issue`, copy that `issue` (and its `branch`) into the new
manifest before doing anything else. Then match tasks by `id`:

- `issue` absent → file a new sub-issue (below), record it, move on.
- `issue` present and the regenerated body differs from the stored
  `$PROMPT_DIR/.body-<task.id>.md` → update in place:
  `gh issue edit <SUB> --repo $REPO --title "<title>" --body-file <new body>`, then
  overwrite the stored body file.
- `issue` present and the body is identical → skip.
- A filed sub-issue whose task id is gone from the manifest is an **orphan**: list it in
  the final report and leave closing to the user. Never delete or auto-close.

**Filing one task.** Build the body from the task file with two edits: drop the
`Working dir:` line (a local machine path does not belong on GitHub) and drop the
"Do NOT open a PR" bullet (that is the driver's implementer contract, not task spec).
Prepend `Part of #$ISSUE_NUM.`; when `blockedBy` is non-empty, append
`Blocked by: #<sub>, …` using the blockers' sub-issue numbers (keeps jarvis autopilot's
body-text blocker check working).

```bash
gh issue create --repo $REPO --parent $ISSUE_NUM \
  --title "<task title>" --body-file $PROMPT_DIR/.body-<task.id>.md
# add --blocked-by <sub>,<sub> when every blockedBy task already has task.issue
```

`--parent` needs a recent gh — check `gh issue create --help` for the flag and tell the
user to upgrade rather than falling back to plain issues. Keep the body file after
filing: it is the change-detection record for re-publishes. Never inline multi-line
bodies on the command line.

**Record immediately.** After each filing, before the next task: set `task.issue` to the
new number (tail of the printed URL), rewrite `task.branch` to `<type>/<number>-<slug>`
(same type and slug, new number), and set the top-level `"epic": <ISSUE_NUM>` once — epic-drive
reads `manifest.epic`, and without it the `Part of` line is silently dropped. Write the
manifest after **every** task, so an interrupted publish resumes where it stopped.

## After the decomposer returns

Publish the sub-issues (previous section), then read `$PROMPT_DIR/manifest.json` and show
the user the task list with the sub-issue numbers as links. Point out that reviewing the
plan on GitHub — editing or closing a sub-issue — is the intended gate before driving.
Then tell them the next step: `/epic-run $REPO $ISSUE_NUM` runs the rest, or
`/epic-drive $REPO $ISSUE_NUM IMPLEMENTER=<harness>:<model>` drives the tasks directly.

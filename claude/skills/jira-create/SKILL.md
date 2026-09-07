---
name: jira-create
description: Create Jira issues/sub-tasks in HelloFresh Cloud (default project TGH). Handles the required "Is Capitalizable?" custom field that makes the jira CLI fail with 400. Use whenever creating Jira tickets; keep using the jira CLI for viewing/searching.
allowed-tools: Bash
---

Create Jira issues. For viewing/searching/commenting, use the `jira` CLI as usual — this skill is for **creating and editing** (the CLI 403s on edits too, see below).

## Why not `jira issue edit`

`jira issue edit ISSUE-KEY -b"..."` gets `403 Forbidden` on TGH. Use `edit-issue.py` (next to this file) for summary/description changes instead:

```bash
python3 ~/.claude/skills/jira-create/edit-issue.py TGH-3512 \
  --summary "New title" \
  --body-file /tmp/body.md \
  --label DPD
```

- At least one of `--summary`, `--body-file`, `--body`, `--label` required; body uses the same markdown subset as `create-issue.py`.
- `--label` is repeatable and **replaces the issue's whole label list** — pass every label the issue should keep, not just the new one. Check current labels first with `jira issue view <key> --plain`.
- Output: `updated  https://hellofresh.atlassian.net/browse/TGH-XXXX`. Verify with `jira issue view <key> --plain`.
- Note: suppressing watcher notifications (`notifyUsers=false`) requires Jira admin, so there is no `--skip-notify` — edits notify watchers.

## Why not `jira issue create`

TGH requires the custom field **"Is Capitalizable?"** (`customfield_12220`, option, values `Yes`/`No`). The jira CLI silently drops it from `--custom` ("Some custom fields are not configured...") and Jira then rejects the create:

```
Error:
  - issuetype: Specify a valid issue type        # if you used -t Subtask (see below)
  - Is Capitalizable?: Is Capitalizable? is required.
```

Two other CLI gotchas seen in the wild:

- Sub-task type is `Sub-task` (hyphen), not `Subtask`.
- Assignee on Jira Cloud needs an accountId, not an email — the script resolves both.

## How to create

Use `create-issue.py` (next to this file). Auth: `JIRA_API_TOKEN` from the env + basic auth; the token is never printed.

```bash
python3 ~/.claude/skills/jira-create/create-issue.py \
  --summary "Short imperative summary" \
  --type "Sub-task" --parent TGH-3027 \
  --assignee me \
  --label DPD \
  --capitalizable Yes \
  --body-file /tmp/body.md
```

- `--type` defaults to `Task`; `--parent` is mandatory for `Sub-task`.
- `--assignee` defaults to `me` (resolved via `/rest/api/3/myself`); pass an email for someone else.
- `--label` repeatable; `--capitalizable` defaults to `Yes`.
- `--body-file` markdown subset: `## ` headings, `- ` bullets, blank-line-separated paragraphs (converted to ADF).
- `--project` defaults to `TGH`.

Output: `TGH-XXXX  https://hellofresh.atlassian.net/browse/TGH-XXXX`. Verify afterwards with `jira issue view <key> --plain`.

## Labels (mandatory — applies to BOTH create and edit)

Every ticket must get exactly one of the existing board labels, chosen by which repo/area the work touches:

| Label | Use for |
|-------|---------|
| `3p` | `production-planning` repo, or `scm-front-apps` / squad-production-planning work — everything **except** the DPD page |
| `DPD` | `fulfilment-demand-allocator`, `fulfilment-demand-allocation-optimizer`, or the DPD page of `scm-front-apps` |
| `DACH` | any repo with `DACH` in its name — always this label, no exceptions |
| `Expedite` | **almost never** — only when the user explicitly asks for it |

Rules:

- **On create:** always set a label per the mapping above; if it is not clear which one applies, **ask the user** — do not guess.
- **On edit:** check the existing labels first (`jira issue view <key> --plain`).
  - Label already present and consistent with the rules → **leave it unchanged**, do not pass `--label`, do not ask.
  - Existing label **contradicts** the rules (e.g. DACH-repo ticket labeled `3p`, or an `Expedite` nobody asked for) → **ask the user** before changing it.
  - No label at all → apply the mapping; if in doubt, **ask the user**.

## Defaults (per ~/.config/opencode/AGENTS.md)

- Project `TGH`, board `Production Planning Kanban` (id 15734).
- If the user gives no assignee, assign to the user themselves (`me`).

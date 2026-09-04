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
  --body-file /tmp/body.md
```

- At least one of `--summary`, `--body-file`, `--body` required; body uses the same markdown subset as `create-issue.py`.
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

## Defaults (per ~/.config/opencode/AGENTS.md)

- Project `TGH`, board `Production Planning Kanban` (id 15734).
- If the user gives no assignee, assign to the user themselves (`me`).

# Global Rules

## GitHub PR comments
- NEVER post replies to GitHub PR review comments directly (no `gh api` reply calls, no comment submissions, ever).
- When a review comment needs a response, draft the reply text and present it in the session for me to review and post myself.
- Code changes requested in review comments follow the normal workflow (edit, test, commit, push).

## Jira defaults
- Default project: `TGH` (Production Planning)
- Default board: `Production Planning Kanban` (id 15734)
- Use the `jira` CLI (reads `~/.config/.jira/.config.yml` for these defaults).
- For the atlassian MCP server, pass `projectKey: "TGH"` and `boardId: 15734` explicitly (MCP does not read CLI defaults).
- Creating issues: TGH requires the `Is Capitalizable?` custom field (`customfield_12220`), which the `jira` CLI cannot set — use the `jira-create` skill (`~/.claude/skills/jira-create/create-issue.py`) instead of `jira issue create`. Sub-task type is `Sub-task` (hyphen).

## Jira ticket pickup
When a Jira ticket is specified for pickup (starting work on it):
1. Check assignee and status: `jira issue view <KEY>`.
2. If it is not assigned to me, ASK whether it should be assigned to me; reassign only after confirmation: `jira issue assign <KEY> $(jira me)`.
3. Move it to `In Progress`: `jira issue move <KEY> "In Progress"`. Board flow is Backlog → To Do → In Progress, so if the ticket is in `Backlog`, move it to `To Do` first, then to `In Progress`.

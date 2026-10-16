# Global Rules

## Identity & environment
- **Identity**: Avanindra Pandeya
- **Editor**: vim
- **Shell**: zsh with [Starship](https://starship.rs/) prompt.
- **Git preferences**:
  - Default branch: `main` (preferred for personal projects)
  - Rebase on pull: `false`
  - Auto setup remote on push: `true`
  - GPG signing enabled (SSH format).
- **Gemini CLI**: prefers `oauth-personal` auth.

## Communication style
- Be brief and to the point. Give the shortest answer that fully solves the task; skip preamble, summaries, and explanations unless I ask for detail.
- Use plain, simple language. No jargon unless the repo/team already uses the term; if a term is unavoidable, say what it means in a few words.
- Only expand into long explanations when I explicitly ask (e.g. "explain", "why", "be verbose").

## Security & secret keeping (CRITICAL)
- NEVER show, log, or echo credentials, private keys, API tokens (e.g. `CLOUDFLARE_API_TOKEN`, SSH keys, database passwords), or other secrets in the conversational transcript, command outputs, or commits. Keep them hidden at all times and pipe them silently directly into commands or API tools.

## Repo context loading
- Always read the `./AGENTS.md` / `./CLAUDE.md` file in the current repository to load project-specific rules, guidelines, and commands.
- Check for any project-specific skills defined under `.claude/skills/` and use them when relevant.

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
2.  If it is not assigned to me, ASK whether it should be assigned to me; reassign only after confirmation: `jira issue assign <KEY> $(jira me)`.
3.  Move it to `In Progress`: `jira issue move <KEY> "In Progress"`. Board flow is Backlog → To Do → In Progress, so if the ticket is in `Backlog`, move it to `To Do` first, then to `In Progress`.

## Orchestration & delegation
- The main agent owns: context gathering, planning, delegation, integration, and final verification.
- I usually tell you which model or agent should implement; respect that selection. If none is given, the default implementer is the dedicated `coder` subagent (currently `ai-model-router/moonshotai/Kimi-K3`).
- Delegate implementation and remediation of review findings to the coder; delegate verification to an independent reviewer (not the agent that wrote the code). Then inspect the result yourself and check the evidence (diffs, test output) — invoking a review skill or agent does not by itself prove an independent review happened.
- Handoffs must be self-contained: the exact task and acceptance checks, the relevant plan steps and repo conventions, data-flow invariants, and exact file paths. Pass what the delegate needs — not a rigid EVERYTHING/verbatim-transcript dump.
- `@coder`-style mention syntax is OpenCode-specific; in other harnesses use the configured coder agent or an equivalent coding subagent instead of assuming the syntax exists.

## Coding & testing rules
- Names encode meaning, scope, and mutation; rename when behavior drifts from the name.
- When a function returns multiple values with distinct responsibilities, use a named result model instead of a positional tuple — this targets obscure cases, not a blanket ban on tuples.
- Wiring tests must use distinguishing, non-default values asserted downstream, so swapped or missing wiring cannot pass.
- Tests that mutate shared state must guarantee teardown and isolation under concurrent runs (unique keys/schemas/ports per run).
- Generators and parsers must reject partial or unsupported input before producing output, using an independent completeness check — a matching count alone does not prove the values were parsed.

@/Users/avanindra.pandeya/.claude/RTK.md

@/Users/avanindra.pandeya/.hf-context/AGENTS.md

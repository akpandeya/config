# Global Personal Memory

- **Identity**: Avanindra Pandeya
- **Editor**: vim
- **Shell**: zsh with [Starship](https://starship.rs/) prompt.
- **Git Preferences**:
  - Default branch: `main` (preferred for personal projects)
  - Rebase on pull: `false`
  - Auto setup remote on push: `true`
  - GPG signing enabled (SSH format).
- **Gemini CLI**: Prefers `oauth-personal` auth.
- **Security & Secret Keeping (CRITICAL)**: NEVER show, log, or echo credentials, private keys, API tokens (e.g. `CLOUDFLARE_API_TOKEN`, SSH keys, database passwords), or other secrets in the conversational transcript, command outputs, or commits. Keep them hidden at all times and pipe them silently directly into commands or API tools.

## Project Instructions & Context Loading
- Always read the `./CLAUDE.md` file in the current repository to load project-specific rules, guidelines, and commands.
- Check for any project-specific skills defined under `.claude/skills/` and use them when relevant.

## Work: Jira ticket pickup
- Work Jira: project `TGH` (Production Planning), board `Production Planning Kanban` (id 15734); use the `jira` CLI (defaults in `~/.config/.jira/.config.yml`).
- When a Jira ticket is specified for pickup (starting work on it):
  1. Check assignee and status: `jira issue view <KEY>`.
  2. If it is not assigned to me, ASK whether it should be assigned to me; reassign only after confirmation: `jira issue assign <KEY> $(jira me)`.
  3. Move it to `In Progress`: `jira issue move <KEY> "In Progress"`. Board flow is Backlog → To Do → In Progress, so if the ticket is in `Backlog`, move it to `To Do` first, then to `In Progress`.

@RTK.md

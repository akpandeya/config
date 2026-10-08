---
name: one-off-ai
description: Run one-off (non-interactive) AI prompts from the terminal with copilot, claude, or opencode — e.g. PR/code review, "explain this diff", quick analysis. Use when the user asks to run a prompt with Copilot CLI, Claude Code headless, or opencode run, or mentions "one-off prompt", "run review with copilot", etc.
---

# One-off AI prompts via CLI

Run a single prompt non-interactively and get output back. All three CLIs run
from the repo working directory so they see the code.

## GitHub Copilot CLI (`copilot`)
- One-off: `copilot -p "<prompt>" --model <model>`
- Models: run `copilot --model x` (with an invalid model name) to list. Notables: `gpt-6.1-sol`, `claude-sonnet-5`, `kimi-k3`.
- Example — PR review:
  `copilot -p "Review the changes on branch $(git branch --show-current) vs master for correctness and edge cases. Be specific." --model gpt-6.1-sol`
- Sessions: `copilot sessions` to list/resume; version: `copilot --version`; update: `copilot update`.

## Claude Code (`claude`)
- One-off (print mode): `claude -p "<prompt>"`
- Useful flags: `--model <model>`, `--output-format text|json|stream-json` (with `-p`),
  `--allowedTools <tools...>` to whitelist tools, `--permission-mode <mode>`,
  `--dangerously-skip-permissions` only for trusted sandboxed runs.
- Example — review current diff:
  `claude -p "Review my uncommitted changes (git diff) for bugs." --output-format text`

## OpenCode (`opencode`)
- One-off: `opencode run "<message>" -m provider/model#variant`
- Useful flags: `--auto` (auto-approve non-denied permissions), `--format json`,
  `-s <sessionID>` / `-c` to continue a session, `-f <file>` to attach a file,
  `--agent <name>`, `--standalone` for a private server.
- Models: `opencode models` lists them (format `provider/model`).
- Example — review a PR branch:
  `opencode run "Review branch $(git branch --show-current) vs master" --auto`

## Picking a tool
- copilot — default for one-off reviews/analysis (user preference); pick model explicitly.
- claude — when Claude-specific skills/agents or JSON output for scripting is needed.
- opencode — when you want it to join/continue an OpenCode harness session or use opencode agents.

## Rules
- Quote prompts; keep one-off prompts self-contained (the CLI has no session context).
- For repo analysis, run inside the repo so the tool can read files.
- Never paste secrets into prompts.
- Long/large output: redirect to a file, then read/present it.

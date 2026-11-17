# Subagent Example

Delegate tasks to specialized subagents with isolated context windows.

## Features

- **Isolated context**: Each subagent runs in a separate `pi` process
- **Streaming output**: See tool calls and progress as they happen
- **Parallel streaming**: All parallel tasks stream updates simultaneously
- **Markdown rendering**: Final output rendered with proper formatting (expanded view)
- **Usage display**: Shows turns, tokens, cost, and context usage inside each subagent result
- **Abort support**: Ctrl+C propagates to kill subagent processes

## Structure

```
subagent/
├── README.md            # This file
├── index.ts             # The extension (entry point)
├── agents.ts            # Agent discovery logic
├── agents/              # Sample agent definitions
│   ├── scout.md         # Fast recon, returns compressed context
│   ├── planner.md       # Creates implementation plans
│   ├── reviewer.md      # Code review (model inherited from dispatching session)
│   ├── reviewer-strong.md # Deep review pinned to the strongest router model
│   └── worker.md        # General-purpose (full capabilities)
└── prompts/             # Workflow presets (prompt templates)
    ├── implement.md     # scout -> planner -> worker
    ├── scout-and-plan.md    # scout -> planner (no implementation)
    └── implement-and-review.md  # worker ⇄ reviewer loop with user-gated escalation
```

## Installation

From the repository root, symlink the files:

```bash
# Symlink the extension (must be in a subdirectory with index.ts)
mkdir -p ~/.pi/agent/extensions/subagent
ln -sf "$(pwd)/packages/coding-agent/examples/extensions/subagent/index.ts" ~/.pi/agent/extensions/subagent/index.ts
ln -sf "$(pwd)/packages/coding-agent/examples/extensions/subagent/agents.ts" ~/.pi/agent/extensions/subagent/agents.ts

# Symlink agents
mkdir -p ~/.pi/agent/agents
for f in packages/coding-agent/examples/extensions/subagent/agents/*.md; do
  ln -sf "$(pwd)/$f" ~/.pi/agent/agents/$(basename "$f")
done

# Symlink workflow prompts
mkdir -p ~/.pi/agent/prompts
for f in packages/coding-agent/examples/extensions/subagent/prompts/*.md; do
  ln -sf "$(pwd)/$f" ~/.pi/agent/prompts/$(basename "$f")
done
```

## Security Model

This tool executes a separate `pi` subprocess with a delegated system prompt and tool/model configuration.

**Project-local agents** (`.pi/agents/*.md`) are repo-controlled prompts that can instruct the model to read files, run bash commands, etc.

**Default behavior:** Only loads **user-level agents** from `~/.pi/agent/agents`.

To enable project-local agents, pass `agentScope: "both"` (or `"project"`). Only do this for repositories you trust.

When running interactively, the tool prompts for confirmation before running project-local agents unless the session trust context reports trusted and the agents come from that session project's `.pi/agents` directory. Agents loaded from another task `cwd` still require confirmation. Set `confirmProjectAgents: false` to disable confirmation.

## Usage

### Single agent
```
Use scout to find all authentication code
```

### Parallel execution
```
Run 2 scouts in parallel: one to find models, one to find providers
```

### Chained workflow
```
Use a chain: first have scout find the read tool, then have planner suggest improvements
```

### Workflow prompts
```
/implement add Redis caching to the session store
/scout-and-plan refactor auth to support OAuth
/implement-and-review add input validation to API endpoints
```

## Tool Modes

| Mode | Parameter | Description |
|------|-----------|-------------|
| Single | `{ agent, task }` | One agent, one task |
| Parallel | `{ tasks: [...] }` | Multiple agents run concurrently (max 8, 4 concurrent) |
| Chain | `{ chain: [...] }` | Sequential with `{previous}` placeholder |

## Output Display

**Collapsed view** (default):
- Status icon (✓/✗/⏳) and agent name
- Last 5-10 items (tool calls and text)
- Usage stats: `3 turns ↑input ↓output RcacheRead WcacheWrite $cost ctx:contextTokens model`

**Expanded view** (Ctrl+O):
- Full task text
- All tool calls with formatted arguments
- Final output rendered as Markdown
- Per-task usage (for chain/parallel)

**Parallel mode streaming**:
- Shows all tasks with live status (⏳ running, ✓ done, ✗ failed)
- Updates as each task makes progress
- Distinguishes pending, running, completed, failed, and aborted tasks
- Returns each completed task summary to the parent model with its own 50 KB limit
- Returns failure diagnostics from stderr/error messages when a child exits before producing output

**Tool call formatting** (mimics built-in tools):
- `$ command` for bash
- `read ~/path:1-10` for read
- `grep /pattern/ in ~/path` for grep
- etc.

## Agent Definitions

Agents are markdown files with YAML frontmatter:

```markdown
---
name: my-agent
description: What this agent does
tools: read, grep, find, ls
model: claude-haiku-4-5
---

System prompt for the agent goes here.
```

When `model` is omitted, the subagent inherits the dispatching session's active model and thinking level.

**Per-dispatch model override:** every dispatch form (`agent`+`task` single mode, `tasks[]`, `chain[]`) also accepts an optional `model` argument (`provider/id`). It takes precedence over the agent file's pin and over session inheritance — e.g. `subagent { agent: "worker", model: "ai-model-router/Claude Opus 5.5", task: "..." }` runs that one dispatch on Opus regardless of what the session or the agent file says. A dispatch with an override does not inherit the session's thinking level.

**Locations:**
- `~/.pi/agent/agents/*.md` - User-level (with `agentScope: "user"` or `"both"`)
- `.pi/agents/*.md` - Project-level (only with `agentScope: "project"` or `"both"`)

Project agents override user agents with the same name when `agentScope: "both"`.

## Sample Agents

| Agent | Purpose | Model |
|-------|---------|-------|
| `scout` | Fast codebase recon | `ai-model-router/Claude Haiku 5.5` |
| `planner` | Implementation plans | inherits dispatching session |
| `reviewer` | Code review (ends with `Verdict: CLEAN` / `Verdict: FINDINGS (n)`) | inherits dispatching session |
| `reviewer-strong` | Deep review for escalation rounds | `ai-model-router/Claude Opus 5.5` |
| `worker` | General-purpose | inherits dispatching session |

## Workflow Prompts

| Prompt | Flow |
|--------|------|
| `/implement <query>` | scout → planner → worker |
| `/scout-and-plan <query>` | scout → planner |
| `/implement-and-review <query>` | orchestrator loop: worker ⇄ reviewer until `Verdict: CLEAN`; the orchestrator fixes mechanical findings silently and asks the user (retry / switch reviewer / split task / accept / stop) only when findings survive a round, look systemic, or the round limit is hit |

## Review loop protocol (`/implement-and-review`)

The prompt template turns the main agent into an orchestrator that dispatches
one `subagent` call per step (never a single chain, so it can decide between
steps):

1. `worker` implements (or fixes the previous review's feedback).
2. A reviewer agent reviews and ends with `Verdict: CLEAN` or
   `Verdict: FINDINGS (n)`.
3. Mechanical findings are fixed and re-reviewed without interrupting the user.
   The user is asked (via the questionnaire tool) only when a finding survived a
   fix round, the task looks like it should be split (a concrete split is
   proposed), quality issues look systemic (a stronger reviewer is offered), or
   the 3-round limit is reached.

Reviewers must emit the verdict line; `reviewer.md` and `reviewer-strong.md`
enforce this in their system prompts.

## Error Handling

- **Exit code != 0 or signal termination**: Tool returns an error with preserved stderr/output
- **Spawn errors**: Tool returns the spawn diagnostic
- **stopReason "error"**: LLM error is propagated with its error message
- **Abort**: Ctrl+C sends SIGTERM, escalates to SIGKILL after five seconds if needed, and preserves partial details/usage
- **Chain mode**: Stops at the first failing step and reports which step failed

## Limitations

- Output truncated to last 10 items in collapsed view (expand to see all)
- Single and chain output is capped at 50 KB/2,000 lines; full results remain in tool details
- Parallel output keeps a separate 50 KB budget per task, allowing up to roughly 400 KB across eight tasks
- Child usage is displayed in tool details but is not added to the calling session's usage totals
- Agents are snapshotted from each task's effective cwd when the tool invocation starts; relative task cwd values resolve from the session cwd
- Parallel mode limited to 8 tasks, 4 concurrent

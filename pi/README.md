# pi/

Config that belongs to [Pi](https://github.com/earendil-works/pi) (`pc` / `pi`).

## extensions/

Pi auto-discovers extensions in `~/.pi/agent/extensions/`. Entries here are
symlinked there by `setup-dev-env.sh`, so the repo stays the source of truth
and edits are live without re-running setup (Pi reads the files at startup;
`/reload` picks up changes in a running session).

| Extension | What it does |
|---|---|
| `plan-mode/` | Read-only plan phase (`/plan`, `Ctrl+Alt+P`, `--plan`, `Shift+Tab`) that presents the plan and asks **Approve / Keep planning / Revise** until you approve, then executes with `[DONE:n]` step tracking and a progress widget |
| `inline-bash.ts` | Expands `!{command}` in prompts before sending: `What's in !{pwd}?`, `branch: !{git branch --show-current}`. Whole-line `!cmd` behavior preserved. 30s timeout per command |
| `subagent/` | Delegate tasks to specialized subagents in isolated pi processes: single, parallel (max 8 tasks / 4 concurrent), or chained via `{previous}`. Agents + workflow prompts live in `subagent/agents/` and `subagent/prompts/`, symlinked into `~/.pi/agent/agents` and `~/.pi/agent/prompts` |
| `dynamic-tools.ts` | Template for runtime tool registration: adds `echo_session` tool at session start and `/add-echo-tool <name>` command. Adapt it to register tools you actually want |
| `keybindings.json` | Linked to `~/.pi/agent/keybindings.json`. Single override: `app.thinking.cycle` moves to `Alt+T`, freeing `Shift+Tab` for plan-mode |
| `mcp/ddg-search/` | Local DuckDuckGo web-search MCP server (see below) |

### mcp/ddg-search

A self-hosted MCP server replacing `duckduckgo-mcp-server` (npm), whose
`duck-duck-scrape` dependency now triggers DuckDuckGo's anomaly detection on
every request (the library is unmaintained). This server does a plain GET to
`html.duckduckgo.com/html/` with browser headers, which still returns real
results, and parses them with regex. Keyless, no API account.

Registered user-level in `~/.pi/agent/mcp.json` (see `pi mcp list`):

```json
"ddgsearch": {
  "command": "node",
  "args": ["~/code/personal/config/pi/mcp/ddg-search/server.mjs"]
}
```

`node_modules` is gitignored; after cloning run `npm i` inside the directory.
One tool: `duckduckgo_web_search` (query, count 1-20, safeSearch), default
`codemode` exposure — callable from codemode scripts. Verify with:

```bash
pi mcp list
cd $(mktemp -d) && pi -p "use mcp__ddgsearch__duckduckgo_web_search to search for 'test' and report the top result"
```

### plan-mode is vendored, not installed

Pi ships plan mode as an **example** extension (`examples/extensions/plan-mode/`
in the `@earendil-works/pi-coding-agent` package), not as a package you can
`pi install`. We keep a copy in this repo so every machine gets an identical,
reviewable version, and so local tweaks survive pi upgrades.

Copied from: `@earendil-works/pi-coding-agent` **1.5.2**
Upstream path: `$(npm root -g)/@earendil-works/pi-coding-agent/examples/extensions/plan-mode/`

Local deviations from upstream:

- Prompt (`[PLAN MODE ACTIVE]` in `index.ts`): dropped the `brave-search` skill
  line (that skill isn't installed everywhere), and the clarifying-questions
  hint no longer names the `questionnaire` tool, which ships as a separate
  example extension and is usually not active.
- Added `Shift+Tab` to enter plan mode and, once a plan exists, to open the
  approval dialog instead of executing straight away. The agent also gets the
  dialog after every plan turn, so approve → keep planning → revise loops until
  you approve. Execute mode restores every previously active tool and runs no
  bash allowlist; the allowlist only gates plan mode.
- Execute-mode prompt now states explicitly that every tool and command is
  available, so the model doesn't self-censor.
- Added a `plan_done` tool (registerTool in `index.ts`): during execution the
  agent calls it with finished step numbers, so the progress widget ticks
  immediately mid-turn instead of jumping 0 → all-done when the message ends
  (`[DONE:n]` tags in text are still scanned as a fallback). The tool is
  excluded from plan mode via `PLAN_MODE_DISABLED_TOOLS` so steps can't be
  ticked early; both execute prompts instruct the agent to call it.
- `pi/keybindings.json` moves `app.thinking.cycle` to `Alt+T`. Pi reserves
  `Shift+Tab` for that action and would otherwise skip the extension shortcut
  with a conflict warning.

Everything else is upstream. If you customize further, note it here.

### inline-bash, subagent, dynamic-tools (vendored)

Also vendored from `@earendil-works/pi-coding-agent` examples, same policy as plan-mode:
symlinked into `~/.pi/agent/extensions/`, source of truth in this repo.

```bash
UP="$(npm root -g)/@earendil-works/pi-coding-agent/examples/extensions"
diff -u "$UP/inline-bash.ts" pi/extensions/inline-bash.ts
diff -u "$UP/dynamic-tools.ts" pi/extensions/dynamic-tools.ts
diff -ur "$UP/subagent" pi/extensions/subagent
```

Subagent additionally symlinks sample agents (`scout`, `planner`, `reviewer`,
`worker`) into `~/.pi/agent/agents/` and workflow prompts (`/implement`,
`/scout-and-plan`, `/implement-and-review`) into `~/.pi/agent/prompts/`.
It runs user-level agents only by default (`.pi/agents` in untrusted repos is
ignored). Check `subagent/README.md` for the security model.

### Updating after a pi upgrade

```bash
UP="$(npm root -g)/@earendil-works/pi-coding-agent/examples/extensions/plan-mode"
diff -u "$UP/utils.ts" pi/extensions/plan-mode/utils.ts
diff -u "$UP/index.ts" pi/extensions/plan-mode/index.ts
```

Re-copy upstream, re-apply the deviations above (including the `plan_done`
tool), then syntax-check the vendored file loads:

```bash
node -e 'import("/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/node_modules/jiti/lib/jiti.mjs").then(async ({ createJiti }) => { const j = createJiti(import.meta.url, { alias: { typebox: "/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/node_modules/typebox/build/index.mjs" } }); const m = await j.import("pi/extensions/plan-mode/index.ts", { default: true }); console.log(typeof m); })'
```

Re-copy upstream, re-apply the two prompt deviations above, update the version
numbers in the file headers and in this README, then test:

```bash
pi --help | grep -- --plan      # proves the extension loaded
```

### Verification

After adding an extension, sanity-check it loads:

```bash
cd $(mktemp -d) && pi --list-commands 2>/dev/null || true
# then in pi: /add-echo-tool mytest  (dynamic-tools), /reload after edits,
# and prompt: branch is !{git branch --show-current}   (inline-bash)
```

### Usage

```bash
pi --plan          # start in plan mode
/plan              # toggle plan mode in a session (Ctrl+Alt+P also works)
/todos             # show plan progress
```

`Shift+Tab` drives the Claude Code-style approval cycle:

| Current mode | Shift+Tab does |
|---|---|
| Normal | Enters plan mode (read-only) |
| Plan, plan present | Opens the approval dialog: **Approve — implement now** / **Keep planning** / **Revise plan…** |
| Plan, no plan yet | Leaves plan mode (nothing to approve) |
| Execute | Back to plan mode, keeping the extracted steps |

The same dialog appears automatically after every plan-mode turn that contains
a `Plan:` section, so the loop is plan → ask → (keep planning or revise) →
re-plan → ask → approve. *Keep planning* leaves you in plan mode to type
feedback; *Revise plan…* opens an editor and sends your revision as a follow-up,
which produces a new plan and a new prompt. Nothing runs until you approve.

Plan mode removes `edit`/`write`, keeps your other active tools, and blocks
non-allowlisted bash (allowlist lives in `utils.ts`). Execute mode has no
restrictions: every tool comes back and every command is allowed.
After a pi upgrade, run `/hotkeys` to confirm `Shift+Tab` is still bound to the
extension (a conflict warning means `keybindings.json` isn't linked).

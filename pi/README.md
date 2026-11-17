# pi/

Config that belongs to [Pi](https://github.com/earendil-works/pi) (`pc` / `pi`).

## extensions/

Pi auto-discovers extensions in `~/.pi/agent/extensions/`. Entries here are
symlinked there by `setup-dev-env.sh`, so the repo stays the source of truth
and edits are live without re-running setup (Pi reads the files at startup;
`/reload` picks up changes in a running session).

| Extension | What it does |
|---|---|
| `plan-mode/` | Read-only plan phase (`/plan`, `Ctrl+Alt+P`, `--plan`, `Shift+Tab`): clarify-first questions when the request is ambiguous, then presents the plan and asks **Approve / Revise** (Esc = keep planning) until you approve, then executes with `plan_done` step tracking, a multi-column progress widget (`/todos`), role-based models (planner picker → implementer picker → read-only deep review → orchestrator restore) and a review loop that sends findings back to the implementer |
| `questionnaire.ts` | `questionnaire` tool: asks the user one or more option-based questions (single-question list, or tabbed wizard for multiple). Vendored verbatim; plan-mode's clarify phase calls it |
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
  line (that skill isn't installed everywhere), and defines a two-phase flow:
  if the request is ambiguous, call the `questionnaire` tool with option-based
  questions, marked with a `Clarifying questions:` header. No plan before the
  questions are answered; when the questionnaire returns answers (its tool
  result, same turn), continue straight to the `Plan:`. Plain-text questions
  end the turn and wait for the user's reply.
- Structural clarify gate: an `awaitingAnswers` flag (persisted in session
  state, restored on resume). In `agent_end`, a turn that asked questions
  (questionnaire tool call or `Clarifying questions:` header) AND produced no
  plan sets the flag, skips the approval dialog, and shows `⏳ awaiting
  answers` in the footer; the next user prompt injects "answers received —
  present the full plan" and clears the flag. A questionnaire call whose
  answers led to a plan in the same run falls through to the normal approval
  flow (extraction runs before the gate), and the footer is refreshed via
  `updateStatus` whenever the flag clears, so `⏳` never goes stale.
- Approval dialog has two options (`Approve — implement now` / `Revise
  plan…`); upstream's third option `Keep planning` was a no-op fallthrough
  identical to dismissing the dialog, so it was removed — Esc means keep
  planning.
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
- `Plan:` extraction (`utils.ts`) anchors the header to the start of a line
  (optional `#`/bold markers, nothing else on the line). Upstream's
  mid-sentence pattern also matched prose like "…present the plan:**", which
  scraped unrelated numbered lists as plan steps and fired the approval dialog
  on non-plans.
- Plan extraction is block-scoped (`extractTodoItemsFromBlocks` in
  `utils.ts`): only the last content block (thinking, then text) containing a
  `Plan:` header is scanned, within that block only. Upstream joins thinking
  and text with `\n` before slicing from the last header, so a thinking draft
  could merge with — or, when the visible text had no header, leak past — the
  final plan (observed live: a 10-step dialog built from 5 + 5 steps).
- Progress widget rewritten (`todos-view.ts`, new local file): numbered `✓`/`▸`/`☐`
  steps laid out in 1-4 columns sized so the longest step fits, so a wide
  terminal shows a 9-step plan in 3 rows instead of 9 rows with a dead right
  margin. Capped at 5 rows: when the plan can't fit, it shows what fits (skipping
  clipped text when a column would gut it) and adds `⋯ N more steps · /todos`.
  Upstream rendered one full-width row per step, truncated at 60 chars with
  `...`, and no step numbers — which made `plan_done(3)` impossible to follow.
- Overlong plans window on the **current step**, not the head of the list: rows
  are `✓ k done · from step k+1` + the remaining steps (+ `⋯ N more` when the
  remainder is still too long), so ticking a step scrolls the next one into view
  instead of burying it under rows of completed work. Completed steps are *not*
  reordered to the bottom — the plan stays 1..N, so `plan_done(n)` maps to a
  stable row even when steps finish out of order.
- `/todos` opens a scrollable overlay (`↑/↓`/`j`/`k`, `esc`/`q`/`c` to close)
  with every step unwrapped and the current one marked; it falls back to the old
  notification in non-TUI modes.
- Plan extraction ignores **fenced code** (`stripFencedCode` in `utils.ts`):
  every fenced block is dropped before headers and numbered lines are matched, and
  unclosed fences run to end of message. A plan *shown* inside a fence is an
  illustration (a diff, a doc snippet, a test fixture), not the agent's plan;
  matching one armed the approval dialog and replaced the live todo list with a
  step list that was never proposed for execution.
- `pi/keybindings.json` moves `app.thinking.cycle` to `Alt+T`. Pi reserves
  `Shift+Tab` for that action and would otherwise skip the extension shortcut
  with a conflict warning.
- **Role-based models** (`role-models.ts`, local-only): plan mode switches the
  session model by phase and restores the orchestrator afterwards. The first
  plan turn offers a planner picker (GLM 5.3 Flash first — Enter keeps the
  workhorse; Opus 5.5, Heavy, Sonnet 5.5, GPT-6.1 Sol, Kimi K3.1 Pro, GLM 5.3
  for hard work). Approval offers an implementer picker: the planner's
  `Implementer:` pick first, marked `★` with its reason, otherwise GLM 5.3
  Flash; GPT-6 Luna is the recommended trivial-task pick. Esc on the
  implementer picker keeps plan mode and runs nothing. In print/RPC mode the
  dialogs are skipped and the defaults apply. The footer appends the live
  model (`⏸ plan · GLM 5.3 Flash`, `📋 2/5 · Sonnet 5.5`,
  `🔍 review · Kimi K3.1 Pro`).
- **Implementer recommendation in the prompt**: plan mode injects the
  implementer menu (ids + catalog prices) and asks for one unnumbered
  `Implementer: <id> — <reason>` line after the plan. `extractImplementerPick`
  strips fenced examples and takes the last match; the line is not numbered,
  so it never becomes a todo step.
- **Review loop**: after the last step, a read-only reviewer checks
  `git status`/`git diff` against the plan and ends with `Verdict: APPROVED` or
  `Verdict: CHANGES NEEDED` plus findings. Read-only means a fixed
  `read,bash,grep,find,ls` whitelist (custom tools are not inherited) and bash
  limited to the plan-mode allowlist, so the reviewer cannot mutate the tree.
  Approved shows the completion card and restores the orchestrator; changes
  send the findings back to the implementer and re-review, capped at
  `MAX_REVIEW_ROUNDS = 2` (the second round suggests Opus 5.5). The verdict
  regex is end-anchored, so a qualified `Verdict: APPROVED, but ...` is treated
  as no verdict (warning + finish), not as approval; a missing verdict never
  loops. An aborted turn (Esc) keeps the current phase instead of completing or
  reviewing. Executions that mutated nothing (no successful `edit`/`write`, no
  non-read-only bash) skip review; the flag is tracked from tool results and
  persisted. Reviewer choice: Kimi K3.1 Pro by default, GLM 5.3 Flash for
  small/mechanical diffs, Opus 5.5 for risky plans or a second round; the
  picker shows the suggestion first with prices.
- **Orchestrator restore**: the model active before the first switch is
  captured once and restored on plan completion, `/plan` off, or Shift+Tab
  leaving an empty plan. Roles and the captured models persist in the
  `plan-mode` session entry, so resume restores the right phase (mid-review
  resumes with read-only tools).
- **Machine-local default**: `~/.pi/agent/settings.json` now defaults to
  `GLM 5.3 Flash` (work PC only; ~4× cheaper input and ~5× cheaper output than
  `Fast`) and compacts it with the same 750k reserve as the other router
  models. Edit `role-models.ts` to change the menus, order, notes, or thinking
  levels; prices are read from the catalog when the dialog opens.

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

`pi/extensions/plan-mode/todos-view.ts` and `role-models.ts` are local-only
(no upstream counterpart): todos-view holds the widget layout and the `/todos`
overlay; role-models holds the phase → model menus and thinking levels. An
upstream `index.ts` drop-in needs the `setWidget` block, the `todos` command
re-pointed at todos-view, and the role/review wiring (`switchToRole`,
`maybeChoosePlannerModel`, `chooseImplementerModel`, `beginReview`,
`handleReviewOutcome`, `restoreOrchestrator`, plus the `Implementer:` line in
plan mode's prompt). Re-copy upstream, re-apply the deviations above (including
the `plan_done` tool), then syntax-check the vendored files load (note the
`pi-tui` alias and the `./` path prefix — a bare `pi/extensions/...` path will
not resolve):

```bash
node -e 'import("/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/node_modules/jiti/lib/jiti.mjs").then(async ({ createJiti }) => { const base = "/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/node_modules"; const j = createJiti(import.meta.url, { alias: { typebox: base + "/typebox/build/index.mjs", "@earendil-works/pi-tui": base + "/@earendil-works/pi-tui/dist/index.js" } }); const m = await j.import("./pi/extensions/plan-mode/index.ts", { default: true }); console.log(typeof m); })'
```

Re-copy upstream, re-apply the deviations above, update the version
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
| Plan, plan present | Opens the approval dialog: **Approve — implement now** / **Revise plan…** (Esc = keep planning) |
| Plan, no plan yet | Leaves plan mode (nothing to approve) |
| Execute | Back to plan mode, keeping the extracted steps |

The same dialog appears automatically after every plan-mode turn that contains
a `Plan:` section, so the loop is plan → ask → (keep planning via Esc, or
revise) → re-plan → ask → approve. *Revise plan…* opens an editor and sends
your revision as a follow-up, which produces a new plan and a new prompt.
Nothing runs until you approve.

Clarify-first: when the request is ambiguous, plan mode's prompt tells the
agent to ask option-based questions via the `questionnaire` tool and stop;
the extension then holds the approval dialog and shows `⏳ awaiting answers`
until you reply. Your reply is injected as "answers received — present the
full plan", and only then does the approval cycle start.

Plan mode removes `edit`/`write`, keeps your other active tools, and blocks
non-allowlisted bash (allowlist lives in `utils.ts`). Execute mode has no
restrictions: every tool comes back and every command is allowed.
After a pi upgrade, run `/hotkeys` to confirm `Shift+Tab` is still bound to the
extension (a conflict warning means `keybindings.json` isn't linked).

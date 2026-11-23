# pi/

Config that belongs to [Pi](https://github.com/earendil-works/pi) (`pc` / `pi`).

## Scoped profiles and memory

`agents/bin/pi-personal` and `agents/bin/pi-work` use the harness-neutral
`agent-profile` launcher documented in the root README. Plain `pi` remains
generic mode without scoped memory. The Pi adapter sets:

- `PI_CODING_AGENT_DIR=~/.agent/profiles/<profile>/pi`
- `PI_CODING_AGENT_SESSION_DIR=$XDG_DATA_HOME/agent-profiles/<profile>/pi/sessions`
  (or `~/.local/share/...` when `XDG_DATA_HOME` is unset)

The launcher reserves `--session-dir` so it cannot bypass profile isolation;
other Pi arguments pass through unchanged. Setup links generic
extensions/keybindings/themes into both profiles and ticket-routing
agents/prompts only into work. Auth, models, MCP and settings remain
profile-specific.

The shared personal/work memory stores and device notes live outside the Pi
config directory under `~/.agent/profiles/<profile>/`. See
`agents/personal-memory.md`, `agents/work-memory.md` and the root README for
the scope policy. The protocols are inspired by
[RikkaHub #2130](https://github.com/rikkahub/rikkahub/pull/2130).

Tests: `python3 -m unittest scripts.tests.test_agent_guidance.InstructionsTest
scripts.tests.test_agent_profiles`.

## extensions/

Pi auto-discovers extensions in `~/.pi/agent/extensions/`. `setup-dev-env.sh`
symlinks every entry below (the repo stays the source of truth, so edits are
live without re-running setup; Pi reads the files at startup; `/reload` picks
up changes in a running session).

| Extension | What it does |
|---|---|
| `plan-mode/` | Read-only plan phase (`/plan`, `Ctrl+Alt+P`, `--plan`, `Shift+Tab`): clarify-first questions when the request is ambiguous, then presents the plan and asks **Approve / Revise** (Esc = keep planning) until you approve, then executes with `plan_done` step tracking, a multi-column progress widget (`/todos`), role-based models (planner picker → implementer + reviewer + review-round pickers → publish-policy picker → auto review loop → orchestrator restore, all decided at approval time so execution, review and the post-review publish steps run without further dialogs) and a review loop that sends findings back to the implementer |
| `questionnaire.ts` | `questionnaire` tool: asks the user one or more option-based questions (single-question list, or tabbed wizard for multiple). Vendored verbatim; plan-mode's clarify phase calls it |
| `inline-bash.ts` | *linked*. Expands `!{command}` in prompts before sending: `What's in !{pwd}?`, `branch: !{git branch --show-current}`. Whole-line `!cmd` behavior preserved. 30s timeout per command |
| `subagent/` | *linked*. Delegate tasks to specialized subagents in isolated pi processes: single, parallel (max 8 tasks / 4 concurrent), or chained via `{previous}`. Agents + workflow prompts live in `subagent/agents/` and `subagent/prompts/`, symlinked into `~/.pi/agent/agents` and `~/.pi/agent/prompts` |
| `background-compaction.ts` | *linked*. Pre-computes a compaction summary in the background once context crosses a threshold (default 200k tokens), so the actual compaction can complete instantly when a fresh cached summary is available; proposes "compact now?" between turns and caches the summary for reuse (invalidated when the context outgrew it) |
| `compaction-overrides.ts` | *linked*. On session start, syncs `compaction.modelOverrides` with the machine's own `models.json`: every 1M-class model (contextWindow ≥ 900k, compact-at ≥ ~150k) gets `reserveTokens: 750000`. pi's override keys are exact `provider/modelId` strings, and pi-setup generates models.json per machine — this keeps the behavior working where hand-listed keys don't port. Only writes when something changed; takes effect from the next session start |
| `dynamic-tools.ts` | *linked*. Runtime tool registration: adds `echo_session` tool at session start and `/add-echo-tool <name>` command. Adapt it to register tools you actually want |
| `rtk.ts` | *linked*. Rewrites bash commands through the `rtk` CLI for token savings; needs `rtk` >= 0.23 in PATH (`brew-packages.txt` installs it). No-ops when `rtk` is missing |
| `ask-user.ts` | *linked*. `ask_user` tool: Claude Code-style multi-question dialog with options, multi-select and free-text "Other" |
| `keybindings.json` | Linked to `~/.pi/agent/keybindings.json`. Six overrides: `app.thinking.cycle` → `Alt+T` (freeing `Shift+Tab` for plan-mode), `app.session.new` → `Ctrl+Shift+N`, `app.session.resume` → `Ctrl+Shift+R`, `app.session.tree` → `Ctrl+Shift+T`, `tui.altScreen.halfPageUp` → `Alt+U`, `tui.altScreen.halfPageDown` → `Alt+D` |
| `themes/matrix-dark.json` | Linked to `~/.pi/agent/themes/matrix-dark.json`; `settings.json`'s theme setting selects it |
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

`node_modules` is gitignored; `setup-dev-env.sh` runs `npm i` in the
directory on every bootstrap and merges the `ddgsearch` entry into
`~/.pi/agent/mcp.json` if it is not already registered (existing servers are
never removed). One tool: `duckduckgo_web_search` (query, count 1-20,
safeSearch), default `codemode` exposure — callable from codemode scripts.
Verify with:

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
- Approval dialog has two options (`Revise plan…` / `Approve — implement now`,
  in that order): upstream's third option `Keep planning` was a no-op
  fallthrough identical to dismissing the dialog, so it was removed — Esc means
  keep planning. Revise leads because `ctx.ui.select` starts the cursor on the
  first option, so Enter must never approve by default; the reviewer,
  review-round, and publish-policy pickers apply the same rule, putting the
  suggested model / round count first (a starred-but-second suggestion is not
  preselected) and `Hold` first on the publish ladder.
- **Publish-policy ladder** (local-only): a fourth approval-time picker asks
  what may happen after the review finishes clean — `Hold` (local commit only,
  the default), `PR only` (push + PR, human merges; draft in work repos),
  `PR + auto-merge` (merge when review clean + CI green; pending CI is watched
  for up to 60 minutes, overridable per repo; never merged on pending or red;
  personal repos only — work repos degrade to PR only per the standing
  human-merge rule), or `PR + merge + deploy` (then the repo's documented
  deploy step, if it defines one). The chosen policy is persisted with the
  plan state, injected into the execution prompt, and re-stated in the
  per-turn execution context.
- **Revision-approval guard**: the injected "Revise plan…" prefix is
  `[PLAN REVISION — do NOT execute anything; do NOT run any tools that modify
  files or state. Present the revised plan and wait for the approval dialog]`,
  and the plan-mode prompt states explicitly that a revision request is never
  approval — only the dialog's Approve (or the user saying "approve"/
  "implement") starts execution. Before this, an agent occasionally treated
  the echoed revision message (or a restated plan) as approval and started
  executing while still in plan mode, getting every write command blocked.
- **Revision messages carry the plan**: the revise path sends ONE user message
  — the guarded prefix plus the current numbered plan inlined — and never a
  bare plan-steps follow-up. The `plan-todo-list` message sent alongside the
  revision reached the model alone as a turn trigger and was read as
  "plan approved — implementing now" (observed in a gambitflow session,
  2026-11-18); the execute path folds the remaining steps into its own message
  the same way.
- **Read-only gate, not just a blocklist** (`utils.ts`): `isSafeCommand`
  checks every top-level segment (quote-aware split on `;` `|` `&&` newlines)
  against a read-only allowlist, resolves redirects itself (anything into a
  real file is a mutation; `/dev/null` and `2>&1` are fine), matches editor
  names only as a command word (so a checkout under `~/code/...` is not
  "running VS Code" — that bug blocked every plan-mode bash probe on this
  machine), recurses into `$()`/`<()`/backtick substitutions, and adds
  read-only tool support: `psql`/`snow sql`/`sqlite3` and the workbench's
  `hf-sql`/`hf-photon`/`hf-df` limited to SELECT-class statements (inline or
  via `-f`/saved-query files), plus GET/HEAD-only `curl` and `gh api`. Deny
  list closes known holes (`find -delete`, `gh api -f` = POST, `psql -o`,
  `sed -i`, `yq -i`, `xargs bash -c` via restricted xargs targets). Interpreters
  (`node script.js`, `python -c`, `bash -c`) stay blocked — a denylist cannot
  prove what a script would do. Tests: `node utils.test.ts`.
- **Subagent-backed review and implementer**: when the `subagent` extension is
  loaded, the deep-review pass is dispatched to the read-only `reviewer` agent
  as an isolated subagent (fresh context — the reviewer no longer re-reads the
  implementer's own reasoning) with an explicit per-dispatch `model` override,
  and the parent relays `Verdict: CLEAN` / `Verdict: FINDINGS (n)` to the
  extension's `Verdict: APPROVED` / `Verdict: CHANGES NEEDED` contract. Without
  the extension the in-session read-only review (with the model switch) is the
  fallback. The implementer picker gains an "Isolated — worker subagent
  (per-step dispatch)" option: each plan step is delegated to a `worker`
  subagent with an explicit model, and the orchestrator **keeps its own model**
  for dispatch and failure recovery — orchestrator and worker models are
  decoupled. The planner can recommend isolation for risky/long plans by
  writing `Implementer: Isolated (<model id>) — <reason>`, which stars the
  isolated option; inline execution stays the Enter-default otherwise. To
  support this, the `subagent` tool accepts a per-dispatch `model` override
  (single/tasks/chain) that beats the agent's pin and session inheritance.
  Safety: in plan mode only read-only agents (scout, reviewer) may be
  dispatched, in review mode only the reviewer agents — dispatching `worker`
  from a read-only phase is blocked, because a subagent's own tool set would
  otherwise bypass the guarantee. A subagent run during execution counts as
  mutating for the review-skip check. The dispatched review briefs also state
  that the reviewer's bash is allowlist-enforced (not just requested read-only);
  see the `readonly-bash.ts` bullet under subagent below.
- **Skippable first review pass** for trivial/mechanical work: the planner may
  append `; review: skip` to the Implementer line (e.g.
  `Implementer: glm-5.3-flash — mechanical symlink fix; review: skip`, parsed
  by `extractImplementerPick` in `utils.ts`), and the review dialog gains a
  "⏭ Skip review" choice that is starred (suggested) for the first round when
  the planner asked for it or the existing trivial heuristic fires (≤2 steps or
  GPT-6 Luna implementer). Picking it sends a visible `plan-review-skipped`
  card stating why and completes the plan without a reviewer. Headless runs
  (no dialog) auto-skip only on the explicit planner annotation — never on the
  heuristic alone. After a FINDINGS round the skip choice stays in the dialog
  but is never starred (manual bail-out), so a changes-requested re-review
  always runs unless you consciously skip it. A revised plan that drops the
  marker clears the request (re-parse on every plan turn).
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
  `🔍 review 1/2 · Kimi K3.1 Pro`).

  The menus are written against the HF model router but resolve
  machine-agnostically (`resolveRoleModels`): exact `provider/id` match first
  (the work PC resolves everything here), then vendor-prefix fuzzy matching
  (`MoonshotAI: Kimi K3.1 Pro` ≡ `Kimi K3.1 Pro`, `z-ai/glm-5.3-flash` ≡
  `GLM 5.3 Flash`), then capability-tier fallback for names that exist on no
  other machine — `Heavy`/`Opus` → priciest reasoning model, `GPT-6 Luna` →
  cheapest, Kimi → largest context window. Fuzzy/tier matches prefer the
  orchestrator's current provider, so resolved models always have credentials
  on the machine in use. Unmatchable specs without a tier are dropped from
  the picker, never fatal.
- **Implementer recommendation in the prompt**: plan mode injects the
  implementer menu (ids + catalog prices) and asks for one unnumbered
  `Implementer: <id> — <reason>` line after the plan. `extractImplementerPick`
  strips fenced examples and takes the last match; the line is not numbered,
  so it never becomes a todo step.
- **Reviewer recommendation in the prompt**: the injected prompt also lists
  the reviewer menu and asks for an optional second unnumbered line
  `Reviewer: <id> — <reason>; rounds: <1-5>`. `extractReviewerPick`
  (`utils.ts`) strips fenced examples, takes the last match, and parses the
  `rounds:` budget out of the reason; a garbage or missing `rounds:` just
  means no suggestion.
- **Review loop**: right after the implementer picker on approval, two more
  dialogs decide the whole review upfront — the reviewer picker (planner's
  `Reviewer:` pick starred, else the automatic heuristic; `⏭ Skip review`
  still available) and a round-budget picker (1–5, planner's `rounds:` pick
  starred, else ≤2 steps → 1, ≥6 steps or a Heavy/Opus implementer → 3,
  otherwise 2). With both decided, the loop runs dialog-free: after the last
  step a read-only reviewer checks `git status`/`git diff` against the plan
  and ends with `Verdict: APPROVED` or `Verdict: CHANGES NEEDED` plus
  findings. Read-only means a fixed `read,bash,grep,find,ls` whitelist
  (custom tools are not inherited) and bash limited to the plan-mode
  allowlist, so the reviewer cannot mutate the tree. Approved shows the
  completion card and restores the orchestrator; changes send the findings
  back to the implementer and re-review, capped at the picked
  `reviewRoundLimit` (default 2, max 5; the footer shows `🔍 review 1/2`).
  The verdict regex is end-anchored, so a qualified
  `Verdict: APPROVED, but ...` is treated as no verdict (warning + finish),
  not as approval; a missing verdict never loops. An aborted turn (Esc) keeps
  the current phase instead of completing or reviewing. Executions that
  mutated nothing (no successful `edit`/`write`, no non-read-only bash) skip
  review; the flag is tracked from tool results and persisted. Reviewer
  default: Kimi K3.1 Pro, GLM 5.3 Flash for small/mechanical diffs, Opus 5.5
  for risky plans; the picker shows the suggestion first with prices.
  Headless runs pick the same defaults without dialogs (skip only on the
  explicit `; review: skip` annotation). Both dialogs re-ask on every
  approval, so a revise → re-approve cycle can change its mind.
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

  Settings notes: `compaction.modelOverrides` keys are exact, case-sensitive
  `provider/modelId` strings — pi does no fuzzy matching there, unlike the
  role-model menus above. That is why the `compaction-overrides` extension
  syncs the overrides from each machine's own `models.json` instead of
  hardcoding router ids. Relatedly, `npm:@hellofresh/pi-setup` is
  intentionally left floating (unpinned) in the install list so internal
  fixes arrive automatically on the next bootstrap.

  Message queueing: `steeringMode` and `followUpMode` are set to `"all"` in
  `~/.pi/agent/settings.json` — messages typed while the agent runs are drained
  as one batch into the next request (pi's default `one-at-a-time` burned a
  full-context turn per queued message).

Everything else is upstream. If you customize further, note it here.

### inline-bash, subagent, dynamic-tools (vendored)

Also vendored from `@earendil-works/pi-coding-agent` examples, same policy as
plan-mode: symlinked into `~/.pi/agent/extensions/` (plus
`~/.pi/agent/agents` and `~/.pi/agent/prompts` for subagent), source of truth
in this repo. `setup-dev-env.sh` creates all of these links.

```bash
UP="$(npm root -g)/@earendil-works/pi-coding-agent/examples/extensions"
diff -u "$UP/inline-bash.ts" pi/extensions/inline-bash.ts
diff -u "$UP/dynamic-tools.ts" pi/extensions/dynamic-tools.ts
diff -ur "$UP/subagent" pi/extensions/subagent
```

`inline-bash.ts` and `dynamic-tools.ts` are vendored verbatim. `subagent/`
differs from upstream — its deviations are documented in
`pi/extensions/subagent/README.md`. In short: the `reviewer` agent enforces a
`Verdict: CLEAN` / `Verdict: FINDINGS (n)` contract, a local-only
`reviewer-strong` agent backs the escalation path of the
`/implement-and-review` loop. Agent files carry no model pins: agents inherit
the dispatching session's model (a pin hardcodes a provider and breaks on any
other machine — use the per-dispatch `model` override or plan-mode's
phase-based routing instead). Agents whose frontmatter sets
`bashAllowlist: true` (currently `reviewer`) run the child with
`--readonly-bash`, and the local-only `readonly-bash.ts` extension then
tool-enforces the plan-mode bash allowlist in that child — closing the gap
where the read-only reviewer's bash was only prompt-constrained. Plan mode's
review briefs mention the enforcement so the orchestrator doesn't ask the
reviewer to run blocked commands.

The bootstrap symlinks the sample agents (`scout`, `planner`, `reviewer`,
`reviewer-strong`, `worker`) into `~/.pi/agent/agents/` and the workflow
prompts (`/implement`, `/scout-and-plan`, `/implement-and-review`) into
`~/.pi/agent/prompts/`. The extension runs user-level agents only by default
(`.pi/agents` in untrusted repos is ignored). Check `subagent/README.md` for
the security model.

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
`maybeChoosePlannerModel`, `chooseImplementerModel`, `chooseReviewerModel`,
`chooseReviewRounds`, `beginReview`, `handleReviewOutcome`,
`restoreOrchestrator`, plus the `Implementer:` and `Reviewer:` lines in plan
mode's prompt). Re-copy upstream, re-apply the deviations above (including
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

After adding an extension, sanity-check it loads (a broken extension fails pi
startup, and registered extension flags show up in `--help`):

```bash
pi --help | grep -- --plan    # plan-mode registered its flag -> it loaded
cd $(mktemp -d) && pi -p "Reply with ok"; cd -   # headless run, no startup errors
python3 -m unittest scripts.tests.test_pi_extensions -v
# unit tests for the readonly-bash gate, bashAllowlist parsing and the child
# argv wiring (node --test under the hood; see scripts/tests/pi_extensions.test.mjs)
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

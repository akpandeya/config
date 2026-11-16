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
| `keybindings.json` | Linked to `~/.pi/agent/keybindings.json`. Single override: `app.thinking.cycle` moves to `Alt+T`, freeing `Shift+Tab` for plan-mode |

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
- `pi/keybindings.json` moves `app.thinking.cycle` to `Alt+T`. Pi reserves
  `Shift+Tab` for that action and would otherwise skip the extension shortcut
  with a conflict warning.

Everything else is upstream. If you customize further, note it here.

### Updating after a pi upgrade

```bash
UP="$(npm root -g)/@earendil-works/pi-coding-agent/examples/extensions/plan-mode"
diff -u "$UP/utils.ts" pi/extensions/plan-mode/utils.ts
diff -u "$UP/index.ts" pi/extensions/plan-mode/index.ts
```

Re-copy upstream, re-apply the two prompt deviations above, update the version
numbers in the file headers and in this README, then test:

```bash
pi --help | grep -- --plan      # proves the extension loaded
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

# pi/

Config that belongs to [Pi](https://github.com/earendil-works/pi) (`pc` / `pi`).

## extensions/

Pi auto-discovers extensions in `~/.pi/agent/extensions/`. Entries here are
symlinked there by `setup-dev-env.sh`, so the repo stays the source of truth
and edits are live without re-running setup (Pi reads the files at startup;
`/reload` picks up changes in a running session).

| Extension | What it does |
|---|---|
| `plan-mode/` | Read-only plan phase (`/plan`, `Ctrl+Alt+P`, `--plan`, `Shift+Tab`), then an execute phase with `[DONE:n]` step tracking and a progress widget |
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
- Added `Shift+Tab` to switch plan → execute → plan without the post-plan
  selector. Execute mode restores every previously active tool and runs no bash
  allowlist; the allowlist only gates plan mode.
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

`Shift+Tab` cycles the modes directly:

| Current mode | Shift+Tab does |
|---|---|
| Normal | Enters plan mode (read-only) |
| Plan, with a plan | Enters execute mode: all tools back, no bash allowlist, next prompt runs with the remaining steps |
| Plan, no plan yet | Leaves plan mode (nothing to execute) |
| Execute | Back to plan mode, keeping the extracted steps |

Plan mode removes `edit`/`write`, keeps your other active tools, and blocks
non-allowlisted bash (allowlist lives in `utils.ts`). A numbered list under a
`Plan:` header is extracted into steps; you then choose **Execute** /
**Stay** / **Refine**, or hit `Shift+Tab`. Execute mode has no restrictions.
After a pi upgrade, run `/hotkeys` to confirm `Shift+Tab` is still bound to the
extension (a conflict warning means `keybindings.json` isn't linked).

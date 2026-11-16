# pi/

Config that belongs to [Pi](https://github.com/earendil-works/pi) (`pc` / `pi`).

## extensions/

Pi auto-discovers extensions in `~/.pi/agent/extensions/`. Entries here are
symlinked there by `setup-dev-env.sh`, so the repo stays the source of truth
and edits are live without re-running setup (Pi reads the files at startup;
`/reload` picks up changes in a running session).

| Extension | What it does |
|---|---|
| `plan-mode/` | Read-only plan phase (`/plan`, `Ctrl+Alt+P`, `--plan`), then an execute phase with `[DONE:n]` step tracking and a progress widget |

### plan-mode is vendored, not installed

Pi ships plan mode as an **example** extension (`examples/extensions/plan-mode/`
in the `@earendil-works/pi-coding-agent` package), not as a package you can
`pi install`. We keep a copy in this repo so every machine gets an identical,
reviewable version, and so local tweaks survive pi upgrades.

Copied from: `@earendil-works/pi-coding-agent` **1.5.2**
Upstream path: `$(npm root -g)/@earendil-works/pi-coding-agent/examples/extensions/plan-mode/`

Local deviations from upstream (both in the `[PLAN MODE ACTIVE]` prompt in
`index.ts`):

- Dropped the `brave-search` skill line (that skill isn't installed everywhere).
- The clarifying-questions hint no longer names the `questionnaire` tool, which
  ships as a separate example extension and is usually not active.

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

Plan mode removes `edit`/`write`, keeps your other active tools, and blocks
non-allowlisted bash (allowlist lives in `utils.ts`). A numbered list under a
`Plan:` header is extracted into steps; you then choose **Execute** /
**Stay** / **Refine**.

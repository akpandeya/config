# config

Personal dotfiles + macOS bootstrap. One-command setup for a fresh Mac.

## Quick start (new machine)

```bash
# 1. Install 1Password desktop app (App Store or https://1password.com)
#    Settings → Security → enable Touch ID
#    Settings → Developer → "Integrate with 1Password CLI"
#    Sign in to 1Password.

# 2. Clone config and the required private atelier repo side by side via
#    HTTPS (SSH keys come later). Your GitHub account needs atelier access.
git clone https://github.com/akpandeya/config
git clone https://github.com/akpandeya/atelier
cd config

# 3. Add your git identity emails (gitignored, never committed):
cp gitconfig/emails.example.env gitconfig/emails.local.env
#    ...then edit emails.local.env with your real addresses.

# 4. Run the bootstrap. It installs Homebrew, packages, and exports
#    SSH keys from 1Password onto disk. Jarvis is opt-in (INSTALL_JARVIS=1).
./setup-dev-env.sh
```

That's it. After `setup-dev-env.sh` finishes:

- `git@github.com-work:` and `git@github.com-personal:` both work.
- Long-running unattended processes (Claude Code, cron, launchd agents) can `git push` without any 1Password prompt.
- A launchd agent at `~/Library/LaunchAgents/com.user.ssh_unlock.plist` re-loads the keys into `ssh-agent` after every login.

## What the SSH setup does

1. Exports the `HF Thinkpad` and `Asus fedora` SSH keys from 1Password using `op read`.
2. Passphrase-protects each with a fresh random string, stashed back into 1Password as an `ssh-passphrase` field.
3. Primes Apple Keychain with the passphrase via `ssh-add --apple-use-keychain`.
4. Installs `~/.ssh/ssh_unlock.sh` and a launchd plist that re-runs it on login (`RunAtLoad=true`, `LimitLoadToSessionType=Aqua`).
5. Rewrites `~/.ssh/config` to use `IdentityFile ~/.ssh/id_*` instead of the 1Password agent socket.

After the first run, Apple Keychain holds the passphrases, so subsequent logins don't need 1Password at all. If you quit 1Password or it locks, SSH still works.

Source of truth: 1Password. The disk copies are a cache. You can rotate a key by deleting it from disk and rerunning `./ssh/setup.sh`.

Edit the `KEYS=(...)` array in `ssh/setup.sh` to add/remove keys.

## Layout

| Directory | What it holds |
|---|---|
| `brew-packages.txt` | Everything Homebrew installs |
| `agents/communication.md` | Shared plain-language and local-explanation preferences |
| `skills/` | Harness-neutral skills, symlinked into `~/.agents/skills/` (read natively by pi, opencode and copilot) and into `~/.claude/skills/` and the Gemini personal-skills plugin. All harnesses share the same files — no per-harness forks |
| `claude/skills/` | Harness-coupled skills kept Claude-only: jarvis-managed (`jarvis-suggest`, `jarvis-continue-in-phone`, `slack-catchup`), `prompt` (clipboard copier), and any not yet promoted to `skills/`. Company-specific skills live in the private work-context repo. Jarvis-managed skill directories retain their own installation |
| `claude/hooks/` | Claude Code hook scripts. None are wired up right now (`settings-hooks.json` has an empty `PostToolUse`), so `jarvis-register.sh` is not active |
| `claude/settings-hooks.json` | Merged into `~/.claude/settings.json` — only replaces `hooks.PostToolUse`, preserves everything else |
| `gitconfig/` | Scoped git identity + signing templates rendered to `~/.gitconfig-personal` / `~/.gitconfig-work` by the bootstrap (see `gitconfig/README.md`). Real emails live in `emails.local.env` (gitignored — never commit them) |
| `kitty/` | Terminal config |
| `pi/` | Pi config. `pi/extensions/plan-mode/` is a vendored copy of the pi `plan-mode` extension, symlinked to `~/.pi/agent/extensions/plan-mode` (read-only planning that asks **Approve / Keep planning / Revise** until you approve, then executes with step tracking; `Shift+Tab`; the review pass and optionally the implementer run as isolated subagents). `pi/keybindings.json` moves thinking-level cycling to `Alt+T` to free `Shift+Tab`. `pi/prompts/` holds pi prompt templates (`/pick-up-ticket`), symlinked into `~/.pi/agent/prompts/` |
| `agents/` | Shared communication policy composed into every harness's global instructions by `scripts/install-agent-instructions.py` |
| `scripts/` | Instruction composer, Pi installer and bootstrap helpers |
| `shell/` | Shared shell aliases (incl. `va`: activate the nearest `.venv`, walking up) + the `dev` repo/harness launcher (`dev.sh`, `dev-shortcuts.conf`) |
| `ssh/` | SSH-from-1Password installer (templates + `setup.sh`) |
| `starship/` | Prompt config |
| `setup-dev-env.sh` | Top-level bootstrap — Homebrew, git, SSH, shared skills+hooks, atelier Mermaid dependencies, optional Jarvis (clone + `make install` + launchd agents). Atelier must be cloned next to config. Env vars: `SETUP_MODE=work\|personal` (which git identity/profile to configure — inferred from existing `~/.gitconfig-work` when unset), `DRY_RUN=1` (print what would happen, change nothing; still validates atelier), `INSTALL_JARVIS=1` (Jarvis is opt-in, not installed by default), `SKIP_MERMAID=1` (skip Mermaid dependency installation only), `SKIP_SCHEDULES=1`, `SKIP_PI=1` (skip Pi CLI installation) |

## Jumping into a repo with an AI harness (`dev`)

`shell/dev.sh` (sourced via `shell/aliases.sh`, zsh only) lists every git repo under the code root — `$DEV_CODE_ROOT`, default `~/code`, scanned for dirs containing `.git` up to depth 4.

| Command | What it does |
|---|---|
| `dev` / `dev <query>` | fzf over all repos, shortcuts pinned on top marked `*`, group folders (e.g. `work`, `personal`) marked `>`. `enter` asks which harness, `ctrl-o` opens opencode, `ctrl-c` opens Claude Code, `ctrl-p` opens Pi, `ctrl-n` opens nvim. |
| `cc [target] [flags]` | Claude Code (`claude --dangerously-skip-permissions`). No target → opens in the current directory. Args from the first `-...` one onward are passed through: `cc dach-pheidi --resume`, `cc --resume`. |
| `oc [target] [flags]` | opencode (`opencode --auto`). No target → opens in the current directory. Same flag passthrough as `cc`. |
| `pc [target] [flags]` | Pi (`pi`). Same repo resolution and flag passthrough as `cc`/`oc`: `pc fda`, `pc gambitflow --continue`, `pc --resume`. |
| `<shortcut>` e.g. `fda` | cd into the shortcut's repo + launch its default harness. Extra args are forwarded to the harness (`fda --resume`). |
| `fcd [query]` | fuzzy-cd into a repo/folder directly under a group folder (`work/<repo>`, `personal/<repo>`) — just cd's, no harness. |

A `target` can be a shortcut name (`cc fda`), a repo basename (`oc gambitflow`), a group folder (`cc work`, `oc personal`), a full relative path, or a fuzzy query (`cc dem and` → picker pre-filtered).

`pc` means **Pi Coding**. The native `pi` command stays untouched for prompts and management commands (`pi "explain this repo"`, `pi update`, `pi auth login`). Like `cc`/`oc`, words before the first flag in `pc` are a repo query, not a prompt. Pi launches without a permission-bypass flag; it does not ask for approval before every tool call, but project trust is a separate check.

## Postgres (`fpsql`)

`shell/pg.sh` (sourced via `shell/aliases.sh`, zsh only) reads `$PGSERVICEFILE` (default `~/.pg_service.conf` — symlinked from hf-workbench).

| Command | What it does |
|---|---|
| `fpsql [svc] [name]` | fzf over the `[stanza]` names plus `snowflake:hf` / `databricks:photon`, then opens the per-service **SQL scratch in nvim** bound to it (`fpsql nomos` → scratch picker, `fpsql nomos review` → `nomos/review.sql` directly, `fpsql snow` → snowflake scratch). |
| `fpsql -p [svc] [psql flags]` | same picker (pg services only), but opens `psql service=<name>` (`fpsql -p nomos -c '\dt'`). |
| `psql service=<TAB>` | tab-completes service names from the same file (other psql args fall through to the stock completion). |

In nvim, `:SqlScratch` / `:SqlHistory` also cover two CLI-backed backends besides the pg services: `snowflake:hf` (runs `snow sql -c hf -f`, SSO browser on first query of a session) and `databricks:photon` (runs `hf-photon -f`). They're custom dadbod adapters in `nvim/autoload/db/adapter/` — scratch + run-in-buffer only, no DBUI schema tree. Executed queries are logged to `~/.local/share/nvim/sql-history/`.

### Add a new shortcut

1. Add one line to `shell/dev-shortcuts.conf`:
   ```
   gfw = personal/gambitflow : claude
   ```
   Format: `name = path-relative-to-code-root [: default-harness]`. The default harness is optional — without it the bare command only cd's.
2. `cc gfw`, `oc gfw`, `pc gfw` and `dev` pick it up **immediately** (the conf is re-read on every call). The bare `gfw` command appears in new shells (`source ~/.zshrc`).

### Add or change a harness

Edit `shell/dev.sh`: the `case` in `_dev_launch` (repo jumps) and the no-arg `case` in `_dev_go` (current-dir launches). Supported launchers are `opencode`, `claude`, `pi` and `nvim`. A shortcut can use `: pi` to make Pi its default.

### New machine

`setup-dev-env.sh` installs `fzf` and `node` from `brew-packages.txt` and wires `shell/aliases.sh` into `~/.zshrc`, which sources `dev.sh`. It also runs `scripts/install-pi.sh` in both personal and work profiles:

- Requires Node.js 22.19+ and installs `@earendil-works/pi-coding-agent` globally with npm (`--ignore-scripts`).
- Leaves an existing Pi installation in the current npm prefix unchanged; fails clearly if another `pi` executable is on PATH rather than overwriting it.
- Supports `DRY_RUN=1` and `SKIP_PI=1`. To run just this step: `bash scripts/install-pi.sh`.
- Links `pi/extensions/plan-mode` into `~/.pi/agent/extensions/plan-mode`, so every machine gets the same plan/execute mode (`/plan`, `Ctrl+Alt+P`, `pi --plan`, `Shift+Tab`): the agent presents a plan and loops on the approval prompt until you approve, then implements with step tracking. Pinned upstream version and update steps: `pi/README.md`.
- Links `pi/keybindings.json` into `~/.pi/agent/keybindings.json`, moving `app.thinking.cycle` to `Alt+T` so `Shift+Tab` can switch plan ↔ execute.
- Verifies `pi --version`. On first use, run `pi` and `/login`; credentials are local and are not installed from this repo.

Open a new shell (or `source ~/.zshrc`) to use `pc`. Use `pi update` when you want to update Pi.

OpenCode and Claude Code are **not currently installed by this bootstrap**; install those CLIs separately.

## Markdown site preview (`mdserve`)

`mdserve [dir]` (in `shell/aliases.sh`) serves any folder of markdown as a browsable site at `localhost:8642` — clickable relative `./x.md#anchor` links, mermaid diagrams rendered, live reload on save. It generates a throwaway mkdocs config (material theme, dark), so no per-project setup. Backed by `mkdocs` + `mkdocs-material`, installed by `setup-dev-env.sh` via `uv tool install mkdocs --with mkdocs-material`.

In nvim, `<leader>mb` in a markdown buffer starts mdserve on the current file's directory and opens the browser once the server is up. Only one mdserve runs at a time: a server already on :8642 gets killed and restarted with the new directory.

## rtk (token-saving CLI proxy)

[`rtk`](https://www.rtk-ai.app/) filters/summarizes noisy command output (git, gh, docker, test runners, ...) before it reaches the LLM. It's wired into both harnesses:

- **Claude Code**: a `PreToolUse` hook on `Bash` (`rtk hook claude`) merged into `~/.claude/settings.json`, plus `claude/RTK.md` composed into the generated Claude instructions.
- **opencode**: a generated plugin at `~/.config/opencode/plugins/rtk.ts`.

Bootstrap runs `rtk init -g --hook-only --auto-patch` (hook only — never touches CLAUDE.md or RTK.md) and `rtk init -g --opencode --auto-patch` (plugin only). Both are idempotent and non-interactive, so `setup-dev-env.sh` re-runs them every time (after installing `rtk` from `brew-packages.txt`).

Do NOT run plain `rtk init -g --auto-patch` against your real HOME: it expects
an `@RTK.md` import and would modify the generated instructions. RTK guidance is
flattened into Claude/OpenCode only, not Gemini or Copilot. If a new version changes
its guidance, regenerate in a scratch HOME, update `claude/RTK.md`, then rerun the
instruction composer. To check savings: `rtk gain`.

## Shared assistant guidance

`opencode/AGENTS.md` holds generic working rules; `agents/communication.md` owns
the communication style. Substantial explanations connect context, behavior,
examples and consequences. Routine answers stay short. Deep reviews include
**How this works** and **Why this matters** for every finding, separately from
the short pasteable review comment.

Refresh the installed instructions after changing these sources:

```bash
python3 scripts/install-agent-instructions.py
```

The composer writes private, mode-600 local files under
`~/.config/agent-context/` and links the harness instruction surfaces to them.
It flattens optional `~/.hf-context/AGENTS.md` rather than assuming every
harness supports imports. No combined private content is written into this
repository. Existing global files/links are preserved as
`.before-agent-context` backups. `--dry-run` previews; `--home <directory>`
supports isolated checks.

Company-specific AWS, Jira, Snowflake and incident workflows are installed by
the private work-context repository, not copied back here. In work setup mode,
bootstrap invokes that repo's link installer before composition, after the
Gemini plugin directory exists. Either installation order is supported.

### Harness-neutral memory profiles

The scope resolver and memory protocols are shared across harnesses. Plain
`pi`, `opencode`, `claude`, `copilot` and `agy` receive generic instructions
without scoped Markdown memory or private work context. Scoped commands are:

- `<harness>-personal`: personal instructions plus the RikkaHub-inspired
  protocol in `agents/personal-memory.md`.
- `<harness>-work`: private work instructions plus the curated protocol in
  `agents/work-memory.md`.

The launchers currently support Pi, OpenCode, Claude Code and Copilot through
their native configuration hooks:

| Harness | Profile configuration | Profile state |
|---|---|---|
| Pi | `PI_CODING_AGENT_DIR` | Separate `PI_CODING_AGENT_SESSION_DIR` |
| OpenCode | `OPENCODE_CONFIG_DIR` | Profile-specific `XDG_DATA_HOME`, `XDG_STATE_HOME` and `XDG_CACHE_HOME`; `--standalone` avoids a shared background service |
| Claude Code | `CLAUDE_CONFIG_DIR` | Config-root-local history/sessions |
| Copilot | `COPILOT_HOME` | Home-local history/sessions |

Harness-native or cloud memory features are outside this protocol. Disable
them in generic mode or configure and verify their isolation separately;
changing a local config root does not prove that a remote memory service is
profile-scoped.

`agy` has no verified config-directory override yet, so plain `agy` remains
generic mode without scoped memory rather than receiving an unscoped personal
or work profile. A future adapter can use a verified native hook or a
deliberate HOME sandbox.

`agents/bin/agent-profile` sanitizes inherited Git worktree overrides, resolves
the canonical Git root and rejects wrong-profile or unknown locations.
Worktrees are classified by real location, not repository identity. Each
profile lives at `~/.agent/profiles/<profile>`; its harness configuration and
state are separate, including session JSONL and compaction history. Config,
data and instruction-link scope escapes are rejected. Existing legacy
histories are not migrated or read by the scoped launchers; review them
separately for offboarding.

The composer also migrates existing work-owned skill symlinks out of generic
Claude/Agy discovery into the scoped work profile. It moves only links whose
targets resolve under `~/code/work`, leaves personal links and real directories
untouched, and preserves conflicting destinations as backups.

Memory content never lives in this public checkout:

- Personal memory uses `~/code/personal/pi-memory` by default and is exposed as
  `~/.agent/profiles/personal/memory`.
- Work memory uses an employer-owned repository at `~/code/work/agent-memory`
  by default and is exposed as `~/.agent/profiles/work/memory`. Set
  `AGENT_WORK_MEMORY_DIR` to another canonical path under `~/code/work` when
  the work setup chooses a different repository. `AGENT_PERSONAL_MEMORY_DIR`
  provides the equivalent personal override under `~/code/personal`.
- A missing repository means no long-term memory; the launchers never clone or
  fall back to the other profile. Cross-scope and unexpected symlinks are
  rejected rather than replaced.

Work memory is limited to explicitly saved preferences, approved tool choices
and glossary entries. Internal acronyms stay work-only. Project state,
architecture, tickets and code stay in repository documentation. There is no
automatic work-to-personal/shared consolidation. Generic shared preferences
are changed only through reviewed config changes.

Device notes may live at `~/.agent/profiles/<profile>/device.md`; they are
local, untracked and shared by that profile's harnesses. Setup links selected
generic Pi/OpenCode resources, but not auth, model endpoints, MCP servers or
settings. This is accident-resistant separation, not a hard OS security
boundary.

### Local HTML explanations

The offline HTML explanation/review renderer and feedback toolchain live in
the private [atelier](https://github.com/akpandeya/atelier) repo. Its README
owns the invocation, complete input JSON format, supported blocks and feedback
options. Clone atelier next to config before setup: the bootstrap installs its
pinned Mermaid dependencies and links the shared `artifact-feedback` skill and
OpenCode command from that checkout.

### Review boundaries and portability

- CI observation is read-only. The watcher distinguishes pending, failed,
  cancelled, empty/unknown and passed checks, bounds API-error retries and
  records new discussion without posting. Explicit end-to-end workflows may
  separately authorize CI repair and publication.
- Driver prompts preserve task dependencies and stop on failed verification.
  They do not discard unexpected files or amend/force-push by default.
  Work merges remain human actions.
- Synced third-party skills were reviewed but not rewritten. The `learn` skill's
  diagnostic-question defaults can conflict with direct explanations: request
  tutoring explicitly rather than applying it to ordinary code explanations.
  Docs/import-memory connectors, hosted-browser assumptions in morning briefs,
  and preinstalled office tooling are environment requirements, not universally
  available capabilities.
- The managed desloppify body is unchanged. A scan does not authorize its
  broader commit/push or upstream-publication suggestions; shared scope rules
  apply.
- OpenCode 2.1.2's installed API schema uses `permissions` rule lists with
  `action`/`resource`/`effect`, unlike older `permission.bash` examples. Agent
  source headers match that schema. Agent activation is not established merely
  by matching it: the installed `/api/agent` endpoint returned an empty list
  even for an isolated valid inline-config fixture. Do not assume the custom
  agents are active or broaden permissions to work around that limitation.

Focused checks:

```bash
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
```

`deep-review` generates read-only PR navigation with
`~/.config/agent-context/scripts/pr-comment-links.py --input <request.json>`.
The helper validates merge-base-to-head diff lines and emits separate candidate
comment links and full-SHA pinned source links. Generated GitHub fragments are
labelled diff-validated but UI-unverified unless actual rendered-target evidence
is supplied.

## Common operations

```bash
# See what a full bootstrap run would do without changing anything
DRY_RUN=1 ./setup-dev-env.sh

# Pick the git identity/profile explicitly. Left unset, it is inferred from
# this machine (work if ~/.gitconfig-work exists), so re-runs never drop the
# work identity just because the variable was not passed again. Git identity
# emails come from gitconfig/emails.local.env and are never prompted for.
SETUP_MODE=work ./setup-dev-env.sh

# Re-run just the SSH setup (after adding a new key to 1Password)
./ssh/setup.sh

# Skip SSH setup (e.g. offline, or 1Password not ready)
SKIP_SSH=1 ./setup-dev-env.sh

# Opt in to installing/scheduling Jarvis (skipped by default)
INSTALL_JARVIS=1 ./setup-dev-env.sh

# Roll back to 1Password SSH agent
# 1. Edit ~/.ssh/config: comment out IdentityFile lines, uncomment the
#    commented-out IdentityAgent block at the bottom.
# 2. Uninstall the launchd agent:
launchctl bootout gui/$UID/com.user.ssh_unlock
rm ~/Library/LaunchAgents/com.user.ssh_unlock.plist

# Inspect what's loaded in ssh-agent right now
ssh-add -l

# Tail the unlock agent's log
tail -f ~/.ssh/ssh_unlock.log
```

## Troubleshooting

**"op read failed" in `~/.ssh/ssh_unlock.log`.** 1Password desktop app wasn't unlocked when the agent fired. Unlock 1Password, then `launchctl kickstart gui/$UID/com.user.ssh_unlock`.

**`ssh -T git@github.com-work` still prompts.** Check `ssh-add -l` — if the key isn't there, run `./ssh/setup.sh` again.

**Cloning this repo requires SSH on a fresh machine.** Clone via HTTPS first (`git clone https://github.com/...`), then bootstrap, which sets up SSH.

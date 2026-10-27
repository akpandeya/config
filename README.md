# config

Personal dotfiles + macOS bootstrap. One-command setup for a fresh Mac.

## Quick start (new machine)

```bash
# 1. Install 1Password desktop app (App Store or https://1password.com)
#    Settings → Security → enable Touch ID
#    Settings → Developer → "Integrate with 1Password CLI"
#    Sign in to 1Password.

# 2. Clone this repo via HTTPS (SSH keys come later).
git clone https://github.com/akpandeya/config
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
| `bash/` | Bash profile snippets |
| `brew-packages.txt` | Everything Homebrew installs |
| `agents/communication.md` | Shared plain-language and local-explanation preferences |
| `claude/skills/` | Personal skills, linked into Claude and the Gemini personal-skills plugin. Company-specific skills live in the private work-context repo. Jarvis-managed skill directories retain their own installation |
| `claude/hooks/` | Claude Code hook scripts. None are wired up right now (`settings-hooks.json` has an empty `PostToolUse`), so `jarvis-register.sh` is not active |
| `claude/settings-hooks.json` | Merged into `~/.claude/settings.json` — only replaces `hooks.PostToolUse`, preserves everything else |
| `git/` | gitconfig templates (one personal, one work, one default with conditional includes) |
| `gitconfig/` | Scoped git identity templates rendered to `~/.gitconfig-personal` / `~/.gitconfig-work` by the bootstrap. Real emails live in `emails.local.env` (gitignored — never commit them) |
| `kitty/` | Terminal config |
| `scripts/` | Instruction composer, offline explanation renderer and bootstrap helpers |
| `shell/` | Shared shell aliases + the `dev` repo/harness launcher (`dev.sh`, `dev-shortcuts.conf`) |
| `ssh/` | SSH-from-1Password installer (templates + `setup.sh`) |
| `starship/` | Prompt config |
| `setup-dev-env.sh` | Top-level bootstrap — Homebrew, git, SSH, Claude skills+hooks, local Mermaid renderer, optional Jarvis (clone + `make install` + launchd agents). Env vars: `DRY_RUN=1` (print what would happen, change nothing), `INSTALL_JARVIS=1` (Jarvis is opt-in, not installed by default), `SKIP_MERMAID=1`, `SKIP_SCHEDULES=1` |

## Jumping into a repo with an AI harness (`dev`)

`shell/dev.sh` (sourced via `shell/aliases.sh`, zsh only) lists every git repo under the code root — `$DEV_CODE_ROOT`, default `~/code`, scanned for dirs containing `.git` up to depth 4.

| Command | What it does |
|---|---|
| `dev` / `dev <query>` | fzf over all repos, shortcuts pinned on top marked `*`, group folders (e.g. `work`, `personal`) marked `>`. `enter` asks which harness, `ctrl-o` opens opencode, `ctrl-c` opens Claude Code. |
| `cc [target] [flags]` | Claude Code (`claude --dangerously-skip-permissions`). No target → opens in the current directory. Args from the first `-...` one onward are passed through: `cc dach-pheidi --resume`, `cc --resume`. |
| `oc [target] [flags]` | opencode (`opencode --auto`). No target → opens in the current directory. Same flag passthrough as `cc`. |
| `<shortcut>` e.g. `fda` | cd into the shortcut's repo + launch its default harness. Extra args are forwarded to the harness (`fda --resume`). |
| `fcd [query]` | fuzzy-cd into a repo/folder directly under a group folder (`work/<repo>`, `personal/<repo>`) — just cd's, no harness. |

A `target` can be a shortcut name (`cc fda`), a repo basename (`oc gambitflow`), a group folder (`cc work`, `oc personal`), a full relative path, or a fuzzy query (`cc dem and` → picker pre-filtered).

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
2. `cc gfw`, `oc gfw` and `dev` pick it up **immediately** (the conf is re-read on every call). The bare `gfw` command appears in new shells (`source ~/.zshrc`).

### Add or change a harness

Edit `shell/dev.sh`: the `case` in `_dev_launch` (repo jumps) and the no-arg `case` in `_dev_go` (current-dir launches). `opencode` and `claude` are the two known harnesses.

### New machine

Nothing extra to do: `setup-dev-env.sh` installs `fzf` and `anomalyco/tap/opencode` from `brew-packages.txt` and wires `shell/aliases.sh` into `~/.zshrc`, which sources `dev.sh`. Claude Code itself is installed by its native installer, not Homebrew.

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
`~/.config/agent-context/` and links all four instruction surfaces to them:
Claude, OpenCode, Gemini and Copilot. It flattens optional
`~/.hf-context/AGENTS.md` rather than assuming every harness supports imports.
No combined private content is written into this repository. Existing global
files/links are preserved as `.before-agent-context` backups. `--dry-run`
previews; `--home <directory>` supports isolated checks.

Company-specific AWS, Jira, Snowflake and incident workflows are installed by
the private work-context repository, not copied back here. In work setup mode,
bootstrap invokes that repo's link installer before composition, after the
Gemini plugin directory exists. Either installation order is supported.

### Local HTML explanations

For substantial reviews or explanations, save one offline page per repo/topic
and open it once. The user can override this with "brief", "text only" or
"don't open". Tiny re-review deltas need no new browser tab.

Write plain-text content as JSON in a local scratch directory, then:

```bash
python3 scripts/agent-explainer.py \
  --repo /path/to/repo --topic data-flow --input /path/to/explanation.json
```

```json
{
  "title": "How the update works",
  "summary": "Validate first, then save the accepted change.",
  "sections": [
    {
      "heading": "The flow",
      "flow": ["Input", "Validation", "Storage", "Response"],
      "paragraphs": ["Invalid input stops before storage changes."]
    },
    {
      "heading": "Why this matters",
      "steps": ["An invalid identifier is rejected.", "The existing record stays unchanged."],
      "code": "validate(input)\nsave(input)"
    }
  ],
  "metadata": {"Revision": "example-sha"},
  "sources": [{"label": "Source", "url": "https://example.org/source"}]
}
```

The legacy fields above remain supported in their existing fixed order:
`paragraphs`, `steps`, `flow`, `code`, then `comments`. For explanations whose
structure matters, use ordered `blocks` instead:

```json
{
  "title": "Why validation changes the outcome",
  "summary": "Validate the candidate before replacing the stored value.",
  "sections": [
    {
      "heading": "One input shows the difference",
      "blocks": [
        {
          "type": "callout",
          "title": "Key rule",
          "text": "A rejected candidate must leave the stored value unchanged."
        },
        {
          "type": "comparison",
          "left": {
            "label": "Expected",
            "value": "old → old",
            "text": "Validation fails before persistence."
          },
          "right": {
            "label": "Actual",
            "value": "old → empty",
            "text": "The old value is cleared before validation finishes."
          },
          "caption": "The state change, not the validation message, is the bug."
        },
        {
          "type": "diagram",
          "source": "flowchart TD\n  A[Candidate] --> B{Valid?}\n  B -->|Yes| C[Save]\n  B -->|No| D[Keep existing value]",
          "caption": "Validation controls whether storage changes.",
          "text_alt": "A candidate is validated. Valid input is saved; invalid input leaves the existing value unchanged."
        },
        {
          "type": "details",
          "summary": "Supporting source trace",
          "blocks": [
            {"type": "text", "text": "The parser calls validation before the storage adapter."},
            {"type": "steps", "items": ["Parse the candidate.", "Validate it.", "Save only when valid."]}
          ]
        },
        {
          "type": "comments",
          "items": ["Can we validate before replacing the stored value?"]
        }
      ]
    }
  ]
}
```

Supported block shapes are deliberately small:

| Type | Fields |
|---|---|
| `text` | `text` |
| `steps` | nonempty `items` list |
| `code` | `code` |
| `comments` | nonempty `items` list; each item gets a copy control |
| `callout` | `title`, `text` |
| `comparison` | `left` and `right`, each with `label`, `value`, optional `text`; optional `caption` |
| `diagram` | Mermaid `source`, visible `caption`, meaningful `text_alt` |
| `details` | `summary` and nonempty nested `blocks`; nested diagrams/details are rejected |

A section may use `blocks` or any legacy content field, never both—even if one
side is empty. Ambiguous mixtures fail rather than silently dropping or
reordering content. Section-level `heading`, `severity` and `location` work in
both formats. In review mode, a finding's required pasteable comment must be a
top-level `comments` field or direct `comments` block so it remains easy to
find; a comment hidden inside `details` does not satisfy that requirement.

Use comparisons when the important point is what differs, diagrams when
relationships, ordering, branches or state transitions matter, worked examples
when a reader needs to follow one concrete input, and details when supporting
evidence would interrupt the main explanation. These are choices, not a
checklist; a short paragraph remains appropriate for a simple point.

#### Mermaid setup and safety

The renderer uses pinned local dependencies in `scripts/mermaid/`:
`@mermaid-js/mermaid-cli` plus its matching Puppeteer browser. The normal
bootstrap installs them with:

```bash
npm ci --prefix scripts/mermaid
```

`setup-dev-env.sh` runs that command automatically; set `SKIP_MERMAID=1` only
when intentionally skipping diagram support. Installation requires Node
22.13 or newer and network access to download npm packages and Puppeteer's
pinned headless Chrome. The repository bootstrap installs current Node through
Homebrew on macOS. Mermaid CLI/Puppeteer also support their documented Linux
platforms, but this repository's full bootstrap remains macOS-oriented. No
global npm install is used.

Normal artifact generation invokes
`scripts/mermaid/node_modules/.bin/mmdc` directly and performs no package,
browser, font or remote-asset download. The generated HTML contains sanitized
static SVG and works offline; it does not load Mermaid in the browser.
The headless browser runs with background networking disabled and an
unreachable loopback proxy so diagram content cannot fetch remote resources
during rendering.
Generated SVG is parsed independently and rejects scripts, event handlers,
foreign/unsupported elements, unsafe links, and external resource references.
The Mermaid source is escaped and retained in an expandable section, while the
caption and text alternative remain available to readers and assistive
technology. Mermaid initialization directives and configuration frontmatter are
both rejected so source content cannot override renderer policy.

Pages live at `~/.local/share/agent-explainers/<repo-key>/<topic>.html`, outside
Git; worktrees share their repository identity. Reusing a topic updates the page.
The renderer validates the complete input, renders every diagram, sanitizes all
SVG and constructs the complete HTML before atomically replacing the
destination. Missing tooling or browser assets, invalid Mermaid syntax,
unsupported/unsafe SVG, unknown JSON keys and invalid schema all fail
explicitly; an existing artifact remains unchanged. The only browser-side
script is a static copy-to-clipboard helper (no content is interpolated into it,
and the CSP pins it by sha256 hash). There are no remote fonts or assets.
Colors follow the system light/dark theme and reset to the light palette when
printing. Closed details are forced open in printed output so evidence is not
lost. Each page stamps its own UTC generation time. Sources and bare https URLs
in text are clickable links, not fetched content; `http://` or credentialed
URLs stay plain text. Metadata values may be
`{"text": "...", "url": "https://..."}` to render as a hyperlink (useful for
pinned commit SHAs); a `Reviewed` date key is optional — the generation stamp
usually replaces it. Sections may carry a `location` (plain `path:line` string
or `{"text", "url"}`) shown muted under the heading. With top-level
`"kind": "review"`, every `Finding ...` section needs a `severity` (blocker |
should-fix | nit | question, rendered as a colored badge), a `location` and at
least one direct legacy `comments` entry or `comments` block, some heading must
contain `Verdict`, findings are
indexed under the summary with anchor links, and leftover
`<sha>`/`<number>`/`<owner>`/`<repo>` placeholders in fill-in slots fail the
render (quoting them inside content blocks is fine). Use
synthetic examples, not credentials or unnecessary production data. A failed
browser open reports the saved path, not a false success.

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

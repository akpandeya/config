# config

Personal dotfiles + macOS bootstrap. One-command setup for a fresh Mac.

## Quick start (new machine)

```bash
# 1. Install 1Password desktop app (App Store or https://1password.com)
#    Settings → Security → enable Touch ID
#    Settings → Developer → "Integrate with 1Password CLI"
#    Sign in to 1Password.

# 2. Clone this repo via HTTPS (SSH keys come later).
git clone https://github.com/akpandeya/config ~/code/personal/config
cd ~/code/personal/config

# 3. Run the bootstrap. It installs Homebrew, packages, Jarvis, and
#    exports SSH keys from 1Password onto disk.
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
| `claude/skills/` | User-level Claude Code skills (symlinked into `~/.claude/skills/`) |
| `claude/hooks/` | Claude Code PostToolUse hooks (e.g. `jarvis-register.sh` auto-subscribes PRs/Jira Claude creates) |
| `claude/settings-hooks.json` | Merged into `~/.claude/settings.json` — only replaces `hooks.PostToolUse`, preserves everything else |
| `git/` | gitconfig templates (one personal, one work, one default with conditional includes) |
| `kitty/` | Terminal config |
| `scripts/` | Helper scripts used by the bootstrap / `jarvis update` (e.g. `merge-claude-hooks.py`) |
| `shell/` | Shared shell aliases |
| `ssh/` | SSH-from-1Password installer (templates + `setup.sh`) |
| `starship/` | Prompt config |
| `setup-dev-env.sh` | Top-level bootstrap — Homebrew, git, SSH, Claude skills+hooks, Jarvis (clone + `make install` + launchd agents). Env vars: `SKIP_JARVIS=1`, `SKIP_SCHEDULES=1` |

## Common operations

```bash
# Re-run just the SSH setup (after adding a new key to 1Password)
./ssh/setup.sh

# Skip SSH setup (e.g. offline, or 1Password not ready)
SKIP_SSH=1 ./setup-dev-env.sh

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

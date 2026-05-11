#!/bin/bash

# Development Environment Setup Script
# This script sets up a fresh macOS machine with essential tools and configurations

set -e

echo "=== Development Environment Setup ==="
echo

# Check if Homebrew is installed
if ! command -v brew &> /dev/null; then
    echo "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
else
    echo "✓ Homebrew already installed"
fi

echo
echo "=== Installing Homebrew packages ==="
echo

# Install packages from brew-packages.txt
if [ -f "brew-packages.txt" ]; then
    while IFS= read -r package || [ -n "$package" ]; do
        # Skip comments and empty lines
        [[ "$package" =~ ^#.*$ ]] || [[ -z "$package" ]] && continue

        is_cask=false
        brew info --cask "$package" &>/dev/null && is_cask=true

        already_installed=false
        if $is_cask; then
            # brew list --cask fails for apps installed outside of brew (App Store, direct download)
            brew list --cask "$package" &>/dev/null && already_installed=true
            app_name="$(brew info --cask "$package" --json=v2 2>/dev/null | jq -r '.casks[0].artifacts[] | select(type=="object") | .app[]? // empty' 2>/dev/null | head -1)"
            [ -n "$app_name" ] && [ -d "/Applications/$app_name" ] && already_installed=true
        else
            brew list "$package" &>/dev/null && already_installed=true
        fi

        if $already_installed; then
            echo "✓ $package already installed"
        else
            echo "Installing $package..."
            if $is_cask; then
                brew install --cask "$package"
            else
                brew install "$package"
            fi
        fi
    done < brew-packages.txt
else
    echo "Warning: brew-packages.txt not found"
fi

echo
echo "=== Creating directory structure ==="
echo

mkdir -p ~/code/work
mkdir -p ~/code/personal
echo "✓ Created ~/code/work and ~/code/personal"

echo
echo "=== Setting up git configuration ==="
echo

REPO_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

cd "$REPO_DIR/git"
chmod +x setup.sh
./setup.sh
cd "$REPO_DIR"

echo
echo "=== Setting up SSH keys from 1Password ==="
echo

if [ "${SKIP_SSH:-0}" = "1" ]; then
    echo "SKIP_SSH=1 — skipping SSH setup."
else
    chmod +x "$REPO_DIR/ssh/setup.sh"
    # Don't abort the whole bootstrap if SSH setup fails (e.g. 1P not
    # signed in yet on a brand-new machine). Print the error and move on.
    "$REPO_DIR/ssh/setup.sh" || {
        echo
        echo "⚠ SSH setup failed. Rerun with:"
        echo "  cd $REPO_DIR && ./ssh/setup.sh"
        echo
    }
fi

echo
echo "=== Setting up terminal & prompt ==="
echo

link_config() {
    local src=$1
    local target=$2

    mkdir -p "$(dirname "$target")"

    if [ -L "$target" ] && [ "$(readlink "$target")" = "$src" ]; then
        echo "✓ $target already linked"
        return
    fi

    if [ -e "$target" ] || [ -L "$target" ]; then
        local backup="${target}.backup.$(date +%Y%m%d%H%M%S)"
        mv "$target" "$backup"
        echo "  Existing $target moved to $backup"
    fi

    ln -s "$src" "$target"
    echo "✓ Linked $target -> $src"
}

link_config "$REPO_DIR/kitty/kitty.conf"       "$HOME/.config/kitty/kitty.conf"
link_config "$REPO_DIR/kitty/tab_bar.py"       "$HOME/.config/kitty/tab_bar.py"
link_config "$REPO_DIR/starship/starship.toml" "$HOME/.config/starship.toml"
link_config "$REPO_DIR/nvim"                   "$HOME/.config/nvim"
link_config "$REPO_DIR/claude/skills/jarvis-suggest/SKILL.md" \
            "$HOME/.claude/skills/jarvis-suggest/SKILL.md"
link_config "$REPO_DIR/claude/skills/slack-catchup/SKILL.md" \
            "$HOME/.claude/skills/slack-catchup/SKILL.md"

# Generic PR / CI automation skills + their subagents. Keep the whole
# skill directory symlinked (not just SKILL.md) in case a skill grows
# scripts or reference docs alongside its entry point.
for skill in pr-create pr-watch pr-merge ci-fix desloppify prompt; do
    link_config "$REPO_DIR/claude/skills/$skill" \
                "$HOME/.claude/skills/$skill"
done

# Long-form prompts paste into fresh Claude sessions. Source of truth
# lives in claude/prompts/; symlink each *.md into ~/.claude/prompts/
# so the `prompt` skill can list and inject them.
for prompt_file in "$REPO_DIR"/claude/prompts/*.md; do
    [ -e "$prompt_file" ] || continue
    [ "$(basename "$prompt_file")" = "README.md" ] && continue
    link_config "$prompt_file" \
                "$HOME/.claude/prompts/$(basename "$prompt_file")"
done
for agent in ci-observer.md ci-fixer.md; do
    link_config "$REPO_DIR/claude/agents/$agent" \
                "$HOME/.claude/agents/$agent"
done

# Per-scope git identity + SSH signing keys. Symlink the repo's
# scoped files in as ~/.gitconfig-{personal,work}; they're pulled in
# by the includeIf blocks set below on the top-level ~/.gitconfig.
link_config "$REPO_DIR/gitconfig/private/.gitconfig" "$HOME/.gitconfig-personal"
link_config "$REPO_DIR/gitconfig/work/.gitconfig"    "$HOME/.gitconfig-work"

# Top-level ~/.gitconfig setup. Uses `git config --global` so we only
# touch the specific keys we care about; anything else the user has
# already set (credential helpers, aliases, core.editor) is preserved.
# All idempotent — re-running this script leaves a correct config
# unchanged.
setup_git_global() {
    # Identity: work email default (the ~/.gitconfig-work includeIf
    # file overrides this under ~/code/work/ anyway, but having a
    # sensible default avoids "Please tell me who you are" on fresh
    # clones outside that tree).
    git config --global user.name  "Avanindra Pandeya"
    git config --global user.email "avanindra.pandeya@hellofresh.de"

    # SSH signing. `gpg.ssh.program` is intentionally NOT set — the
    # default (system ssh-keygen) reads the on-disk private key
    # directly. Routing through 1Password's op-ssh-sign was unstable
    # ("failed to fill whole buffer" mid-commit), and the scoped
    # fragments already carry absolute paths to the on-disk keys.
    git config --global gpg.format     ssh
    git config --global commit.gpgsign true
    # If somebody previously set the 1Password helper, unset it.
    git config --global --unset-all gpg.ssh.program 2>/dev/null || true
    # Fall-back signing key (personal). Overridden by the
    # includeIf'd scope files under ~/code/{personal,work}/.
    git config --global user.signingkey "$HOME/.ssh/id_asus_fedora"

    # Verification: allowed_signers maps emails to pubkeys so
    # `git log --show-signature` actually verifies locally.
    mkdir -p "$HOME/.config/git"
    local signers="$HOME/.config/git/allowed_signers"
    {
        [ -f "$HOME/.ssh/id_asus_fedora.pub" ] && \
            echo "akpandeya1@gmail.com $(cat "$HOME/.ssh/id_asus_fedora.pub")"
        [ -f "$HOME/.ssh/id_hf_thinkpad.pub" ] && \
            echo "avanindra.pandeya@hellofresh.de $(cat "$HOME/.ssh/id_hf_thinkpad.pub")"
    } > "$signers"
    git config --global gpg.ssh.allowedSignersFile "$signers"

    # includeIf: point each scope at its fragment. Set-path'd
    # absolutely so `git config` handles canonicalisation.
    git config --global 'includeIf.gitdir:~/code/personal/.path' \
        "$HOME/.gitconfig-personal"
    git config --global 'includeIf.gitdir:~/code/work/.path' \
        "$HOME/.gitconfig-work"

    # Sane defaults (init branch, push behaviour).
    git config --global init.defaultBranch main
    git config --global push.default          current
    git config --global push.autoSetupRemote  true
    git config --global pull.rebase           false
}
setup_git_global
echo "✓ ~/.gitconfig signing + includeIf set (personal + work)"

if ! grep -q 'starship init zsh' "$HOME/.zshrc" 2>/dev/null; then
    printf '\n# starship prompt\neval "$(starship init zsh)"\n' >> "$HOME/.zshrc"
    echo "✓ Added starship init to ~/.zshrc"
else
    echo "✓ starship init already in ~/.zshrc"
fi

ALIASES_LINE="[ -f \"$REPO_DIR/shell/aliases.sh\" ] && source \"$REPO_DIR/shell/aliases.sh\""
if ! grep -qF "$REPO_DIR/shell/aliases.sh" "$HOME/.zshrc" 2>/dev/null; then
    printf '\n# shared shell aliases\n%s\n' "$ALIASES_LINE" >> "$HOME/.zshrc"
    echo "✓ Added shared aliases source to ~/.zshrc"
else
    echo "✓ shared aliases already sourced in ~/.zshrc"
fi

echo
echo "=== Installing desloppify ==="
echo

# Codebase health scanner used by Claude Code. The skill itself is
# already symlinked above; this just makes the `desloppify` CLI
# available globally via uv's tool dir (~/.local/bin). `uv tool install
# --upgrade` is a no-op when the version already matches, so re-running
# this script is cheap.
if [ "${SKIP_DESLOPPIFY:-0}" = "1" ]; then
    echo "SKIP_DESLOPPIFY=1 — skipping desloppify install."
else
    uv tool install --upgrade "desloppify[full]"
    echo "✓ desloppify CLI installed (skill is symlinked under ~/.claude/skills/desloppify)"
    echo "  When desloppify ships a new SKILL.md (e.g. v6 → v7), refresh it with:"
    echo "    cd $REPO_DIR && desloppify update-skill claude"
    echo "    git -C $REPO_DIR add claude/skills/desloppify/SKILL.md && git -C $REPO_DIR commit -m 'chore: bump desloppify skill'"
fi

echo
echo "=== Installing Jarvis ==="
echo

JARVIS_DIR="$HOME/code/personal/jarvis"

if [ "${SKIP_JARVIS:-0}" = "1" ]; then
    echo "SKIP_JARVIS=1 — skipping Jarvis install."
else
    if [ ! -d "$JARVIS_DIR" ]; then
        echo "Cloning jarvis..."
        git clone git@github.com-personal:akpandeya/jarvis.git "$JARVIS_DIR"
    fi

    echo "Building frontend + installing jarvis..."
    # `make install` handles: npm ci + frontend build, uv build wheel,
    # uv tool install, and registering the repo path at ~/.jarvis/repo_path.
    (cd "$JARVIS_DIR" && make install)

    # jarvis init is safe to re-run — creates config + db if absent.
    jarvis init

    if [ "${SKIP_SCHEDULES:-0}" = "1" ]; then
        echo "SKIP_SCHEDULES=1 — skipping launchd agents."
    else
        echo "Installing launchd agents..."
        jarvis schedule install            # ingest every 15 min
        jarvis schedule-pr-refresh install # hourly PR refresh 09–17
        jarvis schedule-menubar install    # persistent menubar icon
    fi

    # Merge the Claude Code PostToolUse hook fragment into settings.json.
    # Idempotent; preserves every other top-level key.
    if [ -f "$REPO_DIR/scripts/merge-claude-hooks.py" ]; then
        python3 "$REPO_DIR/scripts/merge-claude-hooks.py"
    fi

    echo "✓ Jarvis installed and initialised"
    echo "  Edit ~/.jarvis/config.toml to configure integrations"
    echo "  Set work_domains under [thunderbird] to label your work emails"
    echo "  Add Firefox profile labels under [[firefox.profiles]] if desired"
fi

echo
echo "=== Development Environment Setup Complete! ==="
echo
echo "Next steps:"
echo "  1. Configure Jira CLI: jira init"
echo "  2. Clone your repositories"
echo "  3. Edit ~/.jarvis/config.toml to configure Jarvis integrations"

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

        if brew list "$package" &>/dev/null; then
            echo "✓ $package already installed"
        else
            echo "Installing $package..."
            if [[ "$package" == font-* ]]; then
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
link_config "$REPO_DIR/claude/skills/jarvis-suggest/SKILL.md" \
            "$HOME/.claude/skills/jarvis-suggest/SKILL.md"
link_config "$REPO_DIR/claude/skills/slack-catchup/SKILL.md" \
            "$HOME/.claude/skills/slack-catchup/SKILL.md"

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

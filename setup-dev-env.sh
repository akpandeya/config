#!/bin/bash

# Development Environment Setup Script
# This script sets up a fresh macOS machine with essential tools and configurations

set -e

# --- OS Detection ---
OS_TYPE="$(uname -s)"
echo "=== Development Environment Setup ==="
echo "OS Detected: $OS_TYPE"
echo

# --- Profile Selection ---
if [ -z "$SETUP_MODE" ]; then
    if [ -t 0 ]; then
        echo "Select setup profile:"
        echo "  1) Work (sets up both work and personal configs & credentials)"
        echo "  2) Personal (sets up only personal configs & credentials)"
        read -p "Choose option [1 or 2, default: 2]: " mode_opt
        case "$mode_opt" in
            1) SETUP_MODE="work" ;;
            *) SETUP_MODE="personal" ;;
        esac
    else
        SETUP_MODE="personal"
    fi
fi
export SETUP_MODE
echo "Profile Selected: $SETUP_MODE"
echo

# Check if Homebrew is installed (macOS only or Linux if brew is preferred)
if [ "$OS_TYPE" = "Darwin" ]; then
    if ! command -v brew &> /dev/null; then
        echo "Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    else
        echo "✓ Homebrew already installed"
    fi
fi

echo
echo "=== Parsing packages ==="
echo

# Categorize package lists
GROUP_CORE=""
GROUP_TERMINAL=""
GROUP_WORK=""

# Parse brew-packages.txt
if [ -f "brew-packages.txt" ]; then
    current_group=""
    while IFS= read -r line || [ -n "$line" ]; do
        # Check for group header
        if [[ "$line" =~ ^#[[:space:]]*Group:[[:space:]]*(.*)$ ]]; then
            current_group="${BASH_REMATCH[1]}"
        elif [[ "$line" =~ ^# ]] || [[ -z "$line" ]]; then
            continue
        else
            # Strip trailing/leading whitespace
            pkg=$(echo "$line" | tr -d '\r' | xargs)
            case "$current_group" in
                Core) GROUP_CORE+="$pkg " ;;
                Terminal) GROUP_TERMINAL+="$pkg " ;;
                Work) GROUP_WORK+="$pkg " ;;
                *) GROUP_CORE+="$pkg " ;; # Fallback
            esac
        fi
    done < brew-packages.txt
else
    echo "Warning: brew-packages.txt not found"
fi

# Determine packages to install
PACKAGES_TO_INSTALL=""

# If stdout is a TTY and CHOOSE_PACKAGES is not set to "all", prompt the user
if [ -t 0 ] && [ "${CHOOSE_PACKAGES:-prompt}" = "prompt" ]; then
    echo "Select which groups of packages you want to install:"
    echo
    
    install_core="y"
    read -p "Install Core Utilities (git, gh, 1password, uv, jq, etc.)? [Y/n]: " resp
    [[ "$resp" =~ ^[Nn] ]] && install_core="n"
    
    install_terminal="y"
    read -p "Install Terminal Environment (kitty, zsh, starship, neovim, ripgrep, etc.)? [Y/n]: " resp
    [[ "$resp" =~ ^[Nn] ]] && install_terminal="n"
    
    install_work="y"
    if [ "$SETUP_MODE" = "personal" ]; then
        install_work="n"
        read -p "Install DevOps & Work Tools (jira-cli, docker, kubectl, stern, awscli, vault)? [y/N]: " resp
        [[ "$resp" =~ ^[Yy] ]] && install_work="y"
    else
        read -p "Install DevOps & Work Tools (jira-cli, docker, kubectl, stern, awscli, vault)? [Y/n]: " resp
        [[ "$resp" =~ ^[Nn] ]] && install_work="n"
    fi
    
    echo
    read -p "Do you want to customize/select individual packages? [y/N]: " resp
    if [[ "$resp" =~ ^[Yy] ]]; then
        if [ "$install_core" = "y" ]; then
            for pkg in $GROUP_CORE; do
                read -p "  Install $pkg? [Y/n]: " r
                [[ ! "$r" =~ ^[Nn] ]] && PACKAGES_TO_INSTALL+="$pkg "
            done
        fi
        if [ "$install_terminal" = "y" ]; then
            for pkg in $GROUP_TERMINAL; do
                read -p "  Install $pkg? [Y/n]: " r
                [[ ! "$r" =~ ^[Nn] ]] && PACKAGES_TO_INSTALL+="$pkg "
            done
        fi
        if [ "$install_work" = "y" ]; then
            for pkg in $GROUP_WORK; do
                read -p "  Install $pkg? [Y/n]: " r
                [[ ! "$r" =~ ^[Nn] ]] && PACKAGES_TO_INSTALL+="$pkg "
            done
        fi
    else
        [ "$install_core" = "y" ] && PACKAGES_TO_INSTALL+="$GROUP_CORE"
        [ "$install_terminal" = "y" ] && PACKAGES_TO_INSTALL+="$GROUP_TERMINAL"
        [ "$install_work" = "y" ] && PACKAGES_TO_INSTALL+="$GROUP_WORK"
    fi
else
    # Non-interactive / unattended run: install based on SETUP_MODE
    PACKAGES_TO_INSTALL+="$GROUP_CORE $GROUP_TERMINAL "
    if [ "$SETUP_MODE" = "work" ]; then
        PACKAGES_TO_INSTALL+="$GROUP_WORK "
    fi
fi

echo
echo "=== Installing packages ==="
echo

# Modular Package Installer
install_package() {
    local pkg=$1
    if [ "$OS_TYPE" = "Darwin" ] || command -v brew &>/dev/null; then
        is_cask=false
        # Casks only apply on macOS/Darwin
        if [ "$OS_TYPE" = "Darwin" ]; then
            brew info --cask "$pkg" &>/dev/null && is_cask=true
        fi

        already_installed=false
        if $is_cask; then
            # brew list --cask fails for apps installed outside of brew (App Store, direct download)
            brew list --cask "$pkg" &>/dev/null && already_installed=true
            app_name="$(brew info --cask "$pkg" --json=v2 2>/dev/null | jq -r '.casks[0].artifacts[] | select(type=="object") | .app[]? // empty' 2>/dev/null | head -1)"
            [ -n "$app_name" ] && [ -d "/Applications/$app_name" ] && already_installed=true
        else
            brew list "$pkg" &>/dev/null && already_installed=true
        fi

        if $already_installed; then
            echo "✓ $pkg already installed"
        else
            echo "Installing $pkg..."
            if $is_cask; then
                brew install --cask "$pkg"
            else
                brew install "$pkg"
            fi
        fi
    elif [ "$OS_TYPE" = "Linux" ]; then
        # Linux systems fallback
        if command -v apt-get &>/dev/null; then
            if dpkg -s "$pkg" &>/dev/null; then
                echo "✓ $pkg already installed"
            else
                echo "Installing $pkg via apt..."
                sudo apt-get update && sudo apt-get install -y "$pkg"
            fi
        elif command -v pacman &>/dev/null; then
            if pacman -Qi "$pkg" &>/dev/null; then
                echo "✓ $pkg already installed"
            else
                echo "Installing $pkg via pacman..."
                sudo pacman -S --noconfirm "$pkg"
            fi
        elif command -v dnf &>/dev/null; then
            if dnf list installed "$pkg" &>/dev/null; then
                echo "✓ $pkg already installed"
            else
                echo "Installing $pkg via dnf..."
                sudo dnf install -y "$pkg"
            fi
        else
            echo "Warning: No supported package manager found to install $pkg"
        fi
    fi
}

for package in $PACKAGES_TO_INSTALL; do
    install_package "$package"
done

echo
echo "=== Creating directory structure ==="
echo

if [ "$SETUP_MODE" = "personal" ]; then
    mkdir -p ~/code/personal
    echo "✓ Created ~/code/personal"
else
    mkdir -p ~/code/work
    mkdir -p ~/code/personal
    echo "✓ Created ~/code/work and ~/code/personal"
fi

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

# --- Setup Shared Antigravity (AGY) & Claude Global Settings and Skills ---

# Global Instructions / Memory files
link_config "$REPO_DIR/claude/CLAUDE.md" "$HOME/.claude/CLAUDE.md"
link_config "$REPO_DIR/gemini/GEMINI.md" "$HOME/.gemini/GEMINI.md"

# Antigravity personal-skills plugin setup
mkdir -p "$HOME/.gemini/config/plugins/personal-skills/skills"
link_config "$REPO_DIR/claude/personal-skills-plugin.json" \
            "$HOME/.gemini/config/plugins/personal-skills/plugin.json"

# Symlink all user-level skills to Antigravity's personal-skills plugin
for skill in jarvis-suggest slack-catchup pr-create pr-watch pr-merge ci-fix desloppify prompt; do
    link_config "$REPO_DIR/claude/skills/$skill" \
                "$HOME/.gemini/config/plugins/personal-skills/skills/$skill"
done

# --- End Shared Antigravity Setup ---

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
if [ "$SETUP_MODE" = "work" ]; then
    link_config "$REPO_DIR/gitconfig/work/.gitconfig"    "$HOME/.gitconfig-work"
else
    if [ -e "$HOME/.gitconfig-work" ] || [ -L "$HOME/.gitconfig-work" ]; then
        rm -f "$HOME/.gitconfig-work"
        echo "✓ Removed $HOME/.gitconfig-work"
    fi
fi

# Top-level ~/.gitconfig setup. Uses `git config --global` so we only
# touch the specific keys we care about; anything else the user has
# already set (credential helpers, aliases, core.editor) is preserved.
# All idempotent — re-running this script leaves a correct config
# unchanged.
setup_git_global() {
    # Identity: default user email based on SETUP_MODE
    git config --global user.name  "Avanindra Pandeya"
    if [ "$SETUP_MODE" = "work" ]; then
        git config --global user.email "avanindra.pandeya@hellofresh.de"
    else
        git config --global user.email "akpandeya1@gmail.com"
    fi

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
        if [ "$SETUP_MODE" = "work" ]; then
            [ -f "$HOME/.ssh/id_hf_thinkpad.pub" ] && \
                echo "avanindra.pandeya@hellofresh.de $(cat "$HOME/.ssh/id_hf_thinkpad.pub")"
        fi
    } > "$signers"
    git config --global gpg.ssh.allowedSignersFile "$signers"

    # includeIf: point each scope at its fragment. Set-path'd
    # absolutely so `git config` handles canonicalisation.
    git config --global 'includeIf.gitdir:~/code/personal/.path' \
        "$HOME/.gitconfig-personal"
    if [ "$SETUP_MODE" = "work" ]; then
        git config --global 'includeIf.gitdir:~/code/work/.path' \
            "$HOME/.gitconfig-work"
    else
        git config --global --unset-all 'includeIf.gitdir:~/code/work/.path' 2>/dev/null || true
    fi

    # Sane defaults (init branch, push behaviour).
    git config --global init.defaultBranch main
    git config --global push.default          current
    git config --global push.autoSetupRemote  true
    git config --global pull.rebase           false
}
setup_git_global
echo "✓ ~/.gitconfig signing + includeIf set"

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

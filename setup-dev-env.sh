#!/bin/bash

# Development Environment Setup Script
# This script sets up a fresh macOS machine with essential tools and configurations

set -e

DRY_RUN="${DRY_RUN:-0}"

REPO_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ATELIER_DIR="$( cd "$REPO_DIR/.." && pwd )/atelier"

# Atelier supplies the renderer, overlay, shared feedback skill and OpenCode
# command linked below. Validate every required source before installing
# packages or changing the machine; skipping Mermaid dependencies does not make
# the rest of the integration optional. This check also runs under DRY_RUN so a
# preview cannot claim that an incomplete checkout would work.
preflight_atelier() {
    echo "=== Checking required atelier integration ==="
    echo "Atelier checkout: $ATELIER_DIR"
    if [ ! -d "$ATELIER_DIR" ]; then
        echo "ERROR: atelier is required next to config ($ATELIER_DIR)." >&2
        echo "Clone https://github.com/akpandeya/atelier there before running setup." >&2
        exit 1
    fi

    local required_inputs=(
        "scripts/agent-explainer.py"
        "scripts/artifact-overlay.js"
        "scripts/mermaid/package.json"
        "scripts/mermaid/package-lock.json"
        "agents/artifact-feedback.md"
        "skills/artifact-feedback/SKILL.md"
        "opencode/command/artifact-feedback.md"
    )
    local missing=0
    local relative
    for relative in "${required_inputs[@]}"; do
        if [ ! -f "$ATELIER_DIR/$relative" ]; then
            echo "ERROR: required atelier input is missing: $ATELIER_DIR/$relative" >&2
            missing=1
        fi
    done
    if [ "$missing" -ne 0 ]; then
        echo "Update or restore the atelier checkout before running setup." >&2
        exit 1
    fi
    echo "✓ All required atelier integration inputs are present"
    echo
}
preflight_atelier

# --- OS Detection ---
OS_TYPE="$(uname -s)"
echo "=== Development Environment Setup ==="
echo "OS Detected: $OS_TYPE"
if [ "$DRY_RUN" = "1" ]; then
    echo "=== DRY RUN — no changes will be made ==="
fi
echo

# --- Profile Selection ---
if [ -z "$SETUP_MODE" ]; then
    # Infer the profile from what is already configured on this machine, so a
    # re-run never silently deletes ~/.gitconfig-work or unsets the work
    # includeIf just because SETUP_MODE was not passed again.
    detected_mode="personal"
    if [ -f "$HOME/.gitconfig-work" ] || \
       git config --global --get 'includeIf.gitdir:~/code/work/.path' >/dev/null 2>&1; then
        detected_mode="work"
    fi
    SETUP_MODE="$detected_mode"
    if [ -t 0 ]; then
        echo "Select setup profile:"
        echo "  1) Work (sets up both work and personal configs & credentials)"
        echo "  2) Personal (sets up only personal configs & credentials)"
        echo "  Detected on this machine: $detected_mode"
        read -p "Choose option [1 or 2, default: $detected_mode]: " mode_opt
        case "$mode_opt" in
            1) SETUP_MODE="work" ;;
            2) SETUP_MODE="personal" ;;
        esac
    fi
fi
export SETUP_MODE
echo "Profile Selected: $SETUP_MODE"
echo

# Check if Homebrew is installed (macOS only or Linux if brew is preferred)
if [ "$OS_TYPE" = "Darwin" ]; then
    if ! command -v brew &> /dev/null; then
        if [ "$DRY_RUN" = "1" ]; then
            echo "Would install: Homebrew"
        else
            echo "Installing Homebrew..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        fi
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
        elif [ "$DRY_RUN" = "1" ]; then
            if $is_cask; then
                echo "Would install: $pkg (cask)"
            else
                echo "Would install: $pkg"
            fi
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
            elif [ "$DRY_RUN" = "1" ]; then
                echo "Would install: $pkg (apt)"
            else
                echo "Installing $pkg via apt..."
                sudo apt-get update && sudo apt-get install -y "$pkg"
            fi
        elif command -v pacman &>/dev/null; then
            if pacman -Qi "$pkg" &>/dev/null; then
                echo "✓ $pkg already installed"
            elif [ "$DRY_RUN" = "1" ]; then
                echo "Would install: $pkg (pacman)"
            else
                echo "Installing $pkg via pacman..."
                sudo pacman -S --noconfirm "$pkg"
            fi
        elif command -v dnf &>/dev/null; then
            if dnf list installed "$pkg" &>/dev/null; then
                echo "✓ $pkg already installed"
            elif [ "$DRY_RUN" = "1" ]; then
                echo "Would install: $pkg (dnf)"
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

if [ "$DRY_RUN" = "1" ]; then
    if [ "$SETUP_MODE" = "personal" ]; then
        echo "Would create: ~/code/personal"
    else
        echo "Would create: ~/code/work and ~/code/personal"
    fi
elif [ "$SETUP_MODE" = "personal" ]; then
    mkdir -p ~/code/personal
    echo "✓ Created ~/code/personal"
else
    mkdir -p ~/code/work
    mkdir -p ~/code/personal
    echo "✓ Created ~/code/work and ~/code/personal"
fi

echo
echo "=== Installing Pi CLI ==="
echo

# Homebrew packages (including node) are installed before the Pi CLI.
DRY_RUN="$DRY_RUN" bash "$REPO_DIR/scripts/install-pi.sh"

# Git identity is owned further down by the gitconfig/ render + setup_git_global
# path, which reads gitconfig/emails.local.env and never prompts. Do not add an
# interactive git-identity step here: an earlier one asked for name/emails on
# every run and then had its output overwritten a few steps later.

echo
echo "=== Setting up SSH keys from 1Password ==="
echo

if [ "${SKIP_SSH:-0}" = "1" ]; then
    echo "SKIP_SSH=1 — skipping SSH setup."
elif [ "$DRY_RUN" = "1" ]; then
    echo "Would run: $REPO_DIR/ssh/setup.sh (dry-run mode not supported by that script — skipped)"
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

    if [ -L "$target" ] && [ "$(readlink "$target")" = "$src" ]; then
        echo "✓ $target already linked"
        return
    fi

    if [ "$DRY_RUN" = "1" ]; then
        if [ -e "$target" ] || [ -L "$target" ]; then
            echo "Would back up existing $target"
        fi
        echo "Would link: $target -> $src"
        return
    fi

    mkdir -p "$(dirname "$target")"

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

# Pi extensions are auto-discovered from ~/.pi/agent/extensions/, so the repo
# can own them. plan-mode is vendored from the pi package's examples — see
# pi/README.md for the pinned version, local tweaks and update steps.
link_config "$REPO_DIR/pi/extensions/plan-mode" \
            "$HOME/.pi/agent/extensions/plan-mode"
link_config "$REPO_DIR/pi/extensions/background-compaction.ts" \
            "$HOME/.pi/agent/extensions/background-compaction.ts"
# compaction-overrides keeps compaction.modelOverrides in sync with the
# machine's own models.json (1M-context models get reserveTokens 750000) so
# the hand-listed overrides port to machines with different provider ids.
link_config "$REPO_DIR/pi/extensions/compaction-overrides.ts" \
            "$HOME/.pi/agent/extensions/compaction-overrides.ts"
# questionnaire is vendored from the pi examples too: plan-mode's clarify-first
# flow calls it, and it is not a built-in tool.
link_config "$REPO_DIR/pi/extensions/questionnaire.ts" \
            "$HOME/.pi/agent/extensions/questionnaire.ts"
# inline-bash expands !{command} in prompts before sending (see pi/README.md).
link_config "$REPO_DIR/pi/extensions/inline-bash.ts" \
            "$HOME/.pi/agent/extensions/inline-bash.ts"
# readonly-bash tool-enforces the plan-mode bash allowlist in child pi
# processes: subagent dispatches pass --readonly-bash for agents whose
# frontmatter sets bashAllowlist (e.g. the reviewer).
link_config "$REPO_DIR/pi/extensions/readonly-bash.ts" \
            "$HOME/.pi/agent/extensions/readonly-bash.ts"
# subagent delegates tasks to isolated pi processes. Its sample agents and
# workflow prompts live in subdirectories and must be linked separately.
link_config "$REPO_DIR/pi/extensions/subagent" \
            "$HOME/.pi/agent/extensions/subagent"
mkdir -p "$HOME/.pi/agent/agents" "$HOME/.pi/agent/prompts"
for agent_md in "$REPO_DIR"/pi/extensions/subagent/agents/*.md; do
    link_config "$agent_md" "$HOME/.pi/agent/agents/$(basename "$agent_md")"
done
for prompt_md in "$REPO_DIR"/pi/extensions/subagent/prompts/*.md; do
    link_config "$prompt_md" "$HOME/.pi/agent/prompts/$(basename "$prompt_md")"
done
# The remaining vendored extensions are active by default too:
# dynamic-tools (runtime tool registration), rtk (rewrites bash commands
# through the rtk CLI for token savings; needs rtk >= 0.23 in PATH, which
# brew-packages.txt installs) and ask-user (option-based question dialogs).
link_config "$REPO_DIR/pi/extensions/dynamic-tools.ts" \
            "$HOME/.pi/agent/extensions/dynamic-tools.ts"
link_config "$REPO_DIR/pi/extensions/rtk.ts" \
            "$HOME/.pi/agent/extensions/rtk.ts"
link_config "$REPO_DIR/pi/extensions/ask-user.ts" \
            "$HOME/.pi/agent/extensions/ask-user.ts"
# keybindings.json moves app.thinking.cycle off Shift+Tab so plan-mode can own
# Shift+Tab for the plan <-> execute switch (Pi reserves built-in keys).
link_config "$REPO_DIR/pi/keybindings.json" \
            "$HOME/.pi/agent/keybindings.json"
# Theme file; settings.json's theme setting selects matrix-dark.
link_config "$REPO_DIR/pi/themes/matrix-dark.json" \
            "$HOME/.pi/agent/themes/matrix-dark.json"

# Scoped harness launchers. Plain harnesses get no scoped-memory protocol;
# wrappers share one resolver and verify the external memory repository.
for launcher in agent-profile pi-personal pi-work opencode-personal opencode-work \
                claude-personal claude-work copilot-personal copilot-work; do
    link_config "$REPO_DIR/agents/bin/$launcher" "$HOME/.local/bin/$launcher"
done

# The self-hosted ddg-search MCP server (pi/README.md): install its pinned
# dependencies and register it user-level. npm i is idempotent; the mcp.json
# merge never removes servers the user added themselves.
if command -v node >/dev/null 2>&1; then
    if [ "$DRY_RUN" = "1" ]; then
        echo "Would run: npm i --prefix $REPO_DIR/pi/mcp/ddg-search"
    else
        npm i --prefix "$REPO_DIR/pi/mcp/ddg-search" --no-audit --no-fund >/dev/null 2>&1 \
            || echo "  WARNING: npm i failed in pi/mcp/ddg-search; ddgsearch will not connect"
    fi
    if [ "$DRY_RUN" = "1" ]; then
        if [ -f "$HOME/.pi/agent/mcp.json" ] \
            && grep -q '"ddgsearch"' "$HOME/.pi/agent/mcp.json" 2>/dev/null; then
            echo "✓ ddgsearch already registered in $HOME/.pi/agent/mcp.json"
        else
            echo "Would register ddgsearch in $HOME/.pi/agent/mcp.json -> $REPO_DIR/pi/mcp/ddg-search/server.mjs"
        fi
    else
        node -e '
        const fs = require("fs");
        const path = process.argv[1], server = process.argv[2];
        let cfg = {};
        if (fs.existsSync(path)) {
            try { cfg = JSON.parse(fs.readFileSync(path, "utf8")); }
            catch { console.log("  WARNING: " + path + " is not valid JSON; leaving it untouched"); process.exit(0); }
        }
        cfg.mcpServers = cfg.mcpServers || {};
        if (cfg.mcpServers.ddgsearch) { console.log("\u2713 ddgsearch already registered in " + path); process.exit(0); }
        cfg.mcpServers.ddgsearch = { command: "node", args: [server] };
        fs.mkdirSync(require("path").dirname(path), { recursive: true });
        fs.writeFileSync(path, JSON.stringify(cfg, null, 2) + "\n");
        console.log("\u2713 Registered ddgsearch in " + path);
    ' "$HOME/.pi/agent/mcp.json" "$REPO_DIR/pi/mcp/ddg-search/server.mjs"
    fi
else
    echo "  node not found; skipping ddg-search MCP setup"
fi
link_config "$REPO_DIR/claude/skills/jarvis-suggest/SKILL.md" \
            "$HOME/.claude/skills/jarvis-suggest/SKILL.md"
link_config "$REPO_DIR/claude/skills/slack-catchup/SKILL.md" \
            "$HOME/.claude/skills/slack-catchup/SKILL.md"

# Every non-jarvis skill is symlinked whole-dir into ~/.claude/skills/ (not
# just SKILL.md) so a skill can grow scripts or reference docs alongside its
# entry point. Driven by a glob so it never drifts from the repo contents.
# Skills live in two repo locations: the harness-neutral skills/ (shared with
# pi/opencode/copilot via ~/.agents/skills, see below) and claude/skills/
# (harness-coupled: jarvis-managed skills and Claude-only glue; shared skills
# live in skills/ above).
# Jarvis-managed skills (jarvis-suggest, jarvis-continue-in-phone,
# slack-catchup) are handled separately above or by Jarvis itself.
for skills_root in "$REPO_DIR/skills" "$REPO_DIR/claude/skills"; do
    for skill_dir in "$skills_root"/*/; do
        [ -f "$skill_dir/SKILL.md" ] || continue
        skill="$(basename "$skill_dir")"
        case "$skill" in
            jarvis-suggest|jarvis-continue-in-phone|slack-catchup) continue ;;
        esac
        link_config "$skill_dir" "$HOME/.claude/skills/$skill"
    done
done

# Agent Skills shared location: ~/.agents/skills/ is read natively by pi,
# opencode and copilot. Only the harness-neutral skills/ tree goes here —
# claude/skills entries stay Claude-only unless later promoted.
if [ "$DRY_RUN" = "1" ]; then
    echo "Would create: $HOME/.agents/skills"
else
    mkdir -p "$HOME/.agents/skills"
fi
for skill_dir in "$REPO_DIR"/skills/*/; do
    [ -f "$skill_dir/SKILL.md" ] || continue
    skill="$(basename "$skill_dir")"
    link_config "$skill_dir" "$HOME/.agents/skills/$skill"
done

# --- Setup Shared Antigravity (AGY) & Claude Global Settings and Skills ---

link_config "$REPO_DIR/claude/RTK.md"    "$HOME/.claude/RTK.md"
link_config "$REPO_DIR/opencode/agent"      "$HOME/.config/opencode/agent"
link_config "$REPO_DIR/opencode/command"    "$HOME/.config/opencode/command"

# Antigravity CLI Settings and Statusline
link_config "$REPO_DIR/gemini/settings.json" "$HOME/.gemini/antigravity-cli/settings.json"
link_config "$REPO_DIR/gemini/statusline.sh" "$HOME/.gemini/antigravity-cli/statusline.sh"
link_config "$REPO_DIR/gemini/fetch_quota.js" "$HOME/.gemini/antigravity-cli/scratch/fetch_quota.js"
link_config "$REPO_DIR/gemini/package.json" "$HOME/.gemini/antigravity-cli/scratch/package.json"
link_config "$REPO_DIR/gemini/package-lock.json" "$HOME/.gemini/antigravity-cli/scratch/package-lock.json"

# Install scratch dependencies for fetch_quota.js
if [ -f "$HOME/.gemini/antigravity-cli/scratch/package.json" ]; then
    if [ "$DRY_RUN" = "1" ]; then
        echo "Would run: npm install (Antigravity CLI statusline deps)"
    else
        echo "=== Installing dependencies for Antigravity CLI statusline ==="
        (cd "$HOME/.gemini/antigravity-cli/scratch" && npm install)
    fi
fi

# Pinned local Mermaid renderer for the atelier repo's agent-explainer.py (the
# artifact toolchain lives there; see $ATELIER_DIR). npm ci is an
# explicit setup step: Puppeteer's approved postinstall downloads the matching
# headless Chrome once, while normal explanation generation uses only these
# installed local files and never fetches packages or browsers.
if [ "${SKIP_MERMAID:-0}" = "1" ]; then
    echo "SKIP_MERMAID=1 — skipping Mermaid dependencies only; atelier links are still required."
elif [ "$DRY_RUN" = "1" ]; then
    echo "Would run: npm ci --prefix $ATELIER_DIR/scripts/mermaid"
else
    echo "=== Installing agent explainer Mermaid dependencies ==="
    npm ci --prefix "$ATELIER_DIR/scripts/mermaid" --no-audit --no-fund
    echo "✓ Mermaid CLI + pinned headless Chrome installed for agent-explainer.py"
fi


# Antigravity personal-skills plugin setup
if [ "$DRY_RUN" = "1" ]; then
    echo "Would create: $HOME/.gemini/config/plugins/personal-skills/skills"
else
    mkdir -p "$HOME/.gemini/config/plugins/personal-skills/skills"
fi
link_config "$REPO_DIR/claude/personal-skills-plugin.json" \
            "$HOME/.gemini/config/plugins/personal-skills/plugin.json"

# Symlink all non-jarvis skills to Antigravity's personal-skills plugin. The same
# skill files serve every harness, so there are no separate gemini copies.
for skills_root in "$REPO_DIR/skills" "$REPO_DIR/claude/skills"; do
    for skill_dir in "$skills_root"/*/; do
        [ -f "$skill_dir/SKILL.md" ] || continue
        skill="$(basename "$skill_dir")"
        case "$skill" in
            jarvis-suggest|jarvis-continue-in-phone|slack-catchup) continue ;;
        esac
        link_config "$skill_dir" \
                    "$HOME/.gemini/config/plugins/personal-skills/skills/$skill"
    done
done

# Stable path for the harness-neutral helper scripts used by the epic skills.
# Skills reference ~/.config/agent-context/scripts, not the repo checkout path.
if [ "$DRY_RUN" = "1" ]; then
    echo "Would create: $HOME/.config/agent-context"
else
    mkdir -p "$HOME/.config/agent-context"
fi
link_config "$REPO_DIR/claude/scripts" "$HOME/.config/agent-context/scripts"

# Private skill links must follow creation of the Gemini plugin directory.
PRIVATE_INSTALLER="$HOME/code/work/hf-workbench/scripts/install-agent-context.py"
if [ "$SETUP_MODE" = "work" ] && [ -f "$PRIVATE_INSTALLER" ]; then
    if [ "$DRY_RUN" = "1" ]; then
        echo "Would install private skills and context via $PRIVATE_INSTALLER --links-only"
    else
        python3 "$PRIVATE_INSTALLER" --links-only
    fi
fi
if [ "$DRY_RUN" = "1" ]; then
    python3 "$REPO_DIR/scripts/install-agent-instructions.py" --dry-run
else
    python3 "$REPO_DIR/scripts/install-agent-instructions.py"
fi

# The composer has now preflighted every scoped config root. Only after that
# validation may link_config write profile resources: a symlinked parent must
# never redirect work resources into personal storage (or vice versa).
# Auth, model endpoints, MCP servers and settings remain profile-specific.
for profile in personal work; do
    profile_root="$HOME/.agent/profiles/$profile"
    link_config "$HOME/.pi/agent/extensions" "$profile_root/pi/extensions"
    link_config "$HOME/.pi/agent/keybindings.json" "$profile_root/pi/keybindings.json"
    if [ -d "$HOME/.pi/agent/themes" ]; then
        link_config "$HOME/.pi/agent/themes" "$profile_root/pi/themes"
    fi
    if [ -d "$HOME/.config/opencode/command" ]; then
        link_config "$HOME/.config/opencode/command" "$profile_root/opencode/command"
    fi
done
# Ticket-routing subagents and prompts belong only to the work Pi profile.
link_config "$HOME/.pi/agent/agents" "$HOME/.agent/profiles/work/pi/agents"
link_config "$HOME/.pi/agent/prompts" "$HOME/.agent/profiles/work/pi/prompts"

# --- End Shared Antigravity Setup ---

# rtk: CLI proxy that filters/summarizes command output before it reaches
# the LLM. The Claude Code half runs with --hook-only: it merges the
# PreToolUse hook into settings.json and nothing else. RTK.md is repo-owned
# (claude/RTK.md, linked above) and composed into Claude/OpenCode instructions.
# A plain `rtk init -g --auto-patch` would mutate the generated instructions,
# so never run it against a real HOME. The OpenCode half only
# installs the plugin file. Both calls are idempotent and non-interactive
# (--auto-patch), so safe to re-run on every setup.
if command -v rtk >/dev/null 2>&1; then
    if [ "$DRY_RUN" = "1" ]; then
        echo "Would run: rtk init -g --hook-only --auto-patch && rtk init -g --opencode --auto-patch"
    else
        echo "=== Setting up rtk (LLM token-saving CLI proxy) ==="
        # Two separate calls: combining --opencode with the base call skips the
        # Claude Code half, so each harness needs its own invocation.
        rtk init -g --hook-only --auto-patch
        rtk init -g --opencode --auto-patch
    fi
else
    echo "rtk not found on PATH, skipping rtk init (install it via brew-packages.txt)"
fi

# Long-form prompts paste into fresh Claude sessions. Source of truth
# lives in claude/prompts/; symlink each *.md into ~/.claude/prompts/
# so the `prompt` skill can list and inject them.
for prompt_file in "$REPO_DIR"/claude/prompts/*.md; do
    [ -e "$prompt_file" ] || continue
    [ "$(basename "$prompt_file")" = "README.md" ] && continue
    link_config "$prompt_file" \
                "$HOME/.claude/prompts/$(basename "$prompt_file")"
done
for agent in doc-writer.md; do
    link_config "$REPO_DIR/claude/agents/$agent" \
                "$HOME/.claude/agents/$agent"
done

# Pi prompt templates: /pick-up-ticket in pi sessions.
if [ "$DRY_RUN" = "1" ]; then
    echo "Would create: $HOME/.pi/agent/prompts"
else
    mkdir -p "$HOME/.pi/agent/prompts"
fi
for prompt_md in "$REPO_DIR"/pi/prompts/*.md; do
    [ -e "$prompt_md" ] || continue
    link_config "$prompt_md" \
                "$HOME/.pi/agent/prompts/$(basename "$prompt_md")"
done

# User-scoped MCP servers (available in every project on this machine).
# `claude mcp add` writes into ~/.claude.json, which also holds
# per-machine OAuth tokens/project history, so it isn't symlinked here —
# each server gets its own idempotent `add` call instead.
if command -v claude >/dev/null 2>&1; then
    if command -v 1password-mcp >/dev/null 2>&1; then
        if claude mcp get 1password >/dev/null 2>&1; then
            echo "✓ 1password MCP server already registered"
        elif [ "$DRY_RUN" = "1" ]; then
            echo "Would run: claude mcp add -s user 1password -- 1password-mcp"
        else
            claude mcp add -s user 1password -- 1password-mcp
            echo "✓ 1password MCP server registered (user scope)"
        fi
    else
        echo "1password-mcp not found on PATH, skipping MCP registration"
    fi
fi


echo
echo "=== Setting up git identity + signing ==="
echo

# Per-scope git identity + SSH signing keys. Render the repo's scoped
# templates into ~/.gitconfig-{personal,work}; they're pulled in by the
# includeIf blocks set below on the top-level ~/.gitconfig. Real emails
# live in gitconfig/emails.local.env (gitignored — never committed).
EMAILS_ENV="$REPO_DIR/gitconfig/emails.local.env"
if [ -f "$EMAILS_ENV" ]; then
    # shellcheck disable=SC1090
    . "$EMAILS_ENV"
fi

# Re-running on an already-configured machine must never re-prompt for
# identity. Only when emails.local.env is absent do we fall back to the
# identity currently in effect, and only prompt if that is empty too.
# The placeholder check guards against a previously failed render leaving
# __PERSONAL_EMAIL__/__WORK_EMAIL__ literals in the scoped files.
_is_placeholder() { case "$1" in __PERSONAL_EMAIL__|__WORK_EMAIL__|"") return 0 ;; *) return 1 ;; esac; }
if [ -z "$PERSONAL_EMAIL" ] || _is_placeholder "$PERSONAL_EMAIL"; then
    PERSONAL_EMAIL=""
    if [ -f "$HOME/.gitconfig-personal" ]; then
        PERSONAL_EMAIL=$(git config --file "$HOME/.gitconfig-personal" user.email 2>/dev/null || true)
    fi
    if _is_placeholder "$PERSONAL_EMAIL"; then
        PERSONAL_EMAIL=$(git config --global user.email 2>/dev/null || true)
    fi
fi
if [ "$SETUP_MODE" = "work" ] && { [ -z "$WORK_EMAIL" ] || _is_placeholder "$WORK_EMAIL"; }; then
    WORK_EMAIL=""
    if [ -f "$HOME/.gitconfig-work" ]; then
        WORK_EMAIL=$(git config --file "$HOME/.gitconfig-work" user.email 2>/dev/null || true)
    fi
    if _is_placeholder "$WORK_EMAIL"; then
        WORK_EMAIL=""
    fi
fi

if [ -z "$PERSONAL_EMAIL" ]; then
    if [ -t 0 ]; then
        read -p "Personal email: " -r PERSONAL_EMAIL
    elif [ "$DRY_RUN" = "1" ]; then
        echo "Note: $EMAILS_ENV missing — would prompt/error here on a real run"
        PERSONAL_EMAIL="__PERSONAL_EMAIL__"
    else
        echo "ERROR: $EMAILS_ENV missing — copy gitconfig/emails.example.env and fill it in" >&2
        exit 1
    fi
fi
if [ "$SETUP_MODE" = "work" ] && [ -z "$WORK_EMAIL" ]; then
    if [ -t 0 ]; then
        read -p "Work email: " -r WORK_EMAIL
    elif [ "$DRY_RUN" = "1" ]; then
        echo "Note: WORK_EMAIL not set in $EMAILS_ENV — would prompt/error here on a real run"
        WORK_EMAIL="__WORK_EMAIL__"
    else
        echo "ERROR: WORK_EMAIL not set in $EMAILS_ENV" >&2
        exit 1
    fi
fi

render_gitconfig() {
    local src=$1 target=$2
    if [ "$DRY_RUN" = "1" ]; then
        echo "Would render: $target"
        return
    fi
    # Remove any existing target FIRST — it may be a symlink into this
    # repo (older installs), and writing through it would clobber the
    # template in the repo.
    if [ -L "$target" ]; then
        rm -f "$target"
    elif [ -e "$target" ]; then
        mv "$target" "${target}.backup.$(date +%Y%m%d%H%M%S)"
    fi
    sed -e "s/__PERSONAL_EMAIL__/$PERSONAL_EMAIL/g" \
        -e "s/__WORK_EMAIL__/$WORK_EMAIL/g" \
        "$src" > "$target"
    echo "✓ Rendered $target"
}

render_gitconfig "$REPO_DIR/gitconfig/private/.gitconfig.tmpl" "$HOME/.gitconfig-personal"
if [ "$SETUP_MODE" = "work" ]; then
    render_gitconfig "$REPO_DIR/gitconfig/work/.gitconfig.tmpl" "$HOME/.gitconfig-work"
elif [ "$DRY_RUN" = "1" ]; then
    if [ -e "$HOME/.gitconfig-work" ] || [ -L "$HOME/.gitconfig-work" ]; then
        echo "Would remove: $HOME/.gitconfig-work"
    fi
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
    if [ "$DRY_RUN" = "1" ]; then
        echo "Would run: git config --global ... (identity, SSH signing, allowed_signers, includeIf, defaults)"
        return
    fi
    # Identity: default user email based on SETUP_MODE
    git config --global user.name  "Avanindra Pandeya"
    if [ "$SETUP_MODE" = "work" ]; then
        git config --global user.email "$WORK_EMAIL"
    else
        git config --global user.email "$PERSONAL_EMAIL"
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
    git config --global user.signingkey "$HOME/.ssh/id_dipus_macbook"

    # Verification: allowed_signers maps emails to pubkeys so
    # `git log --show-signature` actually verifies locally.
    mkdir -p "$HOME/.config/git"
    local signers="$HOME/.config/git/allowed_signers"
    {
        [ -f "$HOME/.ssh/id_asus_fedora.pub" ] && \
            echo "$PERSONAL_EMAIL $(cat "$HOME/.ssh/id_asus_fedora.pub")"
        [ -f "$HOME/.ssh/id_dipus_macbook.pub" ] && \
            echo "$PERSONAL_EMAIL $(cat "$HOME/.ssh/id_dipus_macbook.pub")"
        if [ "$SETUP_MODE" = "work" ]; then
            [ -f "$HOME/.ssh/id_hf_thinkpad.pub" ] && \
                echo "$WORK_EMAIL $(cat "$HOME/.ssh/id_hf_thinkpad.pub")"
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
[ "$DRY_RUN" != "1" ] && echo "✓ ~/.gitconfig signing + includeIf set"

if ! grep -q 'starship init zsh' "$HOME/.zshrc" 2>/dev/null; then
    if [ "$DRY_RUN" = "1" ]; then
        echo "Would append: starship init to ~/.zshrc"
    else
        printf '\n# starship prompt\neval "$(starship init zsh)"\n' >> "$HOME/.zshrc"
        echo "✓ Added starship init to ~/.zshrc"
    fi
else
    echo "✓ starship init already in ~/.zshrc"
fi

ALIASES_LINE="[ -f \"$REPO_DIR/shell/aliases.sh\" ] && source \"$REPO_DIR/shell/aliases.sh\""
if ! grep -qF "$REPO_DIR/shell/aliases.sh" "$HOME/.zshrc" 2>/dev/null; then
    if [ "$DRY_RUN" = "1" ]; then
        echo "Would append: shared aliases source to ~/.zshrc"
    else
        printf '\n# shared shell aliases\n%s\n' "$ALIASES_LINE" >> "$HOME/.zshrc"
        echo "✓ Added shared aliases source to ~/.zshrc"
    fi
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
elif [ "$DRY_RUN" = "1" ]; then
    echo "Would run: uv tool install --upgrade desloppify[full]"
else
    uv tool install --upgrade "desloppify[full]"
    echo "✓ desloppify CLI installed (skill is symlinked under ~/.agents/skills/desloppify)"
    echo "  When desloppify ships a new SKILL.md (e.g. v6 → v7), refresh it with:"
    echo "    cd $REPO_DIR && desloppify update-skill claude"
    echo "    git -C $REPO_DIR add skills/desloppify/SKILL.md && git -C $REPO_DIR commit -m 'chore: bump desloppify skill'"
fi

echo
echo "=== Installing mkdocs (mdserve) ==="
echo

# Backs the `mdserve` shell function (shell/aliases.sh): serves any folder
# of markdown as a browsable site with working links + mermaid rendering.
# `uv tool install --upgrade` is a no-op when already current.
if [ "$DRY_RUN" = "1" ]; then
    echo "Would run: uv tool install --upgrade mkdocs --with mkdocs-material"
else
    uv tool install --upgrade mkdocs --with mkdocs-material
    echo "✓ mkdocs + material installed (usage: mdserve <dir>)"
fi

echo
echo "=== Merging Claude Code hooks ==="
echo

# Merge the Claude Code PostToolUse hook fragment into settings.json.
# Idempotent; preserves every other top-level key. This is a general
# mechanism (not Jarvis-specific — e.g. claude/hooks/jarvis-register.sh
# fails soft when Jarvis isn't running), so it runs regardless of
# whether Jarvis itself gets installed below.
if [ -f "$REPO_DIR/scripts/merge-claude-hooks.py" ]; then
    if [ "$DRY_RUN" = "1" ]; then
        echo "Would run: python3 $REPO_DIR/scripts/merge-claude-hooks.py"
    else
        python3 "$REPO_DIR/scripts/merge-claude-hooks.py"
    fi
fi

echo
echo "=== Installing Jarvis ==="
echo

JARVIS_DIR="$HOME/code/personal/jarvis"

# Opt-in, not opt-out: Jarvis is a personal add-on, not part of the core
# bootstrap. Set INSTALL_JARVIS=1 to clone/build/schedule it.
if [ "${INSTALL_JARVIS:-0}" != "1" ]; then
    echo "INSTALL_JARVIS not set — skipping Jarvis install (set INSTALL_JARVIS=1 to install)."
elif [ "$DRY_RUN" = "1" ]; then
    echo "Would install Jarvis: clone/build $JARVIS_DIR, jarvis init, and (unless SKIP_SCHEDULES=1) install launchd agents"
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

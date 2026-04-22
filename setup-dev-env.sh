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
echo "=== Development Environment Setup Complete! ==="
echo
echo "Next steps:"
echo "  1. Configure Jira CLI: jira init"
echo "  2. Clone your repositories"
echo "  3. Set up 1Password SSH agent if not already configured"

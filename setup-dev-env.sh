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
            brew install "$package"
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

cd git
chmod +x setup.sh
./setup.sh

echo
echo "=== Development Environment Setup Complete! ==="
echo
echo "Next steps:"
echo "  1. Configure Jira CLI: jira init"
echo "  2. Clone your repositories"
echo "  3. Set up 1Password SSH agent if not already configured"

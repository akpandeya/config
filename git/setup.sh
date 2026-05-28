#!/bin/bash

# Git configuration setup script
# This script installs git configurations from templates with user-provided values

set -e

echo "=== Git Configuration Setup ==="
echo

# Prompt for user information
read -p "Enter your full name: " FULL_NAME
if [ "${SETUP_MODE:-work}" = "personal" ]; then
    read -p "Enter your personal email: " PERSONAL_EMAIL
    WORK_EMAIL="$PERSONAL_EMAIL"
else
    read -p "Enter your work email: " WORK_EMAIL
    read -p "Enter your personal email: " PERSONAL_EMAIL
fi

echo
echo "Setting up git configuration with:"
echo "  Name: $FULL_NAME"
if [ "${SETUP_MODE:-work}" != "personal" ]; then
    echo "  Work email: $WORK_EMAIL"
fi
echo "  Personal email: $PERSONAL_EMAIL"
echo

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Function to substitute placeholders and install config
install_config() {
    local template=$1
    local target=$2

    if [ "${SETUP_MODE:-work}" = "personal" ] && [ "$template" = "gitconfig.template" ]; then
        # Exclude work includeIf block
        sed -e "s/__FULL_NAME__/$FULL_NAME/g" \
            -e "s/__WORK_EMAIL__/$WORK_EMAIL/g" \
            -e "s/__PERSONAL_EMAIL__/$PERSONAL_EMAIL/g" \
            "$SCRIPT_DIR/$template" | awk '
            /\[includeIf "gitdir:~\/code\/work\/"]/ { skip=1; next }
            { if (skip > 0) { skip--; next } print }
            ' > "$target"
    else
        sed -e "s/__FULL_NAME__/$FULL_NAME/g" \
            -e "s/__WORK_EMAIL__/$WORK_EMAIL/g" \
            -e "s/__PERSONAL_EMAIL__/$PERSONAL_EMAIL/g" \
            "$SCRIPT_DIR/$template" > "$target"
    fi

    echo "✓ Installed $target"
}

# Install configurations
install_config "gitconfig.template" "$HOME/.gitconfig"
install_config "gitconfig-personal.template" "$HOME/.gitconfig-personal"
if [ "${SETUP_MODE:-work}" != "personal" ]; then
    install_config "gitconfig-work.template" "$HOME/.gitconfig-work"
else
    # Clean up work-specific gitconfig if it exists
    rm -f "$HOME/.gitconfig-work"
fi

echo
echo "=== Git configuration installed successfully! ==="
echo
echo "Test your setup:"
if [ "${SETUP_MODE:-work}" != "personal" ]; then
    echo "  cd ~/code/work && git config user.email    # Should show: $WORK_EMAIL"
fi
echo "  cd ~/code/personal && git config user.email # Should show: $PERSONAL_EMAIL"

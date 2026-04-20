# Git Configuration

This directory contains git configuration templates for setting up dual-identity git configurations on macOS.

## Overview

The configuration uses git's conditional includes to automatically switch user identity based on directory:
- `~/code/work/` → Work email and SSH key
- `~/code/personal/` → Personal email and SSH key

## Files

- `gitconfig.template` - Main git config with conditional includes
- `gitconfig-work.template` - Work-specific identity
- `gitconfig-personal.template` - Personal identity  
- `setup.sh` - Script to install configurations

## Setup

1. Run the setup script:
   ```bash
   cd ~/code/personal/config/git
   chmod +x setup.sh
   ./setup.sh
   ```

2. Provide your information when prompted:
   - Full name (e.g., "Avanindra Pandeya")
   - Work email (e.g., "avanindra.pandeya@hellofresh.de")
   - Personal email (e.g., "akpandeya1@gmail.com")

3. Verify the setup:
   ```bash
   cd ~/code/work
   git config user.email  # Should show work email
   
   cd ~/code/personal
   git config user.email  # Should show personal email
   ```

## Requirements

- macOS with 1Password SSH agent configured
- Directory structure: `~/code/work/` and `~/code/personal/`
- SSH keys stored in 1Password with appropriate labels

## How It Works

The main `.gitconfig` file includes conditional includes that load different configurations based on the current directory:

```gitconfig
[includeIf "gitdir:~/code/work/"]
    path = ~/.gitconfig-work

[includeIf "gitdir:~/code/personal/"]
    path = ~/.gitconfig-personal
```

Each conditional config overrides the user identity for that directory tree.

## SSH Key Selection

When git operations require SSH authentication, 1Password's SSH agent will prompt you to select which key to use. Make sure to select:
- Work SSH key (e.g., "HF Thinkpad") for repositories in `~/code/work/`
- Personal SSH key (e.g., "Asus fedora") for repositories in `~/code/personal/`

## Troubleshooting

**Wrong email showing:**
- Ensure you're in the correct directory (`~/code/work/` or `~/code/personal/`)
- Check that conditional includes use the correct path format
- Run `git config --show-origin user.email` to see which config file is being used

**SSH key issues:**
- Verify 1Password SSH agent is running: `echo $SSH_AUTH_SOCK`
- Check `~/.ssh/config` contains the 1Password agent configuration
- Test SSH connection: `ssh -T git@github.com`

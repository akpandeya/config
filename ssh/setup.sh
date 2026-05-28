#!/bin/bash
# Export SSH keys from 1Password to disk, passphrase-protect them with a
# fresh random passphrase (stashed back into 1Password), and install a
# launchd agent that loads them into ssh-agent at login.
#
# After this runs once per Mac, unattended SSH (Claude Code git push,
# cron jobs, rsync, etc.) no longer blocks on a 1Password unlock prompt.
#
# Re-running is safe: existing keys + passphrases are preserved.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH_DIR="$HOME/.ssh"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_NAME="com.user.ssh_unlock"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$PLIST_NAME.plist"
UNLOCK_SCRIPT="$SSH_DIR/ssh_unlock.sh"
UNLOCK_LOG="$SSH_DIR/ssh_unlock.log"

# Detect OS
OS_TYPE="${OS_TYPE:-$(uname -s)}"

# Each entry: "key-filename | 1Password item name"
# Edit this list to match the keys you have in 1Password.
if [ "${SETUP_MODE:-work}" = "personal" ]; then
  KEYS=(
    "id_asus_fedora|Asus fedora"
  )
else
  KEYS=(
    "id_hf_thinkpad|HF Thinkpad"
    "id_asus_fedora|Asus fedora"
  )
fi
VAULT="${OP_VAULT:-Private}"

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

echo "=== SSH keys from 1Password → disk ==="
echo "OS Detected: $OS_TYPE"
echo

REQUIRED_CMDS=(op ssh-keygen ssh-add openssl)
if [ "$OS_TYPE" = "Darwin" ]; then
  REQUIRED_CMDS+=(launchctl)
fi

for cmd in "${REQUIRED_CMDS[@]}"; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required tool: $cmd"
    if [ "$OS_TYPE" = "Darwin" ]; then
      echo "Install with: brew install --cask 1password && brew install 1password-cli openssh"
    else
      echo "Install with: 1password-cli and openssh packages using your system package manager"
    fi
    exit 1
  fi
done

if ! op account list 2>/dev/null | grep -q .; then
  cat <<EOF
1Password CLI is not signed in.

Open the 1Password desktop app and:
  1. Settings → Security → enable Touch ID.
  2. Settings → Developer → "Integrate with 1Password CLI".
  3. Click "Sign in" in the desktop app (if not already unlocked).

Then rerun this script.
EOF
  exit 1
fi

mkdir -p "$SSH_DIR"
chmod 700 "$SSH_DIR"
mkdir -p "$LAUNCH_AGENTS_DIR"

# ---------------------------------------------------------------------------
# Per-key: export + passphrase + initial load
# ---------------------------------------------------------------------------

rand_pass() {
  # 32 chars of base64 without the + / = characters
  openssl rand -base64 48 | tr -d '+/=' | head -c 32
}

export_key() {
  local key_name=$1 op_item=$2
  local key_path="$SSH_DIR/$key_name"

  # Detect "is this a valid SSH key file" without running ssh-keygen,
  # which would block on a passphrase prompt if the key is already
  # passphrase-protected.
  if [ -f "$key_path" ] && head -1 "$key_path" | grep -q "BEGIN.*PRIVATE KEY"; then
    echo "✓ $key_name already on disk"
  else
    echo "Exporting $op_item from 1Password → $key_path"
    op read --force --out-file "$key_path" \
      "op://$VAULT/$op_item/private key?ssh-format=openssh"
    chmod 600 "$key_path"
  fi

  # Derive .pub file if missing. Skip silently if the key is
  # passphrase-protected (ssh-keygen -y would block).
  if [ ! -f "$key_path.pub" ]; then
    ssh-keygen -y -P "" -f "$key_path" >"$key_path.pub" 2>/dev/null || true
    [ -s "$key_path.pub" ] && chmod 644 "$key_path.pub" || rm -f "$key_path.pub"
  fi
}

passphrase_item_title() {
  # Dedicated Login item per key, e.g. "SSH Passphrase: HF Thinkpad".
  # Using a new item (not the SSH Key item) because 1Password's SSH Key
  # schema is locked — you can't just `op item edit` arbitrary fields
  # into it. Login items accept custom fields freely.
  echo "SSH Passphrase: $1"
}

key_has_passphrase() {
  # 0 = encrypted, 1 = plain. ssh-keygen -y -P "" returns nonzero on
  # encrypted keys (and prints "incorrect passphrase supplied").
  ! ssh-keygen -y -P "" -f "$1" >/dev/null 2>&1
}

get_pass_from_keychain() {
  # Apple Keychain stores SSH passphrases under service "SSH"; the
  # account name is the full path to the private key.
  if [ "$OS_TYPE" = "Darwin" ]; then
    security find-generic-password -a "$1" -s "SSH" -w 2>/dev/null || true
  else
    return 0
  fi
}

save_pass_to_1password() {
  local pass_title=$1 key_name=$2 pass=$3
  if op item get "$pass_title" --vault "$VAULT" >/dev/null 2>&1; then
    op item edit "$pass_title" --vault "$VAULT" "password=$pass" >/dev/null 2>&1
  else
    op item create --category login --vault "$VAULT" \
      --title "$pass_title" --tags "ssh-unlock" \
      "username=$key_name" "password=$pass" >/dev/null 2>&1
  fi
}

ensure_passphrase() {
  local key_name=$1 op_item=$2
  local key_path="$SSH_DIR/$key_name"
  local pass_title
  pass_title=$(passphrase_item_title "$op_item")
  local pass=""

  # 1Password first (source of truth on subsequent machines).
  pass=$(op read "op://$VAULT/$pass_title/password" 2>/dev/null || true)

  # Fall back to Apple Keychain (e.g. after a partial earlier run).
  if [ -z "$pass" ]; then
    pass=$(get_pass_from_keychain "$key_path")
    if [ -n "$pass" ]; then
      echo "Found passphrase for $key_name in Apple Keychain — syncing to 1Password"
      save_pass_to_1password "$pass_title" "$key_name" "$pass" \
        || echo "WARNING: could not save '$pass_title' to 1Password."
    fi
  fi

  # Still nothing — mint a fresh one and apply it to the key.
  if [ -z "$pass" ]; then
    if key_has_passphrase "$key_path"; then
      echo "Key $key_name is already passphrase-protected but we have no"
      echo "record of the passphrase anywhere. You need to either:"
      echo "  1. Delete ~/.ssh/$key_name and rerun (it'll re-export from 1P)"
      echo "  2. Manually add a 'SSH Passphrase: $op_item' Login item to 1P"
      return 1
    fi
    echo "Minting new passphrase for $op_item (storing as '$pass_title' in 1Password)…"
    pass=$(rand_pass)
    ssh-keygen -p -N "$pass" -P "" -f "$key_path" >/dev/null
    save_pass_to_1password "$pass_title" "$key_name" "$pass" \
      || echo "WARNING: could not save '$pass_title' to 1Password."
  else
    echo "✓ passphrase available for $key_name"
  fi

  # Prime Apple Keychain so future ssh-add calls don't need 1Password.
  local askpass
  askpass=$(mktemp)
  printf '#!/bin/bash\nprintf "%%s" "%s"\n' "$pass" >"$askpass"
  chmod 700 "$askpass"
  if [ "$OS_TYPE" = "Darwin" ]; then
    DISPLAY=:0 SSH_ASKPASS="$askpass" SSH_ASKPASS_REQUIRE=force \
      ssh-add --apple-use-keychain "$key_path" </dev/null
  else
    # Linux / other: load into running ssh-agent without Apple keychain flag
    if [ -n "$SSH_AUTH_SOCK" ]; then
      DISPLAY=:0 SSH_ASKPASS="$askpass" SSH_ASKPASS_REQUIRE=force \
        ssh-add "$key_path" </dev/null
    else
      echo "  ssh-agent is not running; key not loaded but exported to disk"
    fi
  fi
  rm -f "$askpass"
  echo "✓ $key_name loaded into ssh-agent"
}

for entry in "${KEYS[@]}"; do
  key_name="${entry%%|*}"
  op_item="${entry##*|}"
  export_key "$key_name" "$op_item"
  ensure_passphrase "$key_name" "$op_item"
done

# ---------------------------------------------------------------------------
# Rewrite ~/.ssh/config
# ---------------------------------------------------------------------------

SSH_CONFIG="$SSH_DIR/config"
if [ -f "$SSH_CONFIG" ]; then
  backup="$SSH_CONFIG.bak.$(date +%Y%m%d%H%M%S)"
  cp "$SSH_CONFIG" "$backup"
  echo "Backed up existing ~/.ssh/config → $backup"
fi

if [ "${SETUP_MODE:-work}" = "personal" ]; then
  # Exclude the work Host block using Python
  python3 -c '
import sys
content = open(sys.argv[1]).read()
blocks = content.split("\n\n")
filtered = [b for b in blocks if "github.com-work" not in b and "id_hf_thinkpad" not in b]
sys.stdout.write("\n\n".join(filtered))
' "$SCRIPT_DIR/config.template" > "$SSH_CONFIG"
else
  cp "$SCRIPT_DIR/config.template" "$SSH_CONFIG"
fi
chmod 600 "$SSH_CONFIG"
echo "✓ Wrote new ~/.ssh/config"

# ---------------------------------------------------------------------------
# Install the unlock script and launchd/systemd agent
# ---------------------------------------------------------------------------

# Build the key-addition lines inline so the script doesn't need to read
# a config file at boot.
KEY_LINES=""
for entry in "${KEYS[@]}"; do
  key_name="${entry%%|*}"
  op_item="${entry##*|}"
  pass_title=$(passphrase_item_title "$op_item")
  KEY_LINES+="add_key \"\$HOME/.ssh/$key_name\" \"op://$VAULT/$pass_title/password\""$'\n'
done

# Python does the substitution cleanly regardless of special chars or
# newlines in KEY_LINES. awk -v mangles embedded newlines.
python3 -c '
import sys
template = open(sys.argv[1]).read()
sys.stdout.write(template.replace("__KEY_LINES__", sys.argv[2]))
' "$SCRIPT_DIR/ssh_unlock.sh.template" "$KEY_LINES" >"$UNLOCK_SCRIPT"
chmod 700 "$UNLOCK_SCRIPT"
echo "✓ Installed $UNLOCK_SCRIPT"

if [ "$OS_TYPE" = "Darwin" ]; then
  sed -e "s|__SCRIPT_PATH__|$UNLOCK_SCRIPT|g" \
      -e "s|__LOG_PATH__|$UNLOCK_LOG|g" \
      "$SCRIPT_DIR/com.user.ssh_unlock.plist.template" >"$PLIST_PATH"
  echo "✓ Installed $PLIST_PATH"

  # Reload the launchd agent.
  launchctl bootout "gui/$UID/$PLIST_NAME" 2>/dev/null || true
  if launchctl bootstrap "gui/$UID" "$PLIST_PATH" 2>/dev/null; then
    launchctl kickstart "gui/$UID/$PLIST_NAME"
    echo "✓ Reloaded launchd agent"
  else
    # Older macOS fallback.
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    launchctl load "$PLIST_PATH"
    echo "✓ Loaded launchd agent (legacy path)"
  fi
elif [ "$OS_TYPE" = "Linux" ]; then
  # On Linux, standard way to unlock at login can be handled by systemd user unit
  SYSTEMD_DIR="$HOME/.config/systemd/user"
  SYSTEMD_SERVICE="$SYSTEMD_DIR/ssh-unlock.service"
  mkdir -p "$SYSTEMD_DIR"
  cat <<EOF >"$SYSTEMD_SERVICE"
[Unit]
Description=Unlock SSH keys from 1Password
After=default.target

[Service]
Type=oneshot
ExecStart=$UNLOCK_SCRIPT
StandardOutput=append:$UNLOCK_LOG
StandardError=append:$UNLOCK_LOG

[Install]
WantedBy=default.target
EOF
  echo "✓ Installed systemd service at $SYSTEMD_SERVICE"
  if command -v systemctl &>/dev/null; then
    systemctl --user daemon-reload || true
    systemctl --user enable ssh-unlock.service || true
    echo "✓ Enabled systemd service ssh-unlock.service"
  fi
fi

# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

echo
echo "=== Verifying ==="
ssh-add -l | head -10 || true
echo
echo "If the keys above match your 1Password entries, you're done."
echo
echo "Log: $UNLOCK_LOG"
if [ "$OS_TYPE" = "Darwin" ]; then
  echo "Plist: $PLIST_PATH"
  echo
  echo "To revert: edit ~/.ssh/config — comment out the IdentityFile"
  echo "lines, uncomment the IdentityAgent block at the bottom, then run"
  echo "launchctl bootout gui/\$UID/$PLIST_NAME && rm $PLIST_PATH"
else
  echo "Systemd service: $SYSTEMD_SERVICE"
  echo
  echo "To revert: edit ~/.ssh/config — comment out the IdentityFile"
  echo "lines, then run"
  echo "systemctl --user disable ssh-unlock.service && rm $SYSTEMD_SERVICE"
fi

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

# Each entry: "key-filename | 1Password item name"
# Edit this list to match the keys you have in 1Password.
KEYS=(
  "id_hf_thinkpad|HF Thinkpad"
  "id_asus_fedora|Asus fedora"
)
VAULT="${OP_VAULT:-Private}"

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

echo "=== SSH keys from 1Password → disk ==="
echo

for cmd in op ssh-keygen ssh-add launchctl openssl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required tool: $cmd"
    echo "Install with: brew install --cask 1password && brew install 1password-cli openssh"
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

  if [ -f "$key_path" ] && ssh-keygen -y -f "$key_path" >/dev/null 2>&1; then
    echo "✓ $key_name already on disk"
  else
    echo "Exporting $op_item from 1Password → $key_path"
    op read --out-file "$key_path" \
      "op://$VAULT/$op_item/private key?ssh-format=openssh"
    chmod 600 "$key_path"
  fi

  # Derive .pub file if missing.
  if [ ! -f "$key_path.pub" ]; then
    ssh-keygen -y -f "$key_path" >"$key_path.pub"
    chmod 644 "$key_path.pub"
  fi
}

ensure_passphrase() {
  local key_name=$1 op_item=$2
  local key_path="$SSH_DIR/$key_name"
  local pass

  # Does 1Password already have a passphrase stored for this item?
  pass=$(op read "op://$VAULT/$op_item/ssh-passphrase" 2>/dev/null || true)

  if [ -z "$pass" ]; then
    echo "Minting new passphrase for $op_item (storing in 1Password)…"
    pass=$(rand_pass)

    # Apply passphrase to the on-disk key. Try empty-old first, fall back
    # to prompting the user if the on-disk key is already passphrased.
    if ! ssh-keygen -p -N "$pass" -P "" -f "$key_path" >/dev/null 2>&1; then
      echo "Key $key_name is already passphrase-protected."
      echo "Enter the current passphrase to rotate it:"
      ssh-keygen -p -N "$pass" -f "$key_path"
    fi

    # Store back in 1Password. `op item edit` fails if the field exists
    # with a different type; use assignment with section/type tag.
    if ! op item edit "$op_item" --vault "$VAULT" \
         "ssh-passphrase[password]=$pass" >/dev/null 2>&1; then
      echo "WARNING: op item edit failed for $op_item. Saving to keychain"
      echo "only — you'll need to add 'ssh-passphrase' to that item manually."
    fi
  else
    echo "✓ $op_item has a stored passphrase"
  fi

  # Prime Apple Keychain so future ssh-add calls don't need 1Password.
  local askpass
  askpass=$(mktemp)
  printf '#!/bin/bash\nprintf "%%s" "%s"\n' "$pass" >"$askpass"
  chmod 700 "$askpass"
  DISPLAY=:0 SSH_ASKPASS="$askpass" SSH_ASKPASS_REQUIRE=force \
    ssh-add --apple-use-keychain "$key_path" </dev/null
  rm -f "$askpass"
  echo "✓ $key_name primed in Apple Keychain and loaded into ssh-agent"
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
cp "$SCRIPT_DIR/config.template" "$SSH_CONFIG"
chmod 600 "$SSH_CONFIG"
echo "✓ Wrote new ~/.ssh/config"

# ---------------------------------------------------------------------------
# Install the unlock script and launchd plist
# ---------------------------------------------------------------------------

# Build the key-addition lines inline so the script doesn't need to read
# a config file at boot.
KEY_LINES=""
for entry in "${KEYS[@]}"; do
  key_name="${entry%%|*}"
  op_item="${entry##*|}"
  KEY_LINES+="add_key \"\$HOME/.ssh/$key_name\" \"op://$VAULT/$op_item/ssh-passphrase\""$'\n'
done

# awk does the substitution cleanly regardless of special chars in KEY_LINES.
awk -v repl="$KEY_LINES" '
  { gsub(/__KEY_LINES__/, repl); print }
' "$SCRIPT_DIR/ssh_unlock.sh.template" >"$UNLOCK_SCRIPT"
chmod 700 "$UNLOCK_SCRIPT"
echo "✓ Installed $UNLOCK_SCRIPT"

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
echo "Plist: $PLIST_PATH"
echo
echo "To revert: edit ~/.ssh/config — comment out the IdentityFile"
echo "lines, uncomment the IdentityAgent block at the bottom, then run"
echo "launchctl bootout gui/\$UID/$PLIST_NAME && rm $PLIST_PATH"

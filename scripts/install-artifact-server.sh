#!/bin/bash
# Install (or restart) the artifact feedback server as a macOS LaunchAgent.
#
# The server (scripts/artifact-server.py) serves ~/.local/share/agent-explainers
# on 127.0.0.1:8787 with the comment overlay injected, and stores feedback as
# <artifact>.feedback.json next to each artifact. It binds 127.0.0.1 only;
# exposure to other devices goes through a tunnel (issue #19), never the LAN.
#
# Re-running restarts the agent with the current repo copy of the script.

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_NAME="com.user.artifact-server"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
PORT="${ARTIFACT_SERVER_PORT:-8787}"
PYTHON="${ARTIFACT_SERVER_PYTHON:-/usr/bin/python3}"

command -v "$PYTHON" >/dev/null || { echo "Python not found: $PYTHON"; exit 1; }
[ -f "$REPO_DIR/scripts/artifact-server.py" ] || { echo "artifact-server.py missing"; exit 1; }

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/.local/share/agent-explainers"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$PLIST_NAME</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$REPO_DIR/scripts/artifact-server.py</string>
        <string>--port</string>
        <string>$PORT</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>$HOME/.local/share/agent-explainers/server.log</string>
    <key>StandardErrorPath</key><string>$HOME/.local/share/agent-explainers/server.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$PLIST_NAME" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
sleep 1

if curl -s --max-time 3 -o /dev/null "http://127.0.0.1:$PORT/"; then
  echo "Artifact feedback server running at http://127.0.0.1:$PORT"
  echo "Serving: $HOME/.local/share/agent-explainers (log: server.log in that directory)"
  echo "Stop it with: launchctl bootout gui/\$(id -u)/$PLIST_NAME"
else
  echo "Server did not respond on port $PORT — check $HOME/.local/share/agent-explainers/server.log"
  exit 1
fi

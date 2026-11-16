#!/bin/bash
# Install the Pi CLI without upgrading an existing npm installation.
set -e

PACKAGE="@earendil-works/pi-coding-agent"

echo "=== Installing Pi ==="
if [ "${SKIP_PI:-0}" = "1" ]; then
    echo "SKIP_PI=1 — skipping Pi install."
    exit 0
fi
if [ "${DRY_RUN:-0}" = "1" ]; then
    echo "Would check: Node.js 22.19+ and npm; reject unrelated pi executables"
    echo "Would run if Pi is missing: npm install -g --ignore-scripts $PACKAGE"
    echo "Would verify: pi --version"
    exit 0
fi

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    echo "ERROR: Pi requires Node.js 22.19+ and npm. Install node with Homebrew first." >&2
    exit 1
fi
if ! node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 19) ? 0 : 1)'; then
    echo "ERROR: Pi requires Node.js 22.19+ (found $(node --version)). Upgrade node first." >&2
    exit 1
fi

# Check the executable's real path, not just its name: a different pi command
# must never be silently accepted or overwritten. Fail rather than replacing
# an installation managed by another prefix or package manager.
PI_BIN="$(command -v pi || true)"
if [ -n "$PI_BIN" ]; then
    NPM_ROOT="$(npm root -g)"
    if ! node - "$PI_BIN" "$NPM_ROOT/$PACKAGE" <<'NODE'
const fs = require("node:fs");
const path = require("node:path");
try {
    const [binary, directory] = process.argv.slice(2);
    const pkg = JSON.parse(fs.readFileSync(path.join(directory, "package.json"), "utf8"));
    const entry = typeof pkg.bin === "string" ? pkg.bin : pkg.bin.pi;
    process.exit(pkg.name === "@earendil-works/pi-coding-agent" &&
        fs.realpathSync(binary) === fs.realpathSync(path.join(directory, entry)) ? 0 : 1);
} catch {
    process.exit(1);
}
NODE
    then
        echo "ERROR: $PI_BIN is not Pi from the current global npm prefix." >&2
        echo "Keep your existing installation, or resolve the PATH conflict before retrying (SKIP_PI=1 skips this step)." >&2
        exit 1
    fi
    echo "✓ Pi already installed — leaving its version unchanged"
else
    npm install -g --ignore-scripts "$PACKAGE"
    hash -r
fi

pi --version
echo "✓ Pi CLI ready (pc launches it via the shared shell config)"
echo "  First use: run pi, then /login. Credentials stay local."

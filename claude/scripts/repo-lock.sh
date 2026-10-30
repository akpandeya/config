#!/usr/bin/env bash
# repo-lock.sh — advisory cross-driver lock for one git checkout.
#
#   repo-lock.sh acquire <repo-path> <owner-description> [--force]
#   repo-lock.sh release <repo-path> <token>
#   repo-lock.sh check   <repo-path>
#
# One lock per real checkout path, at $AGENT_LOCK_ROOT/<sha1-of-path>/
# (default ~/.local/share/agent-locks). mkdir is the atomic test-and-set.
# owner.json records pid, host, startedAt, repo, command and a random token.
#
# acquire prints TOKEN=<t>; the holder must pass <t> to release, so one
# driver can never release another's lock by accident. A held lock makes
# acquire and check exit 9 and print the owner — refuse by default. Steal
# only with --force, which prints exactly what it takes from. Stale-lock
# judgement (is that pid/host/session actually dead?) belongs to a human
# or the calling orchestrator, never to this script.
#
# Exit codes: 0 ok, 2 usage error, 9 lock held / token mismatch.

set -euo pipefail

LOCK_ROOT="${AGENT_LOCK_ROOT:-$HOME/.local/share/agent-locks}"

die() { echo "repo-lock: $*" >&2; exit 2; }

[ $# -ge 2 ] || die "usage: repo-lock.sh acquire|release|check <repo-path> [owner|--force|token]"
cmd=$1
repo=$2
shift 2

real=$(cd "$repo" 2>/dev/null && pwd -P) || die "no such directory: $repo"
hash=$(printf %s "$real" | shasum -a 1 | awk '{print $1}')
dir="$LOCK_ROOT/$hash"
owner_file="$dir/owner.json"

show_owner() { [ -f "$owner_file" ] && cat "$owner_file" >&2 || echo "repo-lock: (lock dir exists but no owner.json)" >&2; }

case "$cmd" in
  acquire)
    force=0
    desc="unknown session"
    for arg in "$@"; do
      case "$arg" in
        --force) force=1 ;;
        *) desc=$arg ;;
      esac
    done
    if ! mkdir -p "$LOCK_ROOT"; then die "cannot create $LOCK_ROOT"; fi
    if ! mkdir "$dir" 2>/dev/null; then
      if [ "$force" -eq 1 ]; then
        echo "repo-lock: stealing lock from:" >&2
        show_owner
        rm -rf "$dir"
        mkdir "$dir"
      else
        echo "repo-lock: LOCKED — $real is held by:" >&2
        show_owner
        echo "repo-lock: refusing. Inspect the owner; steal only with --force." >&2
        exit 9
      fi
    fi
    token=$(openssl rand -hex 8 2>/dev/null || printf '%s%s' "$$" "$(date +%s)")
    tmp="$dir/.owner.json.tmp"
    printf '{"pid":%s,"host":"%s","startedAt":"%s","repo":"%s","command":"%s","token":"%s"}\n' \
      "$$" "$(hostname -s 2>/dev/null || hostname)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      "$real" "${desc//\"/\'}" "$token" > "$tmp"
    mv "$tmp" "$owner_file"
    echo "repo-lock: acquired $real"
    echo "TOKEN=$token"
    ;;
  release)
    token=${1:-}
    if [ ! -d "$dir" ]; then
      echo "repo-lock: no lock held for $real"
      exit 0
    fi
    held=$(sed -n 's/.*"token":"\([^"]*\)".*/\1/p' "$owner_file" 2>/dev/null || true)
    if [ -n "$held" ] && [ "$held" != "$token" ]; then
      echo "repo-lock: token mismatch — not your lock. Owner:" >&2
      show_owner
      exit 9
    fi
    rm -rf "$dir"
    echo "repo-lock: released $real"
    ;;
  check)
    if [ -d "$dir" ]; then
      show_owner
      exit 9
    fi
    echo "repo-lock: free ($real)"
    ;;
  *)
    die "unknown command: $cmd"
    ;;
esac

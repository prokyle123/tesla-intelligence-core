#!/usr/bin/env bash
# GENESIS preview: stage/rollback separately from Classic GHOST.
# No sudo, apt, systemd, production-file edits or network activity.
set -Eeuo pipefail

if [[ "$EUID" -eq 0 ]]; then echo "Do not stage as root." >&2; exit 2; fi
MODE="${1:-stage}"
SOURCE="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX="$HOME/genesis-product"
if [[ -n "${GHOST_GENESIS_PREFIX:-}" ]]; then PREFIX="$GHOST_GENESIS_PREFIX"; fi
[[ -d "$SOURCE/.git" ]] || { echo "Run from a versioned GENESIS checkout." >&2; exit 2; }
case "$MODE" in stage|rollback|status) ;; *) echo "Usage: $0 [stage|rollback|status]" >&2; exit 2 ;; esac
mkdir -p "$PREFIX"
chmod 700 "$PREFIX"
PREFIX="$(cd "$PREFIX" && pwd -P)"
CURRENT="$PREFIX/current"
PREVIOUS="$PREFIX/previous-release.txt"

if [[ -e "$CURRENT" && ! -L "$CURRENT" ]]; then
    echo "Refusing to replace a real directory at $CURRENT" >&2
    exit 2
fi
case "$MODE" in
 status)
    if [[ -L "$CURRENT" ]]; then
        echo "GENESIS STAGED VERSION: $(readlink "$CURRENT")"
    else
        echo "GENESIS NOT STAGED"
    fi
    echo "PRIVATE PRODUCT DATA: $PREFIX/state"
    exit 0
    ;;
 rollback)
    [[ -f "$PREVIOUS" ]] || { echo "No previous release recorded." >&2; exit 2; }
    target="$(cat "$PREVIOUS")"
    case "$target" in "$PREFIX"/releases/*) ;; *) echo "Unsafe rollback path." >&2; exit 2 ;; esac
    [[ -d "$target/genesis" ]] || { echo "Rollback stage missing." >&2; exit 2; }
    old=""
    [[ -L "$CURRENT" ]] && old="$(readlink "$CURRENT")"
    ln -sfnT "$target" "$CURRENT"
    if [[ -n "$old" ]]; then printf '%s\n' "$old" > "$PREVIOUS"; else rm -f "$PREVIOUS"; fi
    echo "ROLLED BACK TO: $target"
    echo "No service processes have been started or stopped."
    exit 0
    ;;
esac

git -C "$SOURCE" diff --quiet
git -C "$SOURCE" diff --cached --quiet
SHA="$(git -C "$SOURCE" rev-parse --verify HEAD)"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "No verified code revision." >&2; exit 2; }
mkdir -p "$PREFIX/releases" "$PREFIX/state"
chmod 700 "$PREFIX/releases" "$PREFIX/state"
RELEASE="$PREFIX/releases/$SHA"
if [[ ! -d "$RELEASE" ]]; then
    mkdir -m 700 "$RELEASE"
    git -C "$SOURCE" archive "$SHA" genesis | tar -xf - -C "$RELEASE"
    printf '%s\n' "$SHA" > "$RELEASE/COMMIT"
    chmod -R go-rwx "$RELEASE"
fi
[[ -f "$RELEASE/genesis/cli.py" && -f "$RELEASE/genesis/workspace.py" ]] || {
    echo "Incomplete GENESIS stage." >&2; exit 2;
}
old=""
[[ -L "$CURRENT" ]] && old="$(readlink "$CURRENT")"
if [[ -n "$old" && "$old" != "$RELEASE" ]]; then
    printf '%s\n' "$old" > "$PREVIOUS"
    chmod 600 "$PREVIOUS"
fi
ln -sfnT "$RELEASE" "$CURRENT"
echo "GENESIS STAGED: $SHA"
echo "CODE: $CURRENT"
echo "PRIVATE DATA: $PREFIX/state"
echo "Classic GHOST unchanged; nothing started, no timers installed."
echo
echo "Next (operator invoked):"
echo "  cd \"$CURRENT\""
echo "  python3 -m genesis.cli --source-db /var/lib/ghost-tesla-ai/ghost_ai.sqlite3 --product-db \"$PREFIX/state/product.sqlite3\" product-cycle --save"
echo "Preview (localhost/SSH forwarding only):"
echo "  python3 -m genesis.workspace --data-dir \"$PREFIX/state\" --port 8767"

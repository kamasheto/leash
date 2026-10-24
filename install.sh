#!/usr/bin/env bash
# Installs leash: clones it to ~/.local/share/leash (or updates an existing
# clone), then runs `leash install`, which sets up nono, symlinks
# ~/.local/bin/leash and puts ~/.local/bin on PATH. Every step that changes
# anything asks first.
#
#   bash -c "$(curl -fsSL https://sakr.me/leash-install)"
#
# Everything runs from main, called on the last line, so a truncated download
# runs nothing.

set -euo pipefail

REPO_URL="https://github.com/kamasheto/leash.git"
LEASH_DIR="$HOME/.local/share/leash"

die() {
    echo "leash: $*" >&2
    exit 1
}

# Asks a y/n question on the terminal; anything but y/yes (or no terminal) is no.
confirm() {
    local answer
    { printf 'leash: %s (y/n) ' "$1" >/dev/tty; } 2>/dev/null || return 1
    read -r answer </dev/tty || return 1
    case "$answer" in
        [yY] | [yY][eE][sS]) return 0 ;;
        *) return 1 ;;
    esac
}

main() {
    command -v git >/dev/null || die "git is required but not found in PATH."
    command -v python3 >/dev/null || die "python3 (3.11+) is required but not found in PATH."

    if [ -d "$LEASH_DIR/.git" ]; then
        confirm "Update the leash checkout in $LEASH_DIR (git pull)?" ||
            die "installation stopped."
        git -C "$LEASH_DIR" pull --ff-only --quiet
    elif [ -e "$LEASH_DIR" ]; then
        die "$LEASH_DIR exists but isn't a git checkout; move it aside and rerun."
    else
        confirm "Clone leash into $LEASH_DIR?" || die "installation stopped."
        mkdir -p "$(dirname "$LEASH_DIR")"
        git clone --quiet "$REPO_URL" "$LEASH_DIR"
    fi

    # `leash install` asks before each remaining change (nono, the
    # ~/.local/bin/leash symlink, your shell's PATH). Its answers come from the
    # terminal too, so they still work when this script arrives on stdin.
    if (exec </dev/tty) 2>/dev/null; then
        "$LEASH_DIR/cli" install </dev/tty
    else
        "$LEASH_DIR/cli" install
    fi
}

main "$@"

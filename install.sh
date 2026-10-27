#!/usr/bin/env bash
# Installs leash: clones it to ~/.local/share/leash (or updates an existing
# clone), then runs `leash install`, which sets up nono, symlinks
# ~/.local/bin/leash and puts ~/.local/bin on PATH. Every step that changes
# anything asks first.
#
#   curl -fsSL https://kamasheto.dev/install-leash | bash
#   curl -fsSL https://kamasheto.dev/install-leash | bash -s -- --verbose
#
# The script arrives on stdin, so prompts read from /dev/tty instead. Piping
# (rather than `bash -c "$(curl ...)"`) keeps the script out of bash's
# arguments, where terminals that show the running command would display it.
# Everything runs from main, called on the last line, so a truncated download
# runs nothing.

set -euo pipefail

REPO_URL="https://github.com/kamasheto/leash.git"
LEASH_DIR="$HOME/.local/share/leash"
LEASH_DIR_SHOWN="~${LEASH_DIR#"$HOME"}"

if [ -t 1 ]; then
    BOLD=$'\033[1m' GREEN=$'\033[32m' RED=$'\033[31m' RESET=$'\033[0m'
else
    BOLD="" GREEN="" RED="" RESET=""
fi

ok() {
    printf '  %s✓%s %s\n' "$GREEN" "$RESET" "$*"
}

die() {
    printf '  %s✗%s %s\n' "$RED" "$RESET" "$*" >&2
    exit 1
}

# Asks a y/n question on the terminal, like leash's own confirm(): Enter or
# y/yes is yes; anything else (or no terminal) is no.
confirm() {
    local answer
    { printf '🦮 %s (Y/n) ' "$1" >/dev/tty; } 2>/dev/null || return 1
    read -r answer </dev/tty || return 1
    case "$answer" in
        "" | [yY] | [yY][eE][sS]) return 0 ;;
        *) return 1 ;;
    esac
}

main() {
    # Without --verbose, git runs quietly and `leash install` hides the output
    # of the commands it runs.
    local verbose="" quiet="-q"
    case "${1:-}" in
        --verbose) verbose="--verbose" quiet="" ;;
        "") ;;
        *) die "unknown option '$1' (only --verbose is supported)." ;;
    esac

    printf '%sInstalling leash%s\n' "$BOLD" "$RESET"

    command -v git >/dev/null || die "git is required but not found in PATH."
    ok "git $(git --version | awk '{print $3}')"
    command -v python3 >/dev/null || die "python3 (3.11+) is required but not found in PATH."
    python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' ||
        die "leash needs Python 3.11+, but python3 is $(python3 -V 2>&1 | awk '{print $2}')."
    ok "python $(python3 -V 2>&1 | awk '{print $2}')"
    echo
    if [ -z "$verbose" ]; then
        printf '%s\n\n' "⚠️  Running in silent mode. To see progress details, re-run this command in verbose mode: \`curl -fsSL https://kamasheto.dev/install-leash | bash -s -- --verbose\`"
    fi

    if [ -d "$LEASH_DIR/.git" ]; then
        confirm "Update the leash checkout in $LEASH_DIR_SHOWN (git pull)?" ||
            die "installation stopped."
        git -C "$LEASH_DIR" pull $quiet --ff-only ||
            die "couldn't update $LEASH_DIR_SHOWN."
        ok "Updated leash in $LEASH_DIR_SHOWN"
    elif [ -e "$LEASH_DIR" ]; then
        die "$LEASH_DIR_SHOWN exists but isn't a git checkout; move it aside and rerun."
    else
        confirm "Clone leash into $LEASH_DIR_SHOWN?" || die "installation stopped."
        mkdir -p "$(dirname "$LEASH_DIR")"
        git clone $quiet "$REPO_URL" "$LEASH_DIR" ||
            die "couldn't clone $REPO_URL."
        ok "Cloned leash into $LEASH_DIR_SHOWN"
    fi

    # `leash install` asks before each remaining change (nono, the
    # ~/.local/bin/leash symlink, your shell's PATH). Its answers come from the
    # terminal too, since stdin is this script. LEASH_NOTICE_SHOWN stops it
    # repeating the silent-mode notice above.
    if (exec </dev/tty) 2>/dev/null; then
        LEASH_NOTICE_SHOWN=1 "$LEASH_DIR/cli" $verbose install </dev/tty
    else
        LEASH_NOTICE_SHOWN=1 "$LEASH_DIR/cli" $verbose install
    fi
}

main "$@"

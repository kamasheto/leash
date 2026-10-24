#!/usr/bin/env bash
# Installs leash: clones it to ~/.local/share/leash (or updates an existing
# clone), then runs `leash install`, which sets up nono, symlinks
# ~/.local/bin/leash and puts ~/.local/bin on PATH. Every step that changes
# anything asks first.
#
#   curl -fsSL https://sakr.me/install-leash | bash
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

# Draws "  <label> [██████░░░░] 60%" over the current line.
bar() {
    local label=$1 pct=$2 width=30 filled i done_part="" todo_part=""
    filled=$((pct * width / 100))
    for ((i = 0; i < filled; i++)); do done_part+="█"; done
    for ((i = filled; i < width; i++)); do todo_part+="░"; done
    printf '\r  %s [%s%s] %3d%%' "$label" "$done_part" "$todo_part" "$pct"
}

# Turns git's --progress output on stdin into a bar: receiving objects fills
# the first 90%, resolving deltas the rest. git redraws each line with \r, so
# chunks are split on \r and only the last line of each is looked at.
show_git_progress() {
    local label=$1 chunk line pct
    while IFS= read -r -d $'\r' chunk || [ -n "$chunk" ]; do
        line=${chunk##*$'\n'}
        case "$line" in
            "Receiving objects:"* | "Unpacking objects:"*) pct=$((9 * $(percent "$line") / 10)) ;;
            "Resolving deltas:"*) pct=$((90 + $(percent "$line") / 10)) ;;
            *) continue ;;
        esac
        bar "$label" "$pct"
    done
}

# "Receiving objects:  45% (9/20)" -> 45
percent() {
    local p=${1#*:}
    p=${p%%%*}
    echo $((10#${p// /}))
}

# Runs git with a progress bar labeled $1 (when on a terminal), keeping its
# output out of sight unless it fails.
run_git() {
    local label=$1 log status=0
    shift
    log=$(mktemp)
    if [ -t 1 ]; then
        bar "$label" 0
        git "$@" 2>&1 | tee "$log" | show_git_progress "$label" || status=$?
        printf '\r\033[K'
    else
        git "$@" >"$log" 2>&1 || status=$?
    fi
    [ "$status" -eq 0 ] || cat "$log" >&2
    rm -f "$log"
    return "$status"
}

main() {
    printf '%sInstalling leash%s\n' "$BOLD" "$RESET"

    command -v git >/dev/null || die "git is required but not found in PATH."
    ok "git $(git --version | awk '{print $3}')"
    command -v python3 >/dev/null || die "python3 (3.11+) is required but not found in PATH."
    python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' ||
        die "leash needs Python 3.11+, but python3 is $(python3 -V 2>&1 | awk '{print $2}')."
    ok "python $(python3 -V 2>&1 | awk '{print $2}')"
    echo

    if [ -d "$LEASH_DIR/.git" ]; then
        confirm "Update the leash checkout in $LEASH_DIR_SHOWN (git pull)?" ||
            die "installation stopped."
        run_git "Updating" -C "$LEASH_DIR" pull --ff-only --progress ||
            die "couldn't update $LEASH_DIR_SHOWN."
        ok "Updated leash in $LEASH_DIR_SHOWN"
    elif [ -e "$LEASH_DIR" ]; then
        die "$LEASH_DIR_SHOWN exists but isn't a git checkout; move it aside and rerun."
    else
        confirm "Clone leash into $LEASH_DIR_SHOWN?" || die "installation stopped."
        mkdir -p "$(dirname "$LEASH_DIR")"
        run_git "Cloning " clone --progress "$REPO_URL" "$LEASH_DIR" ||
            die "couldn't clone $REPO_URL."
        ok "Cloned leash into $LEASH_DIR_SHOWN"
    fi

    # `leash install` asks before each remaining change (nono, the
    # ~/.local/bin/leash symlink, your shell's PATH). Its answers come from the
    # terminal too, since stdin is this script.
    if (exec </dev/tty) 2>/dev/null; then
        "$LEASH_DIR/cli" install </dev/tty
    else
        "$LEASH_DIR/cli" install
    fi
}

main "$@"

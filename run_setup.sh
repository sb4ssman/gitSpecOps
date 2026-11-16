#!/usr/bin/env sh
# Run the optional bootstrap. It needs some Python to start: prefer `uv run`
# (using an available Python without project sync/downloads), else python3, else python.
set -eu
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

# Double-clicked in a file manager ("Execute"): there is no terminal, so setup's questions would
# go nowhere and nothing would appear. Open a terminal and run this script in it (2026-11-15).
if [ ! -t 0 ] && [ -z "${GITSO_SETUP_WINDOW:-}" ] && [ "$#" -eq 0 ]; then
    export GITSO_SETUP_WINDOW=1
    for terminal in x-terminal-emulator konsole gnome-terminal xfce4-terminal mate-terminal xterm; do
        if command -v "$terminal" >/dev/null 2>&1; then
            case "$terminal" in
                gnome-terminal|mate-terminal) exec "$terminal" -- "$0" ;;
                *) exec "$terminal" -e "$0" ;;
            esac
        fi
    done
fi

# Keep caller-relative settings/root paths; bootstrap itself uses the explicit checkout root.
status=0
if command -v uv >/dev/null 2>&1; then
    uv run --no-project --no-python-downloads python "$SCRIPT_DIR/_build/setup_gitspecops.py" "$@" || status=$?
elif command -v python3 >/dev/null 2>&1; then
    python3 "$SCRIPT_DIR/_build/setup_gitspecops.py" "$@" || status=$?
elif command -v python >/dev/null 2>&1; then
    python "$SCRIPT_DIR/_build/setup_gitspecops.py" "$@" || status=$?
else
    echo "No Python found. Install uv (https://docs.astral.sh/uv/) or Python (https://python.org)." >&2
    status=1
fi
# A window this script opened closes with it: keep it until the person has read the last screen.
if [ -n "${GITSO_SETUP_WINDOW:-}" ]; then
    printf '\n  Press Enter to close this window. '
    read -r _ || true
fi
exit "$status"

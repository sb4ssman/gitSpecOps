#!/usr/bin/env sh
# Run the optional bootstrap. It needs some Python to start: prefer `uv run`
# (uv provides its own Python), else python3, else python.
set -eu
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR"
if command -v uv >/dev/null 2>&1; then
    exec uv run python setup_gitspecops.py "$@"
elif command -v python3 >/dev/null 2>&1; then
    exec python3 setup_gitspecops.py "$@"
elif command -v python >/dev/null 2>&1; then
    exec python setup_gitspecops.py "$@"
else
    echo "No Python found. Install uv (https://docs.astral.sh/uv/) or Python (https://python.org)." >&2
    exit 1
fi

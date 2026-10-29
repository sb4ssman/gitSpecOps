#!/usr/bin/env sh
# Run the optional bootstrap. It needs some Python to start: prefer `uv run`
# (using an available Python without project sync/downloads), else python3, else python.
set -eu
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# Keep caller-relative settings/root paths; bootstrap itself uses the explicit checkout root.
if command -v uv >/dev/null 2>&1; then
    exec uv run --no-project --no-python-downloads python "$SCRIPT_DIR/setup_gitspecops.py" "$@"
elif command -v python3 >/dev/null 2>&1; then
    exec python3 "$SCRIPT_DIR/setup_gitspecops.py" "$@"
elif command -v python >/dev/null 2>&1; then
    exec python "$SCRIPT_DIR/setup_gitspecops.py" "$@"
else
    echo "No Python found. Install uv (https://docs.astral.sh/uv/) or Python (https://python.org)." >&2
    exit 1
fi

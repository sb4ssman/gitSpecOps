#!/bin/sh
set -eu
root=$(git rev-parse --show-toplevel)
gate="$root/_build/repo_commit_gate.py"
cd "$root"
if [ -x "$root/.venv/Scripts/python.exe" ]; then
    exec "$root/.venv/Scripts/python.exe" -B "$gate" "$@"
elif [ -x "$root/.venv/bin/python" ]; then
    exec "$root/.venv/bin/python" -B "$gate" "$@"
elif command -v python3 >/dev/null 2>&1; then
    exec python3 -B "$gate" "$@"
else
    exec python -B "$gate" "$@"
fi

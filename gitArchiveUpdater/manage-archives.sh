#!/usr/bin/env sh
# Launch the archive manager. Prefer the repo's .venv (built by run_setup);
# fall back to `uv run` when .venv is absent. Run from anywhere.
set -eu
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"
if [ -x ".venv/bin/python" ]; then
    exec .venv/bin/python gitArchiveUpdater/archive_manager.py "$@"
else
    exec uv run python gitArchiveUpdater/archive_manager.py "$@"
fi

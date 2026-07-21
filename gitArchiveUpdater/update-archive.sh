#!/usr/bin/env sh
# Launch the standalone archive updater. Prefer the repo's .venv (built by
# run_setup); fall back to `uv run` when .venv is absent. With no arguments,
# show --help so a bare launch explains the tool instead of acting.
set -eu
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"
if [ "$#" -eq 0 ]; then
    set -- --help
fi
if [ -x ".venv/bin/python" ]; then
    exec .venv/bin/python gitArchiveUpdater/archive_updater.py "$@"
else
    exec uv run python gitArchiveUpdater/archive_updater.py "$@"
fi

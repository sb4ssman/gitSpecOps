#!/usr/bin/env sh
# Launch the GitHub org duplicator. Prefer the repo's .venv (built by
# run_setup); fall back to `uv run` when .venv is absent. Run from anywhere.
set -eu
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"
if [ -x ".venv/bin/python" ]; then
    exec .venv/bin/python github-org-duplicator/github_org_duplicator.py "$@"
else
    exec uv run python github-org-duplicator/github_org_duplicator.py "$@"
fi

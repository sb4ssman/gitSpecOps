# Work log

Append-only record of **completed** work. Newest first. Items that graduate from
[`working-notes.md`](working-notes.md) land here with an absolute date.

## 2026-07-21

- **Stood up the `.agents/` workspace.** Migrated the full project brief out of the fat root
  `AGENTS.md` into [`README.md`](README.md) (primary project document + Directives), and slimmed
  root `AGENTS.md` / added an identical `CLAUDE.md` as lean pointers. Created `knowledge/`,
  `tools/`, `output/`, and the living `working-notes.md` / `work-log.md`.

- **Setup / venv architecture shipped** (commits `5165d17` + `cd5a608`). Settled model:
  UV-preferred, stdlib fallback, a permanent `.venv` instead of per-launch `uv run`.
  - `setup_gitspecops.py` rewritten as an optional bootstrap: `uv sync` first (honors `uv.lock`),
    falling back to stdlib `venv` + `pip install -e .`; reports git/gh/uv. No longer writes
    launchers.
  - Committed static launcher trios (`.bat` shim → real `.ps1` → `.sh`) for the org duplicator and
    the two archive-updater entry points; each prefers the repo's `.venv` Python and falls back to
    `uv run` when `.venv` is absent. `run_setup.{bat,ps1,sh}` added.
  - `archive_manager.py`'s runtime-generated per-archive launchers and `refresh-managed-archives`
    now emit the same trio + prefer-`.venv` scheme.
  - Duplicator folder safety: `prompt_for_directory()` re-prompts instead of `sys.exit`; the
    non-empty download destination warning now lists the colliding repo names and requires `[y/N]`.

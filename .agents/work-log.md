# Work log

Append-only record of **completed** work. Newest first. Items that graduate from
[`working-notes.md`](working-notes.md) land here with an absolute date.

## 2026-08-06

- **Consolidated Sync Suggester research and family design.** Added
  [`new-tool-sync-suggester.md`](new-tool-sync-suggester.md) covering the cross-machine problem,
  public-fork/private-branch constraint, privacy-minimized manifests, transport alternatives, watcher
  and UI concepts, safety classifications, how Archive Updater/Sync Suggester/Org Duplicator can
  share capabilities, and a no-mutation vertical slice. Identified a user-selected cloud-synced
  folder as the simplest experiment; private Git, provider app folders, object storage, and P2P remain
  optional transports.

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

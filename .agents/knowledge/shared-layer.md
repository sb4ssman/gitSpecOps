# shared/ — the cross-operation primitive layer

> **Superseded 2026-09-21 by the layer stack** ([architecture-layers.md](architecture-layers.md)).
> Migration phase 1 moved `console`, `git_facts`, `remote_identity` and `repo_discovery` into
> `Basic/` (`_console`, `_facts`, `_identity`, `_discovery`), merged `run_git` and the duplicator's
> `run_command` into `Basic/_run.py` (which `run_gh` now also uses), and dropped the standalone
> CLIs of plumbing modules — `Basic/status.py` and `Basic/discover.py` replace the two that were
> useful; the identity self-test became `tests/basic/test_identity.py`. What remains in `shared/`
> leaves in phases 2 and 4. The record below is kept for its reasoning and history.

_Decision recorded 2026-08-31._

## Decision

`shared/` (repo root, flat, no `__init__.py`) holds primitives shared by the special operations:
archive updater (`git-archive-updater/`), org duplicator (`github-org-duplicator/`), and sync
suggester (future). **Admission rule (set by the user): a method moves into `shared/` once two of
the three operations need it.** This supersedes the "wait for two real consumers" guidance in the
sync-suggester design doc for discovery/git-facts, because the duplicator, archive updater, and
the planned sync suggester all need the same repo discovery and git facts.

## Properties of everything in shared/

- Standalone interfaces and fact functions are read-only information operations. Low-level process
  wrappers (`run_git`, `run_gh`) are policy-neutral mechanics also reused by tool-owned apply code;
  mutation commands and their preview/confirmation policy never live in `shared/`.
- Stdlib only; no imports from tool folders (one-way dependency: tools → shared).
- No policy: approved-remote lists, confirmation flows, apply classes stay per-tool.
- Each module runs standalone (`python shared/<mod>.py`) as its own small tool.

## Current residents

- `remote_identity.py` — parse any git remote URL → (host, owner, name); `normalize_owner_name`.
  Extracted verbatim from `git_inspect.py` + `archive_diff.py` (both now re-export it).
- `git_facts.py` — `run_git` with timeout handling, `git_stdout`/`git_top_level`, `is_repo_root`,
  ahead/behind vs upstream, `repo_facts()` JSON. Extracted from `git_inspect.py`.
- `repo_discovery.py` — pruned recursive repo finder (worktrees, `.git`-file links, bare repos),
  `DEFAULT_SKIP_NAMES`, `find_repos()` + CLI scanner. New; shared by duplicator/sync suggester.
- `gh_cli.py` — `run_gh()` subprocess wrapper + `GhError` + auth checks. Consolidates the direct
  `gh` shells that were in `provider_github.py` and the duplicator's `gh_remote.py`.

## Mechanics

- Scripts that import `shared/` insert the repo root into `sys.path` (3-line bootstrap; see
  `git_inspect.py`, `archive_diff.py`, `provider_github.py`, `gh_remote.py`).
- No `__init__.py`: PEP 420 namespace package once the repo root is on `sys.path`.
- `pyproject.toml`'s `py-modules = ["setup_gitspecops"]` means `shared/` is not pip-installed;
  everything runs from the checkout, which is the intended model.

## Linux notes (first non-Windows checkout, 2026-08-31)

- `.sh` launchers must keep the executable bit (git mode 100755); they were committed as 644.
- `run_setup.sh` works: `uv sync` → `.venv` (CPython 3.13) → launchers prefer `.venv/bin/python`.
- Stdlib-venv fallback caveat: Debian/Ubuntu needs the `python3-venv` package for the no-uv path.

## Deferred extractions

- `gh_common.run_command` (generic subprocess) stays in the duplicator — not shared by two ops.
- Sync-suggester-specific facts beyond `repo_facts` (stashes, in-progress operations) when it lands.
- Publish direction: ahead/behind already lives in `git_facts`; a push classifier is policy and
  belongs in the archive layer, not `shared/`.

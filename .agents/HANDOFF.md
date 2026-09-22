# Handoff — 2026-09-21

For the next session, human or LLM. Read [`README.md`](README.md) (the project brief) first. It
opens with **What this is for**, and that section outranks every rule below it. Then this, then
[`working-notes.md`](working-notes.md).

## Your job: reorganize the guts into the agreed architecture

The product direction, the layering and the diagram are **settled**. **Phases 1, 2 and 3a–3b are committed
(2026-09-21/22). Phase 3c (Sync Suggester into `Elaborate/`) is next.** The user still has to
replace the scheduled task and reinstall three archive launchers (see "Things that will bite you"). The work is the migration, and nothing else. The target was
revised on 2026-09-21 (root `_os/`, flat `Basic/`, flat `App/tray.py`, `_providers/`, merges and
splits): read "Revisions" at the end of the architecture document before phase 2.

Read these two before touching a file:

1. [`knowledge/architecture-layers.md`](knowledge/architecture-layers.md): the specification,
   including the full target tree with every file's destination.
2. [`knowledge/architecture-diagram.md`](knowledge/architecture-diagram.md): the same thing as a
   picture, and what the picture asserts.

### The shape, in one paragraph

`git` is the raw material; authentication is assumed and never stored. **Basic** wraps one git or
host operation with care, including the host seam (`Basic/providers/`). **Special** repeats a
Basic operation with the logic of the repetition. **Elaborate** widens that across machines and
across time. **App** assembles it for a human, is optional, and is mostly the tray. A layer builds
only on the layers above it in the diagram. A file without an underscore is a command; a file or
folder with one is plumbing. `_build/`, `_docs/` and `_tests/` sit at the root beside the four
layers.

### Decisions taken 2026-09-20: do not reopen these

- **Work directly on `main`.** The user is the only user and wants things fixed cleanly rather
  than carried on a long-lived branch. Keep each phase committed and green.
- **Direct script paths are the command surface. There is no dispatcher.**
  ```
  python Basic/git/pull.py <repo>
  python Special/archive_update.py --root <archive>
  python Elaborate/catchup.py --apply --yes
  python App/tray/tray.py
  ```
  Every command is also an importable module, and higher layers call lower ones with a normal
  `import`. Every runnable file must work when run by its path from any directory, using a small
  inline repository-root bootstrap as the code does today. The monolithic entry points
  (`sync_suggester.py`, `fleet_app.py`, `archive_manager.py` as a front door,
  `github_org_duplicator.py`'s menu) dissolve into their operations.
- **Hard break.** No forwarding shims and no compatibility code for earlier formats. Nothing is
  enrolled, so old config versions and the host/client migration path are deleted rather than
  carried. If any old local config exists, `setup_fleet` writes a fresh one.
- **Plain names.** Lowercase words joined by underscores. No hyphens anywhere.
- **Skins: lcars, modern, retro all ship.** `modern` is today's dashboard. `retro` and `lcars`
  are placeholders: selectable, consuming the display contract, visibly marked unfinished.

### Migration phases: each ends green

Phase 1 is where to start. Do not begin a phase until the one before it is committed green.

1. **`Basic/` — DONE 2026-09-21.** One `_run.py` (git and `gh`), `_facts`, `_identity`,
   `_discovery`, `_console`, `_confirm`, `_files`, `_paths`; commands `status.py`, `discover.py`;
   root `_os/` with `current.py` and `paths`/`process` for all three OSes plus a parity test. Tool
   folders import downward; none moved. `git_inspect` stayed put on purpose: `inspect_candidate`
   is archive policy and goes to `Special/_archive_plan.py` in phase 3. See the work log.
2. **`Basic/_providers/` — DONE 2026-09-21.** `_registry.py` (was `shared/providers.py`) loads
   its built-in providers itself; `github.py` holds every `gh` invocation (was `provider_github`,
   `shared/gh_cli`, the duplicator's `gh_remote` calls, the version check's release query) and
   registers itself. `remote_provider.py` and `_register_providers()` are deleted.
   `tests/repo/test_import_direction.py` enforces `_os → Basic → Special → Elaborate → App`, no
   sideways command imports, nothing outside the stack. See the work log.
3. **`Special/` and `Elaborate/`.** Move the operations to their names in the target tree. Split
   `archive_diff` (generic classification to `Basic/_facts`, archive decisions to
   `Special/_archive_plan.py`). **`archive_manage` goes to Elaborate**: it schedules. Consolidate
   Sync Suggester into **one configuration and one observation code path**: `check` runs it once
   and `peer` runs it continuously; delete `watch` (the peer's file events replace its polling);
   fold `init` into `setup_fleet`; the terminal `dashboard` becomes `check` without observing;
   delete the reserved `handoff` stub. Update `LAUNCHER_SPECS` and every path in the docs.
   Also: the archive registry moves to `Basic/_paths.config_home()` as
   `gitspecops_managed_archives.json`; launcher writing moves to `_os/*/launcher.py` and
   scheduling to `_os/*/schedule.py`; terminal renderers move out of `advice`/`aggregate`.
   **Stop and tell the user before touching the scheduled task** (below).
4. **`App/`, `_build/`, `_docs/`, `_tests/`.** The tray becomes `App/tray.py`; its Win32 code goes
   to `_os/windows/tray.py`, with linux/macos files reporting "unsupported". Create all three skins. Rename `tests/` to `_tests/`
   with subfolders mirroring the layers.
5. **Effect declarations and the invariant test.** Every operation declares
   `EFFECT = "none" | "local" | "remote"` as a module-level constant. A test collects them by
   scanning the layer folders and asserts that everything reachable from the peer, tray,
   dashboard or scheduler is `"none"`.

## Things that will bite you

- **The scheduled task is already broken, and it is the user's.** `gitSpecOps Archive Refresh`
  runs `<repo>\gitArchiveUpdater\refresh-managed-archives.bat`, which calls
  `gitArchiveUpdater\archive_manager.py` — a file that no longer exists (the untracked folder holds
  only that `.bat` and stale `.pyc`s). Read-only query on 2026-09-20: last run 2026-09-01, result
  2 (file not found); monthly, next 2026-10-01. **Done 2026-09-22:** the new launcher is
  `<per-user config>/gitspecops/refresh_managed_archives.bat`; the user replaces the task with
  `Elaborate/archive_manage.py --install-monthly-task` and reinstalls the three archives'
  launchers (`--install <root>`). Delete `gitArchiveUpdater/` only after they confirm.
- **No fleet autostart is registered and no machine is enrolled.** That is why the migration goes
  first: `autostart` writes an absolute resolved path into the registry Run key, the XDG
  `.desktop` file and the LaunchAgent, so moving files after enrollment would break start-at-login
  silently on every machine.
- **Untracked generated folders exist at the root** (`gitArchiveUpdater/`, `build/`, `dist/`,
  `git_spec_ops.egg-info/`, `__pycache__/`). None are tracked; do not migrate them. The tracked
  folder is `_build/`, which also keeps it clear of PyInstaller's own untracked `build/`.
- **Case-only and capitalised renames on Windows** need `git mv`, then a `git status` check that
  git recorded a rename rather than leaving a ghost.
- **Move in small steps.** The current import model widens `sys.path` in `_paths.py` and
  `tests/_bootstrap.py`, and same-named modules in different tool folders can shadow each other.
  Re-run the suite after each move.

## Validation: non-negotiable

```powershell
& .\.venv\Scripts\python.exe tests\run_all.py        # 43/43 after phase 3b
& .\.venv\Scripts\python.exe tests\repo\test_repo_hygiene.py
```

(After phase 4 these live under `_tests\`.) Run the suite **alone**: on 2026-09-12 a test failed
only while five test processes ran concurrently. It takes several minutes; run it in the
background rather than behind a pipe that buffers everything. "The suite passes" means it passes on this
Windows checkout.

Do not run live GitHub duplication, archive refreshes, scheduled-task changes, or any fleet
deployment as validation unless the user asks.

## Where the product stands

**The code is complete and green; the architecture is agreed; nothing has moved.** The
medium-tier recovery chain is built end to end (capture, storage, preview, disposable restore,
peer acknowledgement, exact retirement proof), along with `catchup`, `audit`, `materialize`,
`preflight`, `live_buffers` and `safe_to_wipe`.

After the migration: enroll three machines on one fleet key, validate with one peer switched off,
and decide whether unsaved buffer *content* may ever leave a machine.

Deliberately not done: the git history still contains personal data (no secrets, verified blob by
blob; see [`knowledge/repo-privacy-and-history.md`](knowledge/repo-privacy-and-history.md)). A
rewrite is the only complete fix and breaks every clone.

## Rules that do not bend

- **These tools perform Git operations.** The boundary is *observation never mutates; mutation is
  always a command the user invoked*, planned, shown and confirmed.
- **Never commit personal information.** No local paths, machine names, addresses, or real
  account/org/repo names in code, comments, tests, notes, or commit messages.
  `test_repo_hygiene.py` enforces it and has already caught real leaks.
- **Prior auth first; cross-platform first; stdlib only; plain scripts, no package.**
- **Keep the record.** Update [`working-notes.md`](working-notes.md) as you go and graduate
  finished work into [`work-log.md`](work-log.md) with an absolute date.

# Handoff — 2026-09-20

For the next session, human or LLM. Read [`README.md`](README.md) (the project brief) first — it
opens with **What this is for**, and that section outranks every rule below it. Then this, then
[`working-notes.md`](working-notes.md).

## Your job: reorganize the guts into the agreed architecture

The product direction, the layering and the diagram are **settled**. The code has not moved yet.
This session's work is the migration, and nothing else.

Read these three, in order, before touching a file:

1. [`knowledge/architecture-layers.md`](knowledge/architecture-layers.md) — the specification:
   layers, the one-way rule, three kinds of file, three seams, contracts, migration phases.
2. [`knowledge/architecture-diagram.md`](knowledge/architecture-diagram.md) — the same thing as a
   picture, and what the picture asserts.
3. [`working-notes.md`](working-notes.md) — open items.

### The shape, in one paragraph

`git` is the raw material; authentication is assumed and never stored. **Basic** wraps one git or
remote operation with care. **Special** repeats a Basic operation with the logic of the repetition.
**Elaborate** widens that across machines and across time. **App** assembles it for a human and is
optional — mostly the tray. A layer uses only the layers above it in the diagram (below it in the
dependency sense): never sideways, never what comes after. `plugins-remote/`, `plugins-local/` and
`App/skins/` sit off the stack behind contracts; nothing imports them, they are loaded by path.

### Decisions taken 2026-09-20 — do not reopen these

- **Work directly on `main`.** The user is the only user and prefers to fix things cleanly rather
  than carry a long-lived branch. Keep each phase committed and green so `main` is never left
  mid-move for long.
- **Direct script paths are the command surface.** One file is one command; there is **no
  dispatcher**:
  ```
  python Basic/git/pull.py <repo>
  python Special/archive-update.py --root <archive>
  python Elaborate/catchup.py --apply --yes
  python App/cli.py tray
  ```
  `ls` on a layer lists exactly what that layer can do, and nothing has to be kept in sync with a
  registry. Consequence for phase 5: each operation declares its `effect` as a module-level
  constant in its own file, and the invariant test **collects them by scanning the layer folders**
  rather than reading a central list. Consequence for phase 3: `LAUNCHER_SPECS` targets the new
  direct paths. The monolithic entry points (`sync_suggester.py`, `archive_manager.py` as a CLI
  front door, `github_org_duplicator.py`) dissolve into their operations.
- **Hard break — no forwarding shims.** Move it, fix every caller, delete the old path. Two ways to
  import the same module is exactly what the layering exists to end, and the import-direction test
  can only be honest if there is one way to reach a module. Nothing external depends on these paths
  except the scheduled task, which must be regenerated regardless.

### Migration phases — each ends green

Phase 1 is where to start. Do not begin a later phase until the one before it is committed green.

1. **`Basic/`.** Collapse the two independently-evolved git subprocess wrappers
   (`shared/git_facts.run_git` and `gh_common.run_command`) into one careful `_run`. Move console,
   paths, atomic writes, facts, discovery, identity. Existing tool folders import downward; **no
   tool folder moves in this phase.** Highest value, lowest risk.
2. **`Basic/remote/` + `plugins-remote/`.** Define the contract and loader (in the stack, naming no
   host); move `gh_cli`, `remote_provider`, `provider_github`, and the duplicator's `gh` calls.
   **Add the import-direction test here** — this is the boundary worth the most.
3. **`Special/` and `Elaborate/`.** Move the operations, drop the `git-` prefixes, split
   `archive_diff` (generic classification down to Basic, archive policy stays). Update
   `LAUNCHER_SPECS`, `_paths.py`, `tests/_bootstrap.py`, and every path in the docs.
   **`archive-manage` goes to `Elaborate/`, not `Special/`** — it schedules, and scheduling is
   reach across time.
4. **`App/`, `App/skins/`, `plugins-local/`, `build/`, `docs/`.** The tray stays in `App/tray/` and
   calls `plugins-local/platform/` for per-OS mechanisms; it cannot become a plugin itself because
   it must own the main thread and the Win32 message loop.
5. **Effect declarations and the invariant tests.** Every operation declares
   `effect: none | local | remote`. Then assert the rule that matters: *everything reachable from
   the peer, tray, dashboard or scheduler is `effect: none`.*

## Things that will bite you

- **A live scheduled task points at the old layout.** `gitSpecOps Archive Refresh` executes
  `…\gitArchiveUpdater\refresh-managed-archives.bat` (note the camel-case folder — a generated
  launcher from an older naming). Phase 3 breaks it. It must be regenerated, and the user told.
- **No fleet autostart is registered**, and no machine is enrolled. That is *why* the migration
  goes first: `fleet_autostart.py` writes an absolute resolved path into the registry Run key, the
  XDG `.desktop` file and the LaunchAgent, so moving files after enrollment breaks start-at-login
  **silently** on every machine.
- **Generated, untracked folders exist** at the root (`gitArchiveUpdater/`, `build/`, `dist/`,
  `git_spec_ops.egg-info/`, `__pycache__/`). None are tracked. Do not migrate them; do check that a
  new tracked `build/` does not collide with the untracked one.
- **Case-only renames on Windows** (`git-archive-updater` → `Special/archive…`, and the new
  capitalised layer folders) need care: use `git mv` and verify with `git status` that git recorded
  a rename rather than leaving a ghost.
- **The flat-script import model is fragile to moves.** `_paths.py` and `tests/_bootstrap.py` widen
  `sys.path` deliberately, and all three tools are flat script directories, so a same-named module
  in one can shadow another. Move and re-test in small steps.

## Validation — non-negotiable

```powershell
& .\.venv\Scripts\python.exe tests\run_all.py        # 34/34 as of this handoff
& .\.venv\Scripts\python.exe tests\repo\test_repo_hygiene.py
```

Run the suite **alone** — on 2026-09-12 a test failed only while five test processes ran
concurrently. "The suite passes" means it passes *on this Windows checkout*; Windows-only defects
have shipped twice from validating on Linux.

Do not run live GitHub duplication, archive refreshes, scheduled-task changes, or any fleet
deployment as validation unless the user asks.

## Where the product stands

**The code is complete and green; the architecture is agreed; nothing has moved.** Suite 34/34 on
Windows. The medium-tier recovery chain is built end to end — capture, storage, preview,
disposable restore, peer acknowledgement, exact retirement proof — along with `fleet catchup`,
`audit`, `materialize`, `preflight`, `live-buffers` and `safe-to-wipe`.

What remains is this migration, and then operational work: enroll three machines on one fleet key,
validate with one peer switched off, and decide whether unsaved buffer *content* may ever leave a
machine.

Deliberately not done: the git history still contains personal data (no secrets — verified blob by
blob, see [`knowledge/repo-privacy-and-history.md`](knowledge/repo-privacy-and-history.md)); a
rewrite is the only complete fix and breaks every clone.

## Rules that do not bend

- **These tools perform Git operations.** The boundary is *observation never mutates; mutation is
  always a command the user invoked*, planned, shown and confirmed. A scaffold-era "never writes"
  claim outranked the product goal for 17 days — do not restore that framing.
- **Never commit personal information.** No local paths, machine names, addresses, or real
  account/org/repo names — in code, comments, tests, notes, or commit messages.
  `tests/repo/test_repo_hygiene.py` enforces it and has already caught real leaks.
- **Prior auth first; cross-platform first; stdlib only; plain scripts, no package.**
- **Keep the record.** Update [`working-notes.md`](working-notes.md) as you go and graduate
  finished work into [`work-log.md`](work-log.md) with an absolute date.

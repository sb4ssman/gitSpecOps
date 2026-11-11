# Handoff: clean tree, `git-sync-suggester/` resolved out, Qt tray over the web view

Written 2026-11-11 for whichever agent session executes it. Absorb finished phases into
`WORK-LOG.md` as you go; delete this file when every phase is done. Decisions behind it:
`knowledge/architecture-layers.md`, "Revisions, 2026-11-11". Do not re-ask them.

## Done means
- `git-sync-suggester/` and `_archive/` no longer exist. Everything in them is either moved to
  its layer, ported, or deliberately dissolved (listed below). Nothing is left half-moved.
- Every file in the target tree exists. A file that cannot be built yet has the header (below)
  and a body that says so plainly; nothing pretends to work.
- The Qt tray (PySide6) runs and opens the web view. The hand-written Windows tray is gone.
- The web view has the network map with switchable views, and can be served on the tailnet for
  a phone or tablet, watch and act, off by default.
- `gitso` lists only current commands; every command runs from its own path too.
- All tests pass, including an import-direction test that covers every layer with no exclusion.

## Rules while executing
- **The layer rule:** Basic is one Git or host operation. Special is this machine, once.
  Elaborate is other machines, or over time. App is presence and presentation.
- A file without an underscore is a command; plumbing goes in an underscore folder.
- No backward compatibility: remove old-path wrappers. The existing archive launchers on the
  user's machines will break until regenerated; that is expected (WORKING-NOTES keeps the item).
- Never relocate user data. State paths derived from `__file__` (for example the duplicator's
  ignored `Special/duplicate_org/runs/`) must keep resolving to the same place.
- Behavior-preserving moves first, then the new building, each with its tests.
- Everything below App stays standard-library Python. PySide6 is the App's only dependency.
- Public repo: no personal names, emails, home-folder names or machine names in tracked files.
  `tests/repo/test_repo_hygiene.py` must pass before every commit.

## Header template (every file)
```python
"""<What it does, one line.>

Why:          <the problem it solves>
Reads:        <what it looks at>
May change:   <what it can alter, or "nothing">
Results:      <where output goes>
Layer:        <Basic | Special: this machine, once | Elaborate: machines or time | App>
Status:       <working | placeholder: what is missing>
"""
EFFECT = "none" | "local" | "remote"      # commands only; CONSENT = "<name>" where it applies
```
Commands show this text before and during a run (CLI, web view, tray): one source for
"every operation shows what it does".

## File-by-file mapping

**Special: this machine, once**
| From | To | Notes |
|---|---|---|
| `core/advice.py` | `Special/_sync/advice.py` | classification, pure |
| `core/observer.py` | `Special/_sync/observer.py` | read-only observation of roots |
| `core/manifest.py` | `Special/_sync/manifest.py` | status facts; Elaborate publishes them |
| `core/config.py` (local part, catalog) | `Special/_sync/catalog.py` | transport parts go to Elaborate |
| `app/baskets.py` (observe selection) | `Special/_sync/selection.py` | publish selection goes to Elaborate |
| `sync_suggester.py check` (local part) | `Special/suggest_sync.py` | NEW command: observe, classify, recommend; no fleet |
| `sync_suggester.py alias` | `Special/name_repo.py` | local-only catalog name |
| `app/fleet_actions.py` (catchup) | `Special/catch_up.py` + `Special/_sync/actions.py` | fetch, fast-forward clean behind-only |
| `fleet_app safe-to-wipe` | `Special/check_safe_to_wipe.py` | |
| `fleet_app audit` | `Special/audit_repos.py` | |
| `fleet_app materialize` | `Special/materialize.py` | clone this machine's working set elsewhere |
| `core/vscode_buffers.py` + `live-buffers` | `Special/_sync/vscode_buffers.py` + `Special/list_live_buffers.py` | |
| `_archive/Security/_rewrite.py` follow, follow_many, relink, commit_map, references, published_before, assess, finish | `Special/follow_rewrite.py` + `Special/_security/follow.py` | PORT: move this machine's clones onto rewritten history and fix quoted commit ids; reconcile with current cleanup plans |
| `Special/security/` public commands | `Special/scan_tree.py`, `scan_history.py`, `review_finding.py`, `clean_history.py` | layer-root rule; `security/` becomes `_security/` |
| `Special/duplicate_org/duplicate_org.py` | deleted | wrapper; `runs/` stays where it is |
| `Special/archive_sync.py`, `inventory_export.py`, `inventory_restore.py` | `sync_archive.py`, `export_inventory.py`, `restore_inventory.py` | 2026-10-27 action-name rule |

**Basic**
| From | To | Notes |
|---|---|---|
| `core/version.py` | `Basic/_version.py` | version from pyproject; release check via host CLI |

**Elaborate: other machines, or over time**
| From | To | Notes |
|---|---|---|
| `core/aggregate.py`, `core/convergence.py` | `Elaborate/_fleet/` | |
| `fleet/fleet_display.py` | `Elaborate/_fleet/display.py` | display contract builder (policy) |
| `fleet/local_view.py`, `fleet_store.py`, `fleet_observer.py`, `fleet_events.py`, `fleet_net.py` | `Elaborate/_fleet/` | |
| `core/watcher.py` | `Elaborate/_fleet/` (change detection the peer uses) | `watch` command itself dissolved |
| `core/folder_transport.py`, `repo_transport.py` | `Elaborate/_transport/folder.py`, `repo.py` | |
| `core/config.py` (fleet/transport part), `app/fleet_config.py` | `Elaborate/_fleet/config.py` | one schema; loading never saves (explicit conversion only) |
| `app/baskets.py` (publish selection) | `Elaborate/_fleet/baskets.py` | |
| `app/fleet_peer.py`, `fleet_app run/peer/rescan` | `Elaborate/peer.py` + `Elaborate/_fleet/peer.py` | continuous |
| `sync_suggester.py check` (publish part) | `Elaborate/publish_status.py` | NEW command |
| `sync_suggester.py dashboard/check` (fleet part) | `Elaborate/suggest_fleet_sync.py` | NEW command |
| `sync_suggester.py converge` | `Elaborate/converge.py` | |
| `init`, `fleet-key`, `setup`, `peer` config, `transports`, `baskets` | `Elaborate/setup_fleet.py` | enroll this machine; App guides it |
| `app/fleet_autostart.py`, `autostart` | `Elaborate/start_at_login.py` | per-user, via `_os/` |
| `fleet_app doctor`, `preflight` | `Elaborate/doctor.py`, `Elaborate/preflight.py` | |
| `core/capture.py`, `patch_parse.py`, `secret_scan.py`, `snapshot_*.py`, `retirement.py`, `app/recovery_runtime.py`, `recovery` | `Elaborate/recovery/` (public ops) + `Elaborate/recovery/_*` | `secret_scan` switches to the shared Special security rules: one rule set |
| `Elaborate/archive_manage.py` | `Elaborate/schedule_archives.py` | scheduling only; calls Special manager |
| (new) | `Elaborate/follow_rewrite_fleet.py` | placeholder: ask other machines to follow a rewrite |
| (new) | `Elaborate/request.py` | placeholder: attended remote requests between machines |

**App: presence and presentation**
| From | To | Notes |
|---|---|---|
| `app/local_dashboard.py`, `fleet/ui_assets.py` | `App/_web/server.py`, `App/_web/_assets.py` | loopback by default |
| `ui/fleet_client.js`, `fleet_view.js` | `App/_web/skins/_common/` | |
| `ui/fleet_dashboard.html`, `fleet_standard.css/.js` | `App/_web/skins/standard/` | |
| `app/fleet_tray.py` (Win32) | `App/tray.py` (Qt) | extract menu items, status polling, start/stop, failure reasons; then delete |
| `app/fleet_desktop.py` | `App/desktop.py` | packaged entry: tray, opens the chosen view |
| `app/git_client.py`, `git-client` | `App/git_client.py` | |
| (new) | `App/window.py` | placeholder: Qt window, later |
| (new) | `App/_web/remote.py` | serve on the tailnet: watch and act (below) |
| `tests/probes/qt_shell/` | reference for `App/tray.py`; delete when superseded | |

**Dissolved:** `sync_suggester.py` (split above), `watch`, `handoff`, `init` (into setup_fleet),
`fleet` subcommand, `app/fleet_app.py` (its commands land above), `_paths.py`.
**Other moves:** `docs/` to `_docs/`; `packaging/` to `_build/` (spec, `release_check.py`,
build notes). `tests/` keeps its name (the old target tree's `_tests/` is dropped); `tests/fleet/`
splits into `tests/special/`, `tests/elaborate/`, `tests/app/`.

## New building
1. **Qt tray.** PySide6 tray on Windows, Linux (KDE), macOS: status, start/stop peer, open the
   web view or the Qt window (setting), autostart toggle via Elaborate. A start that fails says
   why for known causes (not configured, invalid settings, port in use) and stays generic
   otherwise; nothing written to disk. Rewrite the tray tests to that contract.
2. **Settings for presentation:** web server off / loopback / tailnet; tray on/off; tray opens
   web or window. Every combination works.
3. **Network map in the web view.** Machines as nodes, colored by report freshness (current,
   stale, offline); repos needing attention on each; lines for machines that reach each other.
   Matching repos across machines line up visually. Switchable views: machines together; whole
   library; one library folder (a folder of orgs) across machines; one org across machines; one
   repo across machines. A chosen machine sets the perspective. Contract additions are additive
   (version stays 1); policy stays in `Elaborate/_fleet/display.py`, drawing in the skin.
4. **Remote watch and act.** Optional listener on the tailnet interface only, off by default.
   Admit only devices of the configured Tailscale user (reuse `fleet_net`'s identity check).
   Actions use the same plan, show, confirm path with a per-session token; forced, reset,
   rebase, merge and delete are never available. Document the threat model in `_docs/`.
5. **Port and delete `_archive/`** (follow/relink above), then delete it.
6. **Entry points:** `gitso.py` (drop legacy `sync`/`app`, add new commands), `setup_gitspecops.py`,
   `run_setup.*`, `tests/_bootstrap.py` (drop `SYNC_DIR`), README "Repo Shape", the tree and
   diagram in `knowledge/`.
7. **Dependency:** declare PySide6-Essentials as an optional App dependency in `pyproject.toml`
   and `uv.lock` (already present in `.venv`, undeclared).
8. **Import-direction test** covers every layer with no exclusion; drop the obsolete Security
   rank; App alone may import PySide6.

## Phases (commit at each green checkpoint)
1. Baseline: run `tests/run_all.py`, record results.
2. Special and Basic moves; Special commands working; tests moved.
3. Elaborate moves; new `suggest_fleet_sync`, `publish_status`; peer runs from its new home.
4. App web moves; dashboard serves from `App/_web/`.
5. Qt tray; Windows tray deleted.
6. Network map views.
7. Remote watch and act.
8. Port `_archive/`; delete `_archive/` and `git-sync-suggester/`.
9. Entry points, docs, headers everywhere, full verification (all tests, hygiene, every command
   from `gitso` and its own path, tray and web view run by hand on Windows).

## Progress (2026-11-11 13:41, checkpoint commit)
- Done: phases 1-8. `git-sync-suggester/` and `_archive/` are gone; every file is in its layer;
  the import-direction test covers 177 files with no exclusion; 79/79 test files pass; every
  command answers `--help` from its own path and is listed by `gitso` (34 commands).
- Choices made while executing (the user may change any):
  - `baskets.py` stayed whole in `Special/_sync/` (pure selection logic) instead of splitting.
  - `git_client.py` sits in `Special/_sync/` (fleet config validates it; it starts only a
    desktop program), not `App/`.
  - The v1 status CLI stays one plumbing module (`Elaborate/_fleet/sync_cli.py`) behind three
    commands (publish_status, suggest_fleet_sync, converge); `alias` became `Special/name_repo.py`.
  - Local commands take the fleet's configuration lock (`Special/_sync/lock.py`), as before.
  - The hygiene test keeps version 1's exact rules, moved beside it (`tests/repo/_hygiene_*`).
  - Plumbing files keep their own docstrings; commands carry the header template.
  - Loading never converts settings: `Elaborate/setup_fleet.py convert` is the explicit step.
- Left in phase 9: delete `App/_win_tray_reference.py` (next commit; DCG blocks a forced
  removal of an edited file); run the Qt tray and the web view by hand on a desktop and look
  at the map; recovery's `secret_scan` onto the shared security rules; the hygiene test onto
  the shared rules; one configuration for status publishing and the fleet app (two exist).

## Open after this (not part of it)
Qt window; what "install" means for the fleet; regenerate archive launchers; native Linux and
macOS runs; Elaborate placeholders above.

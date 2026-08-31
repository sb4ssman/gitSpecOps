# Working notes

Living todo / scratch pad. Add items freely; **prune regularly**. When something is done, move it
into [`work-log.md`](work-log.md) with an absolute date. Dates are always absolute.

_Last tended: 2026-08-31_

## Open

- [ ] **Batch "all my orgs" mode (Mode 4) is implemented, awaiting your live run.** Org selection
  accepts print-style ranges (`1-5, 7, 9-25`), names, `all`, and `except`/`!` exclusions; filters
  (private/archived/forks), format, and parallelism are prompted at run time. Per-org scoped
  tracking files in `tracking.py` (resume never collides/clears), one typed-YES plan table, batch
  manifest in `runs/`. Parser unit-tested with synthetic org names only.
- [ ] **Sync Suggester scaffold is live; complete the first vertical slice.** The consolidated design
  is in [`new-tool-sync-suggester.md`](new-tool-sync-suggester.md). Flat read-only modules now exist:
  `sync_suggester.py` (CLI flow), `observer.py` (configured-root facts), `manifest.py` (privacy-safe
  schema + atomic JSON), `folder_transport.py` (one file per machine), and `advice.py` (pure
  classification + ASCII rendering); synthetic tests stay under root `tests/`. `check` supports
  bounded roots, local readable tables, and optional atomic hash-only publication; `doctor` is
  read-only. Next: persistent local config/catalog, peer-manifest aggregation + freshness rules,
  then implement the reserved `init`, `watch`, and `handoff` flows. Continue to reuse
  `shared/repo_discovery.py`, `shared/git_facts.py`, and `shared/remote_identity.py`; do not build a
  second discovery/Git wrapper. No pull, push, commit, stash, patch transfer, tray, OAuth, or
  Git-backed transport in the first slice. Decisions recorded: direct-child discovery by default
  with per-root recursive opt-in; hashed repo identities in synced manifests plus an unsynced local
  name/path catalog for readable tables; configurable freshness with initial 24-hour stale and 7-day
  expired thresholds. Follow with visible polling/watch mode, semantic-change writes, heartbeat, and
  best-effort final publish; source-remote fetching remains a separate policy decision.

## Someday / deferred

- Deferred from the setup/venv work (see work-log 2026-07-21): no `--dry-run` / `--yes` flags on
  the duplicator yet; `_legacy_sources/` left untouched.
- Future direction: the push/"publish" direction for `archive_sync` — design captured in
  [`README.md`](README.md#future-direction-the-push-direction-publish); not started.
- Multi-host support is a stated goal: archive tools first via `shared/providers.py` (one
  `provider_<host>.py` + `register_provider(...)` per host; fix `remote_identity` URL-port
  parsing first). `github-org-duplicator` stays GitHub-specific by design. Auth stays
  user-owned (host CLI logins); no credential management anywhere.

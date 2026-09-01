# Working notes

Living todo / scratch pad. Add items freely; **prune regularly**. When something is done, move it
into [`work-log.md`](work-log.md) with an absolute date. Dates are always absolute.

_Last tended: 2026-09-01_

## Open

- [ ] **`.venv` stays package-free — watch for regressions.** `[tool.uv] package = false` makes
  `uv sync` a virtual project (`uv.lock` shows `source = { virtual = "." }`, no `.pth`). If a stray
  `pip install -e .` or a pyproject edit ever re-adds an `__editable__*.pth` / `git_spec_ops*.egg-info`,
  remove it. See [`knowledge/venv-and-editors.md`](knowledge/venv-and-editors.md).
- [ ] **Duplicator modes 1-3 (download-one / upload / migrate): follow-ups.** They inherit the
  `run_command` timeout + `GIT_TERMINAL_PROMPT=0` + jittered backoff, but (a) their retry loops
  still retry a `CommandTimeout` twice (mode-4's clone loop re-raises it — a hang won't un-hang),
  and (b) they have no CLI flags — only `--batch`/`--single` do; `--answers FILE` is the stopgap.
  Both low priority; mode 4 is the hot path. Same `parse_args()` pattern if it's ever wanted.
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

- `--yes` shipped for the duplicator (2026-08-31, batch + single); no `--dry-run` yet.
  `_legacy_sources/` still left untouched.
- Future direction: the push/"publish" direction for `archive_sync` — design captured in
  [`README.md`](README.md#future-direction-the-push-direction-publish); not started.
- Multi-host support is a stated goal: archive tools first via `shared/providers.py` (one
  `provider_<host>.py` + `register_provider(...)` per host; fix `remote_identity` URL-port
  parsing first). `github-org-duplicator` stays GitHub-specific by design. Auth stays
  user-owned (host CLI logins); no credential management anywhere.

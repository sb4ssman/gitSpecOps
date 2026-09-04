# Working notes

Living todo / scratch pad. Add items freely; **prune regularly**. When something is done, move it
into [`work-log.md`](work-log.md) with an absolute date. Dates are always absolute.

_Last tended: 2026-09-03_

## Open

- [ ] **`.venv` stays package-free — watch for regressions.** `[tool.uv] package = false` makes
  `uv sync` a virtual project (`uv.lock` shows `source = { virtual = "." }`, no `.pth`). If a stray
  `pip install -e .` or a pyproject edit ever re-adds an `__editable__*.pth` / `git_spec_ops*.egg-info`,
  remove it. See [`knowledge/venv-and-editors.md`](knowledge/venv-and-editors.md).
- [ ] **Duplicator modes 1-3 (download-one / upload / migrate): no CLI flags.** Only
  `--batch`/`--single` have them; `--answers FILE` is the stopgap. Low priority — mode 4 is the hot
  path — and the same `parse_args()` pattern applies if it is ever wanted. (The `CommandTimeout`
  retry half of this item was fixed 2026-09-03.)
- [ ] **Sync Suggester: what the first slice deliberately left out.** The slice shipped
  2026-09-03 (see [`work-log.md`](work-log.md)) — `init`/`check`/`dashboard`/`alias`/`watch`/`doctor`
  all run. Still open, roughly in priority order:
  - `handoff` — the mutation flow (auto-commit, WIP branches, patch/untracked transfer). Needs its
    own design pass first; it must never end up inside the watcher or a scheduled publisher, for
    the same reason `--reconcile`/`--rename-folders` stay interactive-only in the archive tools.
  - **Source-remote fetching.** Every ↑/↓ today comes from cached remote-tracking refs;
    `upstream_observed_at` is carried through the schema but is always `null` because nothing
    fetches. Whether `check` should fetch (never / opt-in / scheduled) is still the open decision
    from the design doc. The dashboard already footnotes the uncertainty honestly.
  - **Installing the watch** — login task, periodic timer, or tray, per OS. `watch` runs in the
    foreground today and that is the honest starting point.
  - Long-lived stashes: information, or do they block an "all clear"? Currently a `stashed` row
    ranks above `unknown` but below `ahead`, so it surfaces without shouting.
  - The **advice → apply** step (clean + behind-only + fresh fetch -> `git pull --ff-only`) is
    still purely advisory and should stay that way until fetching is settled.

- [ ] **Manifest privacy: `repo_id` is brute-forceable and `head` is an unused de-anonymizer.**
  Verified during the first slice that no name/path/URL leaves the machine — but the unsalted
  hash of `host/owner/name`, plus a published commit SHA nothing reads, plus human-authored
  branch names, together let anyone holding the state folder recover which repositories a
  machine has. Options and a recommendation (drop `head`; consider an HMAC identity; write down
  the threat model) are in [`knowledge/manifest-privacy.md`](knowledge/manifest-privacy.md).
  Needs a decision from the user because every option is a `schema_version` bump.

## Someday / deferred

- `--yes` shipped for the duplicator (2026-08-31, batch + single); no `--dry-run` yet.
  `_legacy_sources/` still left untouched.
- Future direction: the push/"publish" direction for `archive_sync` — design captured in
  [`README.md`](README.md#future-direction-the-push-direction-publish); not started.
- Multi-host support is a stated goal: archive tools first via `shared/providers.py` (one
  `provider_<host>.py` + `register_provider(...)` per host; fix `remote_identity` URL-port
  parsing first). `github-org-duplicator` stays GitHub-specific by design. Auth stays
  user-owned (host CLI logins); no credential management anywhere.

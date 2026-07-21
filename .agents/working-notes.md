# Working notes

Living todo / scratch pad. Add items freely; **prune regularly**. When something is done, move it
into [`work-log.md`](work-log.md) with an absolute date. Dates are always absolute.

_Last tended: 2026-07-21_

## Open

- [ ] **`.venv` not yet built in this checkout.** The launchers currently still route through
  `uv run`. Running `run_setup` (`.\run_setup.bat` / `.ps1` / `.sh`) once builds `.venv` and
  exercises the prefer-`.venv` path. End-to-end verification of the prefer-`.venv`/fallback model
  (incl. the stdlib fallback with `uv` hidden from PATH) has **not** been done.

## Someday / deferred

- Deferred from the setup/venv work (see work-log 2026-07-21): no `--dry-run` / `--yes` flags on
  the duplicator yet; `_legacy_sources/` left untouched.
- Future direction: the push/"publish" direction for `archive_sync` — design captured in
  [`README.md`](README.md#future-direction-the-push-direction-publish); not started.

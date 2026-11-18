# gitSpecOps — agent brief

**git Special Operations** — careful, cross-platform, stdlib-only tooling for people with far too
many Git repositories, spread across many namespaces and several machines. Four operations today:
an archive updater/manager (`Special/archive_update.py`, `Special/archive.py`), an org
duplicator (`Special/org_copy.py`), Sync Suggester (`Special/machine_check.py`) and its fleet (`Elaborate/`, `App/`), and
the app that brings them together.

**Read [`.agents/README.md`](.agents/README.md) first — it is the primary project brief.** It
opens with **What this is for**, and that section outranks every rule below it: if a rule
contradicts the goal, the goal wins and the rule is the defect.

## Before you act

- Explain the plan first.
- Ask before running anything in the background (tray, peer, or scheduled tasks), acting over SSH, or capturing a screen.
- Work with the Destructive Command Guard. Do not force-push, reset, rebase, or delete branches.
- Stay on `dev`. Commit and push only when asked.
- Run `tests/repo/test_repo_hygiene.py` before every commit and stop if it fails.
- Always say what was not verified.

Three things that are easy to get backwards:

- **These tools perform Git operations** — that is the product, not a compromise. The boundary is
  *observation never mutates; background change happens only under a standing consent the user
  configured (fast-forward of clean, behind-only checkouts); everything else is a command the
  user invoked*, planned, shown and confirmed.
- **Prior auth first.** Shell out to already-authenticated host CLIs; never store, configure, or
  prompt for a credential.
- **Cross-platform first**, and git-agnostic as the direction of travel — host-specific code
  belongs behind the provider seam.

Architecture is a layer stack with a one-way import rule — see
[`.agents/knowledge/architecture-layers.md`](.agents/knowledge/architecture-layers.md). Plain
scripts throughout: no `src/` package, no console-script entry points.

Terminal screens follow Sb4ssport's station script design, copied unchanged in
[`.agents/knowledge/station-script-design.md`](.agents/knowledge/station-script-design.md) (the
authority is Sb4ssport-Authority `.agents/knowledge/launchers.md`; re-copy it when it changes).
Every screen opens with its banner, drawn by `Basic/_station.py`.

Keep [`.agents/WORKING-NOTES.md`](.agents/WORKING-NOTES.md) current as you work, and graduate
completed work into [`.agents/WORK-LOG.md`](.agents/WORK-LOG.md) — appended at the bottom,
stamped `YYYY-MM-DD HH:MM`.

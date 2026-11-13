# gitSpecOps — agent brief

**git Special Operations** — careful, cross-platform, stdlib-only tooling for people with far too
many Git repositories, spread across many namespaces and several machines. Four operations today:
an archive updater/manager (`Special/update_archive.py`, `Special/archive_manager.py`), an org
duplicator (`Special/duplicate_org.py`), Sync Suggester (`Special/suggest_sync.py`) and its fleet (`Elaborate/`, `App/`), and
the app that brings them together.

**Read [`.agents/README.md`](.agents/README.md) first — it is the primary project brief.** It
opens with **What this is for**, and that section outranks every rule below it: if a rule
contradicts the goal, the goal wins and the rule is the defect.

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

**Every terminal screen follows the station script design**, a verbatim copy of Sb4ssport's
standard: [`.agents/knowledge/station-script-design.md`](.agents/knowledge/station-script-design.md).
Read it before touching any console output; draw screens only through `Basic/_station.py`
(banner, rows, options, notices, steps, summary). The authority is
`Sb4ssport-Alpha/Sb4ssport-Authority/.agents/knowledge/launchers.md`: when it changes, re-copy
it here unchanged and bring `Basic/_station.py` into line in the same batch.

Keep [`.agents/WORKING-NOTES.md`](.agents/WORKING-NOTES.md) current as you work, and graduate
completed work into [`.agents/WORK-LOG.md`](.agents/WORK-LOG.md) — appended at the bottom,
stamped `YYYY-MM-DD HH:MM`.

# gitSpecOps — agent brief

**git Special Operations** — careful, cross-platform, stdlib-only tooling for people with far too
many Git repositories, spread across many namespaces and several machines. Four operations today:
an archive updater/manager (`git-archive-updater/`), an org duplicator (`github-org-duplicator/`),
Sync Suggester and its fleet (`git-sync-suggester/`), and the app that brings them together.

**Read [`.agents/README.md`](.agents/README.md) first — it is the primary project brief.** It
opens with **What this is for**, and that section outranks every rule below it: if a rule
contradicts the goal, the goal wins and the rule is the defect.

Three things that are easy to get backwards:

- **These tools perform Git operations** — that is the product, not a compromise. The boundary is
  *observation never mutates; mutation is always a command the user invoked*, planned, shown and
  confirmed.
- **Prior auth first.** Shell out to already-authenticated host CLIs; never store, configure, or
  prompt for a credential.
- **Cross-platform first**, and git-agnostic as the direction of travel — host-specific code
  belongs behind the provider seam.

Architecture is a layer stack with a one-way import rule — see
[`.agents/knowledge/architecture-layers.md`](.agents/knowledge/architecture-layers.md). Plain
scripts throughout: no `src/` package, no console-script entry points.

Keep [`.agents/working-notes.md`](.agents/working-notes.md) current as you work, and graduate
completed work into [`.agents/work-log.md`](.agents/work-log.md) with an absolute date.

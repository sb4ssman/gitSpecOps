# knowledge/

Durable, hand-authored knowledge about this project — decisions, findings, and background that the
code and git history do not capture. One topic per file (kebab-case names).

Unlike [`../WORKING-NOTES.md`](../WORKING-NOTES.md), which is transient and pruned, entries here are
**kept**. Reach for this folder when you learn something worth remembering next session: a design
decision and its rationale, a non-obvious constraint, an investigation result.

- [`architecture-layers.md`](architecture-layers.md) — **the layer stack; migration done 2026-11-11.**
  The layer stack (Basic → Special → Elaborate → App) as *composition*, the one-way import rule,
  the full target tree, providers as the one host seam, skins, `EFFECT` declarations, and
  why the migration precedes enrolling machines.
- [`architecture-diagram.md`](architecture-diagram.md) — the layer stack as a picture: the ASCII
  flow chart, what it asserts, and where the rendered version lives.
- [`at-risk-work.md`](at-risk-work.md) — **design, not built.** Detecting repositories that exist
  in only one place; the risk classes, and the remote-free root-commit identity they need.
- [`change-detection.md`](change-detection.md) — how change is noticed without scanning.
- [`distribution.md`](distribution.md) — packaging and delivery direction.
- [`handoff-design.md`](handoff-design.md) — **design, not built.** Moving work in progress
  from one machine to another, and why it needs its own privacy boundary.
- [`live-fleet.md`](live-fleet.md) — the tailnet tier.
- [`manifest-privacy.md`](manifest-privacy.md) — what a published record may contain, and why the
  salt is worth a different amount per transport.
- [`repo-privacy-and-history.md`](repo-privacy-and-history.md) — the blob-by-blob history audit:
  personal data, no secrets.
- [`security-design.md`](security-design.md) — **2026-10-20, the Security rebuild.** Why the
  first `Security/` had the wrong shape, the design that replaces it (material, checks, remedies;
  security inside the layers), `clean_history` and its stops, the watch list, what GitHub does
  better, and the phased plan.
- [`test-suite-audit.md`](test-suite-audit.md) — **2026-10-19, first read of what the tests
  assert.** Strong where it exists; confirmed defects (safe-to-wipe said SAFE over unpushed work;
  duplicator cleanup deleted a non-repository folder; both fixed 2026-10-19), untested verbs, weak
  assertions, and the repair order.
- [`tiers-and-capture.md`](tiers-and-capture.md) — what each tier is supposed to be able to
  *rescue*, not merely how fast it is.
- [`venv-and-editors.md`](venv-and-editors.md) — why `.venv` must stay package-free (an editable
  install's startup `.pth` + an editor's stray `^C` = `Fatal Python error: init_import_site`), and
  the VS Code settings that stop terminal-injection breaking interactive prompts.
- [`external-review-2026-11-17.md`](external-review-2026-11-17.md) — an outside model's read-only
  review: nine findings with their status (two fixed, the rest unverified), the wider points, and
  its suggested order of work. A backlog, kept out of WORKING-NOTES.

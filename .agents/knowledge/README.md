# knowledge/

Durable, hand-authored knowledge about this project — decisions, findings, and background that the
code and git history do not capture. One topic per file (kebab-case names).

Unlike [`../working-notes.md`](../working-notes.md), which is transient and pruned, entries here are
**kept**. Reach for this folder when you learn something worth remembering next session: a design
decision and its rationale, a non-obvious constraint, an investigation result.

- [`at-risk-work.md`](at-risk-work.md) — **design, not built.** Detecting repositories that exist
  in only one place; the risk classes, and the remote-free root-commit identity they need.
- [`change-detection.md`](change-detection.md) — how change is noticed without scanning.
- [`distribution.md`](distribution.md) — packaging and delivery direction.
- [`live-fleet.md`](live-fleet.md) — the tailnet tier.
- [`manifest-privacy.md`](manifest-privacy.md) — what a published record may contain, and why the
  salt is worth a different amount per transport.
- [`repo-privacy-and-history.md`](repo-privacy-and-history.md) — the blob-by-blob history audit:
  personal data, no secrets.
- [`shared-layer.md`](shared-layer.md) — the `shared/` cross-operation primitive layer: admission
  rule, module list, import mechanics, Linux notes.
- [`tiers-and-capture.md`](tiers-and-capture.md) — what each tier is supposed to be able to
  *rescue*, not merely how fast it is.
- [`venv-and-editors.md`](venv-and-editors.md) — why `.venv` must stay package-free (an editable
  install's startup `.pth` + an editor's stray `^C` = `Fatal Python error: init_import_site`), and
  the VS Code settings that stop terminal-injection breaking interactive prompts.

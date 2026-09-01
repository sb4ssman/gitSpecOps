# knowledge/

Durable, hand-authored knowledge about this project — decisions, findings, and background that the
code and git history do not capture. One topic per file (kebab-case names).

Unlike [`../working-notes.md`](../working-notes.md), which is transient and pruned, entries here are
**kept**. Reach for this folder when you learn something worth remembering next session: a design
decision and its rationale, a non-obvious constraint, an investigation result.

- [`shared-layer.md`](shared-layer.md) — the `shared/` cross-operation primitive layer: admission
  rule, module list, import mechanics, Linux notes.
- [`venv-and-editors.md`](venv-and-editors.md) — why `.venv` must stay package-free (an editable
  install's startup `.pth` + an editor's stray `^C` = `Fatal Python error: init_import_site`), and
  the VS Code settings that stop terminal-injection breaking interactive prompts.

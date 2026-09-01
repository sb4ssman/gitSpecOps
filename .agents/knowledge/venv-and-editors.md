# `.venv` is a bare interpreter — never install the project into it

_Finding recorded 2026-08-31._

## What happened

Running the org duplicator through a VS Code "Run" action
(`/usr/bin/env sh ".../duplicate-github-org.sh"`) crashed before the script executed:

```
^CFatal Python error: init_import_site: Failed to import the site module
  ...
  File "/.../.venv/lib/python3.13/site-packages/__editable___git_spec_ops_0_1_0_finder.py", line 7
    from pathlib import Path
  ...
  File "/usr/lib/python3.13/collections/__init__.py", line 305, in OrderedDict
KeyboardInterrupt
```

Two causes stacked:

1. **`.venv` contained an editable install of this project.** `uv sync` (and the old stdlib
   fallback's `pip install -e .`) installed `git-spec-ops` editable, which drops
   `__editable__.git_spec_ops-0.1.0.pth` into site-packages. That `.pth` runs
   `__editable___git_spec_ops_0_1_0_finder.install()` on **every interpreter startup**, importing
   `pathlib` → `functools` → `collections` during `site` initialization.
2. **The editor sent a stray `SIGINT` (`^C`) during interpreter startup.** It landed inside that
   `.pth` import, and a failure during `site` init is fatal (`init_import_site`), not a catchable
   `KeyboardInterrupt`.

## Fix (done 2026-08-31)

- **Do not install the project into `.venv`.** It is not an importable package — every tool is a
  flat stdlib-only script that puts its own dir (and the repo root, for `shared/`) on `sys.path`
  at runtime. `.venv` exists only to give the launchers a clean, predictable interpreter.
  - `pyproject.toml`: added `[tool.uv]` `package = false`; dropped `[build-system]` /
    `[tool.setuptools]`. Left a comment explaining why.
  - `setup_gitspecops.py`: `create_venv_with_stdlib()` now just makes the bare venv — no
    `pip install -e .`, no pip upgrade.
  - Removed the existing artifacts: the two `__editable__*` files + `git_spec_ops-0.1.0.dist-info/`
    from `.venv/lib/python3.13/site-packages/`, root `git_spec_ops.egg-info/`, and `uv.lock`
    (regenerates clean; it is gitignored).
  - After: `site` import is ~5 ms and runs no project code; a stray SIGINT during startup can no
    longer cause `init_import_site` to fail.
- `.vscode/settings.json` (gitignored, local): `python.terminal.activateEnvironment: false` (stop
  VS Code typing `source .venv/bin/activate` into terminals — that injection is the *other*
  failure mode, the one that corrupts an open `input()` prompt), interpreter pinned to `.venv`,
  and Code-Runner settings to run in-terminal without a pre-run clear/interrupt.

## Rule going forward

`.venv` stays dependency-free and package-free. If a real third-party dependency is ever added,
put it in `[project].dependencies` and let `uv sync` install *it* — but keep `package = false` so
the project itself is never installed. Prefer running tools as `python3 <tool>/<script>.py` or via
the launcher; avoid editor "Run" buttons, which send `^C` before the command.

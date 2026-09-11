"""The one place that puts this tool's folders on ``sys.path``.

The modules here stay flat scripts -- no package, no console-script entry point (see
``.agents/README.md``). Splitting them across ``core/``, ``fleet/`` and ``app/`` for legibility
therefore needs the import path widened once, at whichever file is actually executed, instead
of rewriting every bare ``from manifest import ...`` into a package path.

Only entry points call ``bootstrap()``. Anything imported afterwards inherits the path.

Layout:
  ``core/``   observation, manifests, advice, config, transports -- no fleet or UI knowledge
  ``fleet/``  the live tailnet tier: protocol, store, observer, display contract
  ``app/``    process shells: CLI app, tray, desktop bundle, start-at-login
  ``ui/``     browser assets, served by name; never imported
  ``build/``  packaging recipe; ``docs/`` user and contract documentation
"""
from __future__ import annotations

import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOL_DIR.parent
UI_DIR = TOOL_DIR / "ui"
#: Order matters only for shadowing; these names are distinct, so it does not bite here.
CODE_DIRS = ("core", "fleet", "app")


def bootstrap() -> None:
    """Idempotent. Adds the repo root (for ``shared/``) and this tool's code folders."""
    for path in (REPO_ROOT, *(TOOL_DIR / name for name in CODE_DIRS)):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)

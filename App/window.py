"""The gitSpecOps Qt window: the fleet, its network map and every operation, without a browser.

Why:          the usual desktop setup is the Qt app; the window is its main view.
Reads:        the same display document as the web view.
May change:   nothing yet.
Results:      until it is built, opening it opens the web view instead and says so.
Layer:        App: presence and presentation. Needs PySide6 (Qt).
Status:       placeholder: the window is not built; the web view is the full view today.
"""
from __future__ import annotations

import webbrowser

EFFECT = "none"


def open_window(context: dict) -> None:
    """Called by the tray when its view is set to `window`."""
    url = context.get("url")
    if url:
        webbrowser.open(url)


def main(argv=None) -> int:
    print("The Qt window is not built yet. Use App/tray.py (it opens the web view) or "
          "App/serve_web.py.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

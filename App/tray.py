"""Run this machine's fleet peer behind a tray icon, and open its web view from the tray.

Why:          a fleet whose peers are not running knows nothing. The tray makes "is it
              running?" a glance, and stopping it deliberate rather than accidental.
Reads:        the running peer's display document every few seconds, in memory.
May change:   nothing itself. Its menu runs the same operations as the terminal: rescan,
              catch-up preview (fetch only), start at login.
Results:      a tray icon (Windows, KDE and other trays, macOS menu bar), its tooltip and
              notifications; the web view in the browser. Counts-only operational events go
              to the log the common app settings choose; console text is never written to disk.
Layer:        App: presence and presentation. Needs PySide6 (Qt).
Status:       working; the Qt window is a placeholder (App/window.py).

    python App/tray.py [--config-dir D] [--settings-home H] [--view web|window]
                       [--open-on-start] [--remote]
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from App._tray.qt import TrayUnavailable, main, run_tray  # noqa: E402,F401

EFFECT = "none"

if __name__ == "__main__":
    raise SystemExit(main())

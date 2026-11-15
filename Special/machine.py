"""Enroll this machine: its library folders, and how the app shows itself.

Why:          the tray and every local command work on this machine's libraries; nothing is
              inventoried until you name them, and a machine may hold several.
Reads:        the settings profile; `find` reads folder names where you tell it to look
              (a folder, or --whole-machine), only after you approve.
May change:   the profile's machine identity, libraries and presentation choices (what the
              tray opens; the web view off, on this machine, or on your tailnet). Never a
              repository, and never a fleet: joining one is gitso fleet setup.
Results:      JSON without a terminal (or with --json); a screen at one.
Layer:        Special: this machine, once.
Status:       working

    gitso machine show
    gitso machine find T:/ | --whole-machine
    gitso machine add T:/Github [D:/More]   (shows what it will look through, then asks)
    gitso machine remove D:/More
    gitso machine presentation --face web --web loopback
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Special._sync.commands import enroll_machine_main as main  # noqa: E402

EFFECT = "local"

if __name__ == "__main__":
    raise SystemExit(main())

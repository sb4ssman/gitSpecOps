"""Enroll this machine with the app: which library folders it holds, and how the app shows itself.

Why:          the tray and every local command work on this machine's libraries; nothing is
              inventoried until you name them, and a machine may hold several.
Reads:        the settings profile; `find` reads folder names where you tell it to look
              (a folder, or --whole-machine), only after you type LOOK.
May change:   the profile's machine identity, libraries and presentation choices (what the
              tray opens; the web view off, on this machine, or on your tailnet). Never a
              repository, and never a fleet: joining one is Elaborate/setup_fleet.py.
Results:      text on stdout.
Layer:        Special: this machine, once.
Status:       working

    python Special/enroll_machine.py                       # show
    python Special/enroll_machine.py find T:/ | --whole-machine
    python Special/enroll_machine.py add T:/Github [D:/More]   (asks you to type SCAN)
    python Special/enroll_machine.py remove D:/More
    python Special/enroll_machine.py presentation --face web --web loopback
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

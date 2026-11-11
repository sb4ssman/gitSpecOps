"""The packaged desktop app's entry: first-run setup when needed, then the tray and its web view.

Why:          a person who opens the app should get a running tray, not a terminal to babysit.
Reads:        whether this machine is enrolled in the fleet.
May change:   on first run, the answers to the setup questions (this machine's fleet settings).
Results:      the tray (App/tray.py), with the web view opened once.
Layer:        App: presence and presentation.
Status:       working

The bundle is also the command line: `GitSpecOpsSync doctor`, `... autostart enable` reach the
fleet commands, and the tray options that start-at-login registers reach the tray.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Elaborate._fleet.cli import load_saved, main  # noqa: E402
from Elaborate._fleet.config import DEFAULT_LOCAL_PORT  # noqa: E402
from Special._settings.fleet import fleet_directory, load_fleet_settings  # noqa: E402

EFFECT = "local"


def dashboard_url(config: dict) -> str:
    """Every machine's own loopback dashboard. It needs no Tailscale and no other machine."""
    return f"http://127.0.0.1:{int(config.get('local_port') or DEFAULT_LOCAL_PORT)}/"


def tray(argv) -> int:
    from App._tray.qt import main as tray_main

    return tray_main(argv)


def desktop_main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and not argv[0].startswith("-"):
        return main(argv)
    if argv:
        return tray(argv)
    try:
        load_fleet_settings()  # invalid common configuration must not start first-run setup
        directory = fleet_directory()
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        load_saved(directory)
    except ValueError:
        code = main(["setup", "--configure-only"])
        if code:
            return code
    return tray(["--open-on-start"])


if __name__ == "__main__":
    raise SystemExit(desktop_main())

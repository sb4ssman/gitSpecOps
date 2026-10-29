"""Desktop entry point for a PyInstaller one-folder build.

The engine and browser UI stay unchanged. This shell decides only three things: run terminal
first-run setup when there is no configuration, open the dashboard once, and then hand the
process to the tray so the app has a visible, stoppable presence instead of owning a terminal
for the whole session. Observation, authorization and Git policy stay out of here.

Where no stdlib tray exists (Linux, macOS) the app runs in the foreground exactly as before;
`fleet autostart enable` is the supported way to keep it running there.
"""
from __future__ import annotations

import sys
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _paths import bootstrap  # noqa: E402

bootstrap()

from fleet_app import APP_CONFIG, load_saved, main  # noqa: E402
from Special._settings.fleet import fleet_directory, load_fleet_settings  # noqa: E402
from fleet_config import DEFAULT_LOCAL_PORT  # noqa: E402


def dashboard_url(config: dict) -> str:
    """Every machine's own loopback dashboard. It needs no Tailscale and no other machine.

    This used to build a Tailscale host URL from the retired host/client keys, so the packaged
    app retried for half an hour and never opened anything for a peer configuration.
    """
    return f"http://127.0.0.1:{int(config.get('local_port') or DEFAULT_LOCAL_PORT)}/"


def open_when_ready(config_path: Path) -> None:
    for _attempt in range(3600):
        try:
            config = load_saved(config_path.parent)
            time.sleep(1)
            webbrowser.open(dashboard_url(config))
            return
        except (OSError, ValueError, KeyError):
            time.sleep(0.5)


def desktop_main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        # The bundle is also the CLI: `GitSpecOpsSync.exe doctor`, `... autostart enable`,
        # and the `tray` argv that the login entry registers all arrive here.
        return main(argv)
    try:
        load_fleet_settings()  # invalid common configuration must not start first-run setup
        config_path = fleet_directory() / APP_CONFIG
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        load_saved(config_path.parent)
    except ValueError:
        # First run is still terminal-driven; --configure-only hands the process back here so
        # the very first session also gets a tray rather than waiting for a restart.
        code = main(["setup", "--configure-only"])
        if code:
            return code
    threading.Thread(target=open_when_ready, args=(config_path,), daemon=True).start()
    return main(["tray"])


if __name__ == "__main__":
    raise SystemExit(desktop_main())

"""Desktop entry point for a PyInstaller one-folder build.

The engine and browser UI stay unchanged. This shell decides only three things: run terminal
first-run setup when there is no configuration, open the dashboard once, and then hand the
process to the tray so the app has a visible, stoppable presence instead of owning a terminal
for the whole session. Observation, authorization and Git policy stay out of here.

Where no stdlib tray exists (Linux, macOS) the app runs in the foreground exactly as before;
`fleet autostart enable` is the supported way to keep it running there.
"""
from __future__ import annotations

import json
import sys
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _paths import bootstrap  # noqa: E402

bootstrap()

from config import default_config_dir  # noqa: E402
from fleet_app import APP_CONFIG, main  # noqa: E402
from fleet_net import local_identity  # noqa: E402


def dashboard_url(config: dict) -> str:
    if config["mode"] == "connect":
        return config["server"].rstrip("/") + "/"
    return f"http://{local_identity()['ip']}:{config['port']}/"


def open_when_ready(config_path: Path) -> None:
    for _attempt in range(3600):
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
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
    config_path = default_config_dir() / APP_CONFIG
    if not config_path.exists():
        # First run is still terminal-driven; --configure-only hands the process back here so
        # the very first session also gets a tray rather than waiting for a restart.
        code = main(["setup", "--configure-only"])
        if code or not config_path.exists():
            return code or 1
    threading.Thread(target=open_when_ready, args=(config_path,), daemon=True).start()
    return main(["tray"])


if __name__ == "__main__":
    raise SystemExit(desktop_main())

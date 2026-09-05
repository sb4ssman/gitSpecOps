"""Desktop-preview entry point suitable for a PyInstaller one-folder build.

The engine and browser UI stay unchanged. This small shell opens the fleet dashboard and
runs first-time terminal setup when configuration does not exist. A later tray shell can
replace this file without moving observation, authorization, or Git policy into the UI.
"""
from __future__ import annotations

import json
import threading
import time
import webbrowser
from pathlib import Path

from config import default_config_dir
from fleet_app import APP_CONFIG, main
from fleet_net import local_identity


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


def desktop_main() -> int:
    config_path = default_config_dir() / APP_CONFIG
    threading.Thread(target=open_when_ready, args=(config_path,), daemon=True).start()
    return main(["run"] if config_path.exists() else ["setup"])


if __name__ == "__main__":
    raise SystemExit(desktop_main())

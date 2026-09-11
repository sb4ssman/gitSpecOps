"""The browser skin's files, loaded by exact name.

Shared by every server that renders the fleet: the local dashboard (no Tailscale involved) and
the live tailnet listener. Only these named assets are ever served -- there is no directory
traversal and no source download, and that property must survive any future skin.
"""
from __future__ import annotations

import sys
from pathlib import Path

ASSETS = {
    "/": ("fleet_dashboard.html", "text/html; charset=utf-8"),
    "/assets/fleet_standard.css": ("fleet_standard.css", "text/css; charset=utf-8"),
    "/assets/fleet_client.js": ("fleet_client.js", "text/javascript; charset=utf-8"),
    "/assets/fleet_view.js": ("fleet_view.js", "text/javascript; charset=utf-8"),
    "/assets/fleet_standard.js": ("fleet_standard.js", "text/javascript; charset=utf-8"),
}


def ui_dir() -> Path:
    """In a frozen bundle the assets sit beside the executable; from source they are in ui/."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent / "ui"


def load_ui_assets() -> dict:
    root = ui_dir()
    return {url: ((root / name).read_bytes(), mime) for url, (name, mime) in ASSETS.items()}

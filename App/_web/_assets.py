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
    "/assets/fleet_map.js": ("fleet_map.js", "text/javascript; charset=utf-8"),
    "/setup": ("fleet_setup.html", "text/html; charset=utf-8"),
    "/assets/fleet_setup.js": ("fleet_setup.js", "text/javascript; charset=utf-8"),
}


def ui_dirs(skin: str = "standard") -> tuple[Path, ...]:
    """Where a skin's files are: the skin's own folder first, then the files every skin shares.

    In a frozen bundle the assets sit flat beside the executable."""
    if getattr(sys, "frozen", False):
        return (Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)),)
    skins = Path(__file__).resolve().parent / "skins"
    return (skins / skin, skins / "_common")


def _find(name: str, folders: tuple[Path, ...]) -> Path:
    for folder in folders:
        if (folder / name).is_file():
            return folder / name
    raise FileNotFoundError(f"skin asset not found: {name}")


def load_ui_assets(skin: str = "standard") -> dict:
    folders = ui_dirs(skin)
    return {url: (_find(name, folders).read_bytes(), mime) for url, (name, mime) in ASSETS.items()}

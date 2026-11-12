"""PyInstaller recipe for the desktop app; run from the repository root on the target OS.

    python -m PyInstaller --noconfirm --clean _build/GitSpecOpsSync.spec
"""
from pathlib import Path

build_dir = Path(SPECPATH).resolve()
project_root = build_dir.parent  # this spec lives in _build/
skins = project_root / "App" / "_web" / "skins"
assets = ([skins / "standard" / name for name in (
              "fleet_dashboard.html", "fleet_standard.css", "fleet_standard.js", "fleet_map.js", "fleet_zoom.js",
              "fleet_setup.html", "fleet_setup.js")]
          + [skins / "_common" / name for name in ("fleet_client.js", "fleet_view.js")])

analysis = Analysis(
    [str(project_root / "App" / "desktop.py")],
    # The layers import from the repository root, exactly as when run from source.
    pathex=[str(project_root)],
    binaries=[],
    # Skin files sit flat beside the executable; pyproject.toml carries the version number
    # (Basic/_version.py reads it at run time).
    datas=[(str(path), ".") for path in assets] + [(str(project_root / "pyproject.toml"), ".")],
    # Imported lazily, inside functions: static analysis would miss them, and the frozen app
    # would fail only when a person reaches them (a menu item, recovery). Name them.
    hiddenimports=["App._tray.qt", "App._tray.model", "App._launch", "App._web.server",
                   "App._web.remote", "App._web._assets", "App._web.setup",
                   "App._mark.geometry", "App._mark.svg", "App._mark.qt",
                   "Elaborate._fleet.setup_state", "Elaborate._fleet.autostart",
                   "Elaborate._fleet.peer", "Elaborate._fleet.local_view", "Special._sync.actions",
                   "Elaborate._recovery.runtime", "Elaborate._recovery.capture",
                   "Elaborate._recovery.secret_scan", "Elaborate._recovery.patch_parse",
                   "Elaborate._recovery.snapshot_store", "Elaborate._recovery.snapshot_preview",
                   "Elaborate._recovery.snapshot_restore", "Elaborate._recovery.retirement",
                   "Special._sync.vscode_buffers", "Basic._console", "Basic._version"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="GitSpecOpsSync",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    name="GitSpecOpsSync",
)

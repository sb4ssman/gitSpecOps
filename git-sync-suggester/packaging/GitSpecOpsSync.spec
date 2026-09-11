"""PyInstaller recipe; run from the repository root on the target operating system."""
from pathlib import Path

tool = Path(SPECPATH).resolve().parent  # this spec lives in git-sync-suggester/packaging/
root = tool.parent
assets = [
    "fleet_dashboard.html", "fleet_standard.css", "fleet_client.js",
    "fleet_view.js", "fleet_standard.js",
]
# The modules are flat scripts split across folders for legibility, so every code folder has
# to be on the analysis path -- the same set _paths.bootstrap() adds at runtime.
code_dirs = [str(tool / name) for name in ("core", "fleet", "app")]

analysis = Analysis(
    [str(tool / "app" / "fleet_desktop.py")],
    pathex=[str(tool), str(root), *code_dirs],
    binaries=[],
    datas=[(str(tool / "ui" / name), ".") for name in assets],
    # The tray and start-at-login shells are imported lazily, inside functions, so static
    # analysis never sees them and the frozen build would fail only at the moment a user
    # clicks the tray menu. Name them explicitly.
    hiddenimports=["fleet_tray", "fleet_autostart", "shared.console"],
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

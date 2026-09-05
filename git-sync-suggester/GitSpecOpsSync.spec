"""PyInstaller recipe; run from the repository root on the target operating system."""
from pathlib import Path

tool = Path(SPECPATH).resolve()
root = tool.parent
assets = [
    "fleet_dashboard.html", "fleet_standard.css", "fleet_client.js",
    "fleet_view.js", "fleet_standard.js",
]

analysis = Analysis(
    [str(tool / "fleet_desktop.py")],
    pathex=[str(tool), str(root)],
    binaries=[],
    datas=[(str(tool / name), ".") for name in assets],
    hiddenimports=[],
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

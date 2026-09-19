"""PyInstaller recipe; run from the repository root on the target operating system."""
from pathlib import Path

packaging_dir = Path(SPECPATH).resolve()
root = packaging_dir.parent  # this spec lives in git-sync-suggester/packaging/
project_root = root.parent
assets = [
    "fleet_dashboard.html", "fleet_standard.css", "fleet_client.js",
    "fleet_view.js", "fleet_standard.js",
]
# The modules are flat scripts split across folders for legibility, so every code folder has
# to be on the analysis path -- the same set _paths.bootstrap() adds at runtime.
code_dirs = [str(root / name) for name in ("core", "fleet", "app")]

analysis = Analysis(
    [str(root / "app" / "fleet_desktop.py")],
    # `shared/` belongs to the repository root, while the flat fleet modules live below
    # git-sync-suggester.  Keep both; an old `tool` variable here was undefined at build time.
    pathex=[str(project_root), str(root), *code_dirs],
    binaries=[],
    datas=[(str(root / "ui" / name), ".") for name in assets],
    # The tray and start-at-login shells are imported lazily, inside functions, so static
    # analysis never sees them and the frozen build would fail only at the moment a user
    # clicks the tray menu. Name them explicitly.
    hiddenimports=["fleet_tray", "fleet_autostart", "fleet_peer", "local_dashboard",
                   "local_view", "ui_assets", "fleet_actions", "recovery_runtime",
                   "capture", "secret_scan", "patch_parse", "snapshot_store",
                   "snapshot_preview", "snapshot_restore", "retirement", "vscode_buffers",
                   "shared.console", "shared.version"],
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

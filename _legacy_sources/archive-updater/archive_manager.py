"""
Archive Updater Manager
=======================

Install and track per-archive launchers that call the centralized
`archive_updater.py` script from this PythonTools checkout.

Run with no arguments on Windows to choose an archive folder with a dialog:

    python archive_manager.py

Command-line usage:

    python archive_manager.py --install T:\\Github\\Archive
    python archive_manager.py --list
    python archive_manager.py --status
    python archive_manager.py --forget T:\\Github\\Archive
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from archive_updater import DEFAULT_APPROVED_REMOTE_PREFIXES, approved_remote, is_repo_root, scan_root


APP_NAME = "Archive Updater Manager"
VERSION = "0.1.0"
REGISTRY_PATH = Path(__file__).with_name("archive_updater_registry.json")
POWERSHELL_LAUNCHER_NAME = "update_archive.ps1"
BAT_LAUNCHER_NAME = "update_archive.bat"
DEFAULT_REPORT_DIR = r"ArchAgent\_claude_notes\_claude_outputs\archive_updates"


@dataclass
class InstallRecord:
    root: str
    installed_at: str
    updated_at: str
    python_tools_dir: str
    python_executable: str
    updater_path: str
    powershell_launcher: str
    bat_launcher: str
    repo_count: int
    approved_remote_prefixes: list[str]


def now_stamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def validate_archive_root(root: Path, approved_prefixes: list[str]) -> tuple[Path, list[str]]:
    resolved = root.resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError(f"target folder is not a directory: {resolved}")
    if (resolved / ".git").exists() or is_repo_root(resolved):
        raise ValueError(f"target folder is itself a Git repository: {resolved}")

    report = scan_root(resolved, approved_prefixes)
    suitable = [
        repo.name
        for repo in report.repos
        if repo.is_work_tree and repo.origin_present and approved_remote(repo.origin, approved_prefixes)
    ]
    if not suitable:
        raise ValueError(
            "target folder must contain at least one direct child Git repository "
            "with an approved origin remote"
        )
    return resolved, suitable


def quote_ps(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def launcher_ps1(root: Path, updater_path: Path, python_executable: Path, approved_prefixes: list[str]) -> str:
    prefix_lines = "\n".join(f"    {quote_ps(prefix)}" for prefix in approved_prefixes)
    return f"""param(
    [switch]$ScanOnly,
    [switch]$ShowRemoteUrls,
    [switch]$NoReport
)

$python = {quote_ps(python_executable)}
$tool = {quote_ps(updater_path)}
$root = {quote_ps(root)}
$outputDir = Join-Path $root {quote_ps(DEFAULT_REPORT_DIR)}
$approvedPrefixes = @(
{prefix_lines}
)

$pyArgs = @(
    $tool,
    "--root", $root,
    "--output-dir", $outputDir
)

foreach ($prefix in $approvedPrefixes) {{
    $pyArgs += @("--approved-remote-prefix", $prefix)
}}

if ($ScanOnly) {{
    $pyArgs += "--scan-only"
}}

if ($ShowRemoteUrls) {{
    $pyArgs += "--show-remote-urls"
}}

if ($NoReport) {{
    $pyArgs += "--no-report"
}}

if (Test-Path $python) {{
    & $python @pyArgs
}} else {{
    python @pyArgs
}}
exit $LASTEXITCODE
"""


def launcher_bat() -> str:
    return """@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_archive.ps1" %*
exit /b %ERRORLEVEL%
"""


def load_registry() -> dict[str, dict]:
    if not REGISTRY_PATH.exists():
        return {"version": 1, "installations": []}
    with REGISTRY_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    data.setdefault("version", 1)
    data.setdefault("installations", [])
    return data


def save_registry(data: dict[str, object]) -> None:
    with REGISTRY_PATH.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


def upsert_record(record: InstallRecord) -> None:
    data = load_registry()
    installations = data["installations"]
    assert isinstance(installations, list)

    existing = None
    for index, item in enumerate(installations):
        if Path(item["root"]).resolve() == Path(record.root).resolve():
            existing = index
            break

    payload = asdict(record)
    if existing is None:
        installations.append(payload)
    else:
        payload["installed_at"] = installations[existing].get("installed_at", record.installed_at)
        installations[existing] = payload
    save_registry(data)


def install_launchers(root: Path, approved_prefixes: list[str]) -> InstallRecord:
    resolved, repos = validate_archive_root(root, approved_prefixes)
    updater_path = Path(__file__).with_name("archive_updater.py").resolve()
    python_executable = Path(sys.executable).resolve()
    ps1_path = resolved / POWERSHELL_LAUNCHER_NAME
    bat_path = resolved / BAT_LAUNCHER_NAME

    ps1_path.write_text(launcher_ps1(resolved, updater_path, python_executable, approved_prefixes), encoding="utf-8")
    bat_path.write_text(launcher_bat(), encoding="utf-8")

    stamp = now_stamp()
    record = InstallRecord(
        root=str(resolved),
        installed_at=stamp,
        updated_at=stamp,
        python_tools_dir=str(Path(__file__).resolve().parents[1]),
        python_executable=str(python_executable),
        updater_path=str(updater_path),
        powershell_launcher=str(ps1_path),
        bat_launcher=str(bat_path),
        repo_count=len(repos),
        approved_remote_prefixes=approved_prefixes,
    )
    upsert_record(record)
    return record


def forget_installation(root: Path) -> bool:
    data = load_registry()
    installations = data["installations"]
    assert isinstance(installations, list)
    resolved = root.resolve()
    kept = [item for item in installations if Path(item["root"]).resolve() != resolved]
    if len(kept) == len(installations):
        return False
    data["installations"] = kept
    save_registry(data)
    return True


def installation_status(item: dict) -> dict[str, object]:
    root = Path(item["root"])
    ps1 = Path(item["powershell_launcher"])
    bat = Path(item["bat_launcher"])
    return {
        "root": str(root),
        "root_exists": root.exists() and root.is_dir(),
        "powershell_launcher_exists": ps1.exists(),
        "bat_launcher_exists": bat.exists(),
        "repo_count_at_install": item.get("repo_count", 0),
        "installed_at": item.get("installed_at"),
        "updated_at": item.get("updated_at"),
    }


def print_registry(show_status: bool) -> None:
    data = load_registry()
    installations = data["installations"]
    assert isinstance(installations, list)
    print(f"{APP_NAME} v{VERSION}")
    print(f"Registry: {REGISTRY_PATH}")
    print(f"Installations: {len(installations)}")
    for item in installations:
        details = installation_status(item) if show_status else item
        print()
        print(f"Root: {details['root']}")
        print(f"  installed: {details.get('installed_at', 'unknown')}")
        print(f"  updated: {details.get('updated_at', 'unknown')}")
        if show_status:
            print(f"  root exists: {'yes' if details['root_exists'] else 'no'}")
            print(f"  ps1 exists: {'yes' if details['powershell_launcher_exists'] else 'no'}")
            print(f"  bat exists: {'yes' if details['bat_launcher_exists'] else 'no'}")
            print(f"  repos at install: {details['repo_count_at_install']}")
        else:
            print(f"  ps1: {details['powershell_launcher']}")
            print(f"  bat: {details['bat_launcher']}")
            print(f"  repos at install: {details['repo_count']}")


def choose_folder_dialog() -> Path | None:
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.withdraw()
    folder = filedialog.askdirectory(title="Choose archive folder to manage")
    if not folder:
        root.destroy()
        return None

    target = Path(folder)
    try:
        resolved, repos = validate_archive_root(target, DEFAULT_APPROVED_REMOTE_PREFIXES)
    except ValueError as exc:
        messagebox.showerror(APP_NAME, str(exc))
        root.destroy()
        return None

    confirmed = messagebox.askyesno(
        APP_NAME,
        "Create archive update launchers here?\n\n"
        f"{resolved}\n\n"
        f"Found {len(repos)} suitable repo(s).",
    )
    root.destroy()
    return resolved if confirmed else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install and track ArchiveUpdater launchers.")
    parser.add_argument("--install", type=Path, help="Archive folder where launchers should be created.")
    parser.add_argument("--list", action="store_true", help="List registered launcher installations.")
    parser.add_argument("--status", action="store_true", help="List installations and verify paths still exist.")
    parser.add_argument("--forget", type=Path, help="Remove one archive folder from the registry.")
    parser.add_argument(
        "--approved-remote-prefix",
        action="append",
        help="Allowed origin prefix. May be passed more than once. Defaults to https://github.com/.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    approved_prefixes = args.approved_remote_prefix or DEFAULT_APPROVED_REMOTE_PREFIXES

    try:
        if args.list or args.status:
            print_registry(show_status=args.status)
            return 0

        if args.forget:
            removed = forget_installation(args.forget)
            print("Removed from registry." if removed else "No matching registry entry found.")
            return 0 if removed else 1

        target = args.install or choose_folder_dialog()
        if not target:
            print("No archive folder selected.")
            return 1

        record = install_launchers(target, approved_prefixes)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Error writing launcher or registry: {exc}", file=sys.stderr)
        return 3

    print(f"Installed archive launchers for {record.root}")
    print(f"  PowerShell: {record.powershell_launcher}")
    print(f"  Batch: {record.bat_launcher}")
    print(f"  Registry: {REGISTRY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

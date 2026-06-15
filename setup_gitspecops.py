"""Create or refresh local gitSpecOps launcher scripts.

Run from this repository:

    uv run python setup_gitspecops.py

The generated scripts are intentionally small: one launcher per tool action,
using the script type for the current OS.
"""

from __future__ import annotations

import platform
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ARCHIVE_DIR = ROOT / "gitArchiveUpdater"
GITHUB_DIR = ROOT / "github-org-duplicator"


WINDOWS = platform.system().lower() == "windows"


def write_text(path: Path, text: str, newline: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline=newline)
    print(f"wrote {path.relative_to(ROOT)}")


def bat_launcher(command: str, error_label: str) -> str:
    return """@echo off
setlocal
cd /d "%~dp0.."
uv run python COMMAND %*
if errorlevel 1 (
    echo.
    echo ERROR_LABEL exited with an error.
    pause
)
""".replace("COMMAND", command).replace("ERROR_LABEL", error_label)


def archive_updater_bat() -> str:
    return """@echo off
setlocal
cd /d "%~dp0.."
if "%~1"=="" (
    uv run python gitArchiveUpdater\\archive_updater.py --help
) else (
    uv run python gitArchiveUpdater\\archive_updater.py %*
)
if errorlevel 1 (
    echo.
    echo Archive updater exited with an error.
    pause
)
"""


def shell_launcher(command: str) -> str:
    return f"""#!/usr/bin/env sh
set -eu
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"
exec uv run python {command} "$@"
"""


def main(argv: list[str] | None = None) -> int:
    _ = argv
    if WINDOWS:
        write_text(ARCHIVE_DIR / "update-archive.bat", archive_updater_bat(), "\r\n")
        write_text(ARCHIVE_DIR / "manage-archives.bat", bat_launcher("gitArchiveUpdater\\archive_manager.py", "Archive manager"), "\r\n")
        write_text(GITHUB_DIR / "duplicate-github-org.bat", bat_launcher("github-org-duplicator\\github_org_duplicator.py", "GitHub org duplicator"), "\r\n")
    else:
        write_text(ARCHIVE_DIR / "update-archive.sh", shell_launcher("gitArchiveUpdater/archive_updater.py"), "\n")
        write_text(ARCHIVE_DIR / "manage-archives.sh", shell_launcher("gitArchiveUpdater/archive_manager.py"), "\n")
        write_text(GITHUB_DIR / "duplicate-github-org.sh", shell_launcher("github-org-duplicator/github_org_duplicator.py"), "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

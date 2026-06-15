@echo off
setlocal
cd /d "%~dp0.."
if "%~1"=="" (
    uv run python gitArchiveUpdater\archive_updater.py --help
) else (
    uv run python gitArchiveUpdater\archive_updater.py %*
)
if errorlevel 1 (
    echo.
    echo Archive updater exited with an error.
    pause
)

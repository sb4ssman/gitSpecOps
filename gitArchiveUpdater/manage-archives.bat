@echo off
setlocal
cd /d "%~dp0.."
uv run python gitArchiveUpdater\archive_manager.py %*
if errorlevel 1 (
    echo.
    echo Archive manager exited with an error.
    pause
)

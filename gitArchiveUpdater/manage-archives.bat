@echo off
rem Shim: hand off to the .ps1 so double-click works and the real logic lives in
rem one place. The .ps1 prefers the repo's .venv and falls back to `uv run`.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0manage-archives.ps1" %*
if errorlevel 1 (
    echo.
    echo Archive manager exited with an error.
    pause
)

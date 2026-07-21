@echo off
rem Shim: hand off to the .ps1 so double-click works and the real logic lives in
rem one place. The .ps1 prefers the repo's .venv and falls back to `uv run`.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0duplicate-github-org.ps1" %*
if errorlevel 1 (
    echo.
    echo GitHub org duplicator exited with an error.
    pause
)

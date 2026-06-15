@echo off
setlocal
cd /d "%~dp0.."
uv run python github-org-duplicator\github_org_duplicator.py %*
if errorlevel 1 (
    echo.
    echo GitHub org duplicator exited with an error.
    pause
)

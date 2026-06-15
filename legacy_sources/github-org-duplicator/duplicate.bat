@echo off
REM Simple launcher for GitHub Organization Duplicator
REM Just runs the Python script - all checks are handled by the script itself

python github_org_duplicator.py

if errorlevel 1 (
    echo.
    echo Script exited with an error.
    pause
)

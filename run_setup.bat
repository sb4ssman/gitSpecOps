@echo off
setlocal
cd /d "%~dp0"
uv run python setup_gitspecops.py %*
if errorlevel 1 (
    echo.
    echo setup_gitspecops.py exited with an error.
    pause
)

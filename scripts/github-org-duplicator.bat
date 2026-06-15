@echo off
python -m git_spec_ops.github_org_duplicator %*
if errorlevel 1 (
    echo.
    echo Script exited with an error.
    pause
)

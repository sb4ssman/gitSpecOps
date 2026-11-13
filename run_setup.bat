@echo off
rem Shim: keep double-click working from Explorer by handing off to the .ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_setup.ps1" %*
rem A failure keeps the window open (a double-clicked window would otherwise close at once).
if errorlevel 1 (
    echo.
    pause
)
exit /b %errorlevel%

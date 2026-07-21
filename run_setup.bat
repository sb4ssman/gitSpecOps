@echo off
rem Shim: keep double-click working from Explorer by handing off to the .ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_setup.ps1" %*

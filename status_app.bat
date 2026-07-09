@echo off
REM Vercillo Analytics — double-click to see whether the app is up.
title Vercillo Analytics - Status
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\app_control.ps1" -Action status
echo.
pause

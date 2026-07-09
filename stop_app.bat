@echo off
REM Vercillo Analytics — double-click to stop the app (webapp + worker).
REM Leaves the cloudflared tunnel service running (it auto-recovers on boot).
title Vercillo Analytics - Stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\app_control.ps1" -Action stop
echo.
pause

@echo off
REM Vercillo Analytics — double-click to start the app (webapp + worker).
REM Safe to run twice: it won't launch a second copy of a running service.
title Vercillo Analytics - Start
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\app_control.ps1" -Action start
echo.
pause

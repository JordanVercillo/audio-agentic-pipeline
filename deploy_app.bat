@echo off
REM Vercillo Analytics - double-click to DEPLOY: pull, sync deps, restart, verify.
REM Use this after committing a change. The app runs uvicorn with reload=False,
REM so a running site never picks up new code on its own - status_app.bat will
REM say "Code STALE" when that has happened.
title Vercillo Analytics - Deploy
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\app_control.ps1" -Action deploy
echo.
pause

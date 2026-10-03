@echo off
title AgentGymnasium
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
if errorlevel 1 (
  echo.
  echo AgentGymnasium did not start. Review the error above.
  pause
)

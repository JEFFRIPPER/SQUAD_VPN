@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" exit /b 1
if not exist "tools\mihomo\mihomo.exe" (
  ".venv\Scripts\python.exe" -m squad_vpn setup-mihomo
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m squad_vpn run
exit /b %errorlevel%

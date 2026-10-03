@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\pythonw.exe" (
  echo [SQUAD VPN] Not installed yet: run install.cmd in the project folder.
  pause
  exit /b 1
)
rem The agent is single-instance: this is a no-op when it already runs.
start "" ".venv\Scripts\pythonw.exe" -m squad_vpn agent
timeout /t 5 /nobreak >nul
if exist "SQUAD VPN.exe" (
  start "" "SQUAD VPN.exe"
) else (
  start "" http://127.0.0.1:8080/app
)

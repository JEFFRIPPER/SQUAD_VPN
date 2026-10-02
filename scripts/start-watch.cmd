@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo [SQUAD VPN] .venv not found. Run installation first.
  exit /b 1
)
if not exist "tools\mihomo\mihomo.exe" (
  echo [SQUAD VPN] Installing Mihomo...
  ".venv\Scripts\python.exe" -m squad_vpn setup-mihomo
  if errorlevel 1 exit /b 1
)
echo [SQUAD VPN] Starting hourly watch mode...
".venv\Scripts\python.exe" -m squad_vpn watch --interval-minutes 60

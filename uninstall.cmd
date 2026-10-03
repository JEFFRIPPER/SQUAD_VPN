@echo off
setlocal
cd /d "%~dp0"
echo Stopping SQUAD VPN and removing autostart...
".venv\Scripts\python.exe" -m squad_vpn agent --stop
".venv\Scripts\python.exe" -m squad_vpn autostart --disable
schtasks /Delete /TN "SQUAD_VPN_HOURLY" /F >nul 2>nul
echo Done. Project files and the database are kept.
pause

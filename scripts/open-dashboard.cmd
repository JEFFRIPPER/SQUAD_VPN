@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo [SQUAD VPN] .venv not found. Run installation first.
  pause
  exit /b 1
)
echo [SQUAD VPN] Updating dependencies...
".venv\Scripts\python.exe" -m pip install -q -e .
if errorlevel 1 (
  pause
  exit /b 1
)
echo [SQUAD VPN] Dashboard: http://127.0.0.1:8080/
echo [SQUAD VPN] Keep this window open. Close it or press Ctrl+C to stop.
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8080/"
".venv\Scripts\python.exe" -m squad_vpn serve
pause

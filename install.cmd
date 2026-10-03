@echo off
setlocal
cd /d "%~dp0"
echo ============================================
echo   SQUAD VPN - one-time setup
echo ============================================
echo.

rem --- Git (needed for automatic updates) ---
where git >nul 2>nul
if errorlevel 1 (
  echo [1/6] Installing Git...
  winget install -e --id Git.Git --silent --accept-source-agreements --accept-package-agreements
) else (
  echo [1/6] Git found.
)

rem --- Python + virtual environment ---
if exist ".venv\Scripts\python.exe" (
  echo [2/6] Python environment found.
  goto deps
)
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo [2/6] Installing Python 3.12...
  winget install -e --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
)
if not defined PY (
  echo Python was not found. Install Python 3.11+ from https://www.python.org and run install.cmd again.
  pause
  exit /b 1
)
echo [2/6] Creating Python environment...
%PY% -m venv .venv
if errorlevel 1 (
  echo Failed to create .venv
  pause
  exit /b 1
)

:deps
echo [3/6] Installing dependencies...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -e .
if errorlevel 1 (
  echo Failed to install dependencies.
  pause
  exit /b 1
)

echo [4/6] Stopping old versions...
".venv\Scripts\python.exe" -m squad_vpn agent --stop >nul 2>nul
schtasks /Delete /TN "SQUAD_VPN_HOURLY" /F >nul 2>nul

echo [5/6] Enabling autostart and desktop shortcut...
".venv\Scripts\python.exe" -m squad_vpn autostart
if errorlevel 1 (
  pause
  exit /b 1
)

echo [6/6] Starting SQUAD VPN in the background...
start "" ".venv\Scripts\pythonw.exe" -m squad_vpn agent
timeout /t 8 /nobreak >nul
start "" http://127.0.0.1:8080/

echo.
echo Done. SQUAD VPN now runs in the background, starts with Windows,
echo refreshes nodes every hour and updates itself from GitHub.
echo Dashboard: "SQUAD VPN" shortcut on the desktop (http://127.0.0.1:8080/).
echo You can close this window.
pause

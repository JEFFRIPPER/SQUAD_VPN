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
  rem A fresh install is not on PATH in this window yet.
  set "PATH=%PATH%;%ProgramFiles%\Git\cmd"
) else (
  echo [1/6] Git found.
)

rem --- Python + virtual environment ---
if exist ".venv\Scripts\python.exe" (
  echo [2/6] Python environment found.
  goto deps
)
rem A real Python 3.11+ (the Microsoft Store "python" stub does not count).
set "PY="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set "PY=py -3"
if not defined PY (
  python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set "PY=python"
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

rem --- a copy downloaded as zip becomes a git checkout (for auto-update) ---
if not exist ".git" (
  where git >nul 2>nul && (
    git init -q
    git remote add origin https://github.com/JEFFRIPPER/SQUAD_VPN.git
    git fetch -q --depth 50 origin main
    git reset -q origin/main
    git branch -q -M main
  )
)

echo [4/6] Stopping old versions...
".venv\Scripts\python.exe" -m squad_vpn agent --stop >nul 2>nul
schtasks /Delete /TN "SQUAD_VPN_HOURLY" /F >nul 2>nul

echo [5/6] Downloading SQUAD VPN.exe and enabling autostart...
".venv\Scripts\python.exe" -m squad_vpn app-update
".venv\Scripts\python.exe" -m squad_vpn autostart
if errorlevel 1 (
  pause
  exit /b 1
)

echo [6/6] Starting SQUAD VPN in the background...
start "" ".venv\Scripts\pythonw.exe" -m squad_vpn agent
timeout /t 8 /nobreak >nul
rem When started from SQUAD VPN.exe, that window shows the panel itself.
if not defined SQUAD_FROM_APP (
  if exist "SQUAD VPN.exe" (
    start "" "SQUAD VPN.exe"
  ) else (
    start "" http://127.0.0.1:8080/app
  )
)

echo.
echo Done. SQUAD VPN now runs in the background, starts with Windows,
echo refreshes nodes every hour and updates itself from GitHub.
echo Control panel: "SQUAD VPN" on the desktop or SQUAD VPN.exe in this folder.
echo You can close this window.
pause

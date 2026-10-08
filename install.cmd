@echo off
setlocal
cd /d "%~dp0"
if not exist "data\logs" mkdir "data\logs"
set "LOG=data\logs\install.log"
>>"%LOG%" echo %date% %time% BEGIN
echo ============================================
echo   SQUAD VPN - one-time setup
echo ============================================
echo.

rem --- Git (only for automatic updates): never blocks the setup ---
call :step 1 git
where git >nul 2>nul
if errorlevel 1 (
  rem Installed in the background; the agent turns this copy into a git
  rem checkout once Git appears. Without Git everything else still works.
  where winget >nul 2>nul && start "SQUAD VPN - Git" /min winget install -e --id Git.Git --silent --accept-source-agreements --accept-package-agreements
  echo [1/6] Git will be installed in the background.
) else (
  echo [1/6] Git found.
)

rem --- Python + virtual environment ---
if exist ".venv\Scripts\python.exe" (
  echo [2/6] Python environment found.
  goto deps
)
call :step 2 python
rem A real Python 3.11+ (the Microsoft Store "python" stub does not count).
set "PY="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set "PY=py -3"
if not defined PY (
  python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set "PY=python"
)
set "USERPY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%USERPY%" set "PY="%USERPY%""
if not defined PY (
  rem For this user only: no administrator rights, no UAC prompt.
  echo [2/6] Installing Python 3.12 for this user...
  where winget >nul 2>nul && winget install -e --id Python.Python.3.12 --scope user --silent --disable-interactivity --accept-source-agreements --accept-package-agreements
  if exist "%USERPY%" set "PY="%USERPY%""
)
if not defined PY (
  rem No winget (or it failed): the official installer straight from python.org.
  echo [2/6] Downloading Python 3.12 from python.org...
  >>"%LOG%" echo %date% %time% python-direct
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -UseBasicParsing 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile ($env:TEMP + '\squad-python.exe')"
  if exist "%TEMP%\squad-python.exe" (
    "%TEMP%\squad-python.exe" /quiet InstallAllUsers=0 PrependPath=0 Include_test=0 Include_doc=0 Include_tcltk=0 Shortcuts=0
    del "%TEMP%\squad-python.exe" >nul 2>nul
  )
  if exist "%USERPY%" set "PY="%USERPY%""
)
if not defined PY (
  >>"%LOG%" echo %date% %time% FAIL python
  echo Python was not found. Install Python 3.11+ from https://www.python.org and run install.cmd again.
  pause
  exit /b 1
)
echo [2/6] Creating Python environment...
%PY% -m venv .venv
if errorlevel 1 (
  >>"%LOG%" echo %date% %time% FAIL venv
  echo Failed to create .venv
  pause
  exit /b 1
)

:deps
call :step 3 deps
echo [3/6] Installing dependencies...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check --prefer-binary -e .
if errorlevel 1 (
  >>"%LOG%" echo %date% %time% FAIL deps
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

call :step 4 stop
echo [4/6] Stopping old versions...
".venv\Scripts\python.exe" -m squad_vpn agent --stop >nul 2>nul
schtasks /Delete /TN "SQUAD_VPN_HOURLY" /F >nul 2>nul

call :step 5 autostart
rem Started from SQUAD VPN.exe: that exe is already here, no second download.
if defined SQUAD_FROM_APP if exist "SQUAD VPN.exe" goto autostart
echo [5/6] Downloading SQUAD VPN.exe...
".venv\Scripts\python.exe" -m squad_vpn app-update
:autostart
echo [5/6] Enabling autostart...
".venv\Scripts\python.exe" -m squad_vpn autostart
if errorlevel 1 (
  >>"%LOG%" echo %date% %time% FAIL autostart
  pause
  exit /b 1
)

call :step 6 agent
echo [6/6] Starting SQUAD VPN in the background...
start "" ".venv\Scripts\pythonw.exe" -m squad_vpn agent
>>"%LOG%" echo %date% %time% DONE
rem When started from SQUAD VPN.exe, that window shows the panel itself.
if not defined SQUAD_FROM_APP (
  timeout /t 8 /nobreak >nul
  if exist "SQUAD VPN.exe" (
    start "" "SQUAD VPN.exe"
  ) else (
    start "" http://127.0.0.1:8080/app
  )
  echo.
  echo Done. SQUAD VPN now runs in the background, starts with Windows,
  echo refreshes nodes every hour and updates itself from GitHub.
  echo Control panel: "SQUAD VPN" on the desktop or SQUAD VPN.exe in this folder.
  echo You can close this window.
  pause
)
exit /b 0

rem Progress marker for the SQUAD VPN.exe window: "STEP <n> <name>".
:step
>>"%LOG%" echo %date% %time% STEP %1 %2
exit /b 0

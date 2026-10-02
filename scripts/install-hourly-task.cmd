@echo off
setlocal
set "TASK_NAME=SQUAD_VPN_HOURLY"
set "RUNNER=%~dp0run-once.cmd"
schtasks /Create /SC HOURLY /MO 1 /TN "%TASK_NAME%" /TR "%RUNNER%" /F
if errorlevel 1 (
  echo Failed to create scheduled task.
  exit /b 1
)
echo Created task %TASK_NAME%: every 1 hour.

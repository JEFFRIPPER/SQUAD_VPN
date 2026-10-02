@echo off
setlocal
schtasks /Delete /TN "SQUAD_VPN_HOURLY" /F

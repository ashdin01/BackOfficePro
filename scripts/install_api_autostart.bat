@echo off
REM Run the BackOfficePro API at Windows login, whether or not the BackOfficePro
REM app is open (needed for the phone's Warehouse Order / PO receive / stocktake).
REM It serves the main store (Little Red Apple) database.
REM
REM Usage (once, from a normal Command Prompt, as the user who runs BackOfficePro):
REM   install_api_autostart.bat "C:\Path\To\BackOfficePro.exe"
REM Remove with:  schtasks /Delete /TN "BackOfficePro API" /F
REM After installing a new BackOfficePro version, log out/in (or reboot) so the
REM background API restarts on the new code.

if "%~1"=="" (
  echo Usage: %~nx0 "C:\Path\To\BackOfficePro.exe"
  exit /b 1
)
if not exist "%~1" (
  echo File not found: %~1
  exit /b 1
)
schtasks /Create /F /TN "BackOfficePro API" /SC ONLOGON /RL LIMITED /TR "\"%~1\" --api-server-mode"
if errorlevel 1 (
  echo Failed to create the scheduled task.
  exit /b 1
)
echo Created. Starting it now...
schtasks /Run /TN "BackOfficePro API"

@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1"
if errorlevel 1 (
  echo.
  echo Setup did not complete. Review the message above.
  pause
  exit /b 1
)
echo.
echo Setup completed successfully.
pause


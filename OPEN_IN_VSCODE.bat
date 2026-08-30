@echo off
setlocal
cd /d "%~dp0"
where code >nul 2>nul
if errorlevel 1 (
  echo VS Code's command-line launcher was not found.
  echo Open Visual Studio Code and choose File ^> Open Workspace from File,
  echo then select prince-cga-composite.code-workspace in this folder.
  pause
  exit /b 1
)
code "%~dp0prince-cga-composite.code-workspace"


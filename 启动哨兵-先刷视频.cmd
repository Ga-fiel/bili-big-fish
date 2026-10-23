@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
if not exist "%~dp0config.json" (
  echo config.json not found. Run the setup script first.
  pause
  exit /b 1
)
"%PY%" -B -u "%~dp0code\fish.py" --boot-scan
pause

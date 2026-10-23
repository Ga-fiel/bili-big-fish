@echo off
chcp 65001 >nul
setlocal
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
if not exist "%~dp0config.json" (
  echo config.json not found. Run the setup script first.
  pause
  exit /b 1
)
title DaFeiYu
echo.
echo  DaFeiYu sentinel - watch a video first, then listen.
echo  Close this window = stop the sentinel.
echo.
"%PY%" -B -u "%~dp0code\fish.py" --boot-scan
echo.
echo  sentinel stopped.
pause

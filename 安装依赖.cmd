@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem Default: Tsinghua mirror (fast in mainland China).
rem If the mirror is down, change the next line to: https://pypi.org/simple
set "PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple"

if not exist ".venv\Scripts\python.exe" (
  echo [1/2] Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo Python 3.10+ not found. Install it from python.org first.
    pause
    exit /b 1
  )
) else (
  echo [1/2] Virtual environment already exists.
)

echo [2/2] Installing requirements from %PIP_INDEX%
".venv\Scripts\python.exe" -m pip install --upgrade pip -i %PIP_INDEX%
".venv\Scripts\python.exe" -m pip install -r requirements.txt -i %PIP_INDEX%
if errorlevel 1 (
  echo.
  echo Install failed. Try the official index instead:
  echo   .venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.org/simple
  pause
  exit /b 1
)
echo.
echo Done. Next: double-click the setup script.
pause

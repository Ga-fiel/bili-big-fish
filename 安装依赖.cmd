@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

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

echo [2/2] Installing requirements...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Install failed. If the network is slow, try the Tsinghua mirror:
  echo   .venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
  pause
  exit /b 1
)
echo.
echo Done. Next: double-click the setup script.
pause

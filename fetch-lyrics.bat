@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Run install.bat first.
    pause
    exit /b 1
)

chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo Downloading synced lyrics from LRCLIB...
echo.
".venv\Scripts\python.exe" -m visusic.fetch %*
echo.
pause

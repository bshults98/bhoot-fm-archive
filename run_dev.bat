@echo off
REM Dev server with hot reload. The actual uvicorn config lives in
REM run_dev.py — calling Python directly avoids shell-glob expansion
REM issues on Git Bash / MSYS / weird-Windows-terminal setups.
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
    echo Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat

REM Make sure watchfiles is available so the include/exclude lists
REM actually work (otherwise uvicorn falls back to a stat-walker that
REM scans the 11 GB audio tree).
python -c "import watchfiles" 2>nul
if errorlevel 1 (
    echo Installing watchfiles ...
    pip install watchfiles
)

python run_dev.py

echo.
echo Server stopped.
pause

@echo off
REM Production-like local server (no reload, no directory watching).
REM For development with hot reload, use run_dev.bat.
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
    echo Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
echo Starting BhootFM Archive on http://127.0.0.1:8000 ...
echo Press Ctrl+C to stop.
python -m uvicorn server:app --host 127.0.0.1 --port 8000

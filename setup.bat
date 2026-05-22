@echo off
cd /d "%~dp0"
echo Creating venv...
python -m venv .venv
call .venv\Scripts\activate.bat
echo Installing dependencies...
pip install -r requirements.txt
echo.
echo Next step: ingest your transcripts:
echo   python ingest.py "C:\path\to\folder-of-docx-files"
echo Then start the server:
echo   run.bat
pause

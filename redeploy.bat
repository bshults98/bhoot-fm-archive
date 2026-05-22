@echo off
REM One-button redeploy. Run this from "BhootFM Archive\" after any new
REM transcripts land in transcripts/.
REM
REM Prerequisites (one time, see DEPLOY.md):
REM   1. flyctl installed and on PATH
REM   2. `fly auth login` done
REM   3. `fly launch --no-deploy` done (creates app)

cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo Virtual environment not found. Run setup.bat first.
    pause & exit /b 1
)
call .venv\Scripts\activate.bat

echo === [1/3] Re-ingesting transcripts into archive.db ===
python ingest.py
if errorlevel 1 ( echo Ingest failed. & pause & exit /b 1 )

echo.
echo === [2/3] Stripping local paths -> archive.prod.db ===
python prepare_production_db.py
if errorlevel 1 ( echo Prep failed. & pause & exit /b 1 )

echo.
echo === [3/3] Deploying to Fly.io ===
where flyctl >nul 2>nul
if errorlevel 1 (
    echo flyctl not installed. See DEPLOY.md.
    pause & exit /b 1
)
fly deploy
if errorlevel 1 ( echo Deploy failed. & pause & exit /b 1 )

echo.
echo === Done. App URL: ===
fly status --json 2>nul | python -c "import sys,json; d=json.load(sys.stdin); print('https://' + d.get('Hostname', d.get('Name','?') + '.fly.dev'))"
echo.
pause

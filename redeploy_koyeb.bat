@echo off
REM ── Bhoot FM Archive — Koyeb redeploy ─────────────────────────────
REM Run this any time you want to push a new version live:
REM   - new transcripts ingested
REM   - code changes
REM   - new IA uploads (so mp3_url links update)
REM
REM Koyeb auto-rebuilds and redeploys when you push to GitHub.
REM This script just makes sure the prod DB is fresh before you push.

echo [1/3] Ingesting latest transcripts into dev DB...
python ingest.py
if errorlevel 1 ( echo ERROR: ingest.py failed & pause & exit /b 1 )

echo [2/3] Building production DB (strips local paths, rewrites IA URLs)...
python prepare_production_db.py
if errorlevel 1 ( echo ERROR: prepare_production_db.py failed & pause & exit /b 1 )

echo [3/3] Pushing to GitHub (Koyeb will auto-redeploy)...
git add archive.prod.db
git add -A
git commit -m "redeploy: refresh prod DB"
git push
if errorlevel 1 ( echo ERROR: git push failed & pause & exit /b 1 )

echo.
echo Done! Koyeb is rebuilding the image now.
echo Watch progress at: https://app.koyeb.com
pause

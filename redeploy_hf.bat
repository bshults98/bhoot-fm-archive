@echo off
REM ── Bhoot FM Archive — Hugging Face Spaces redeploy ───────────────
REM Run this any time you want to push a new version live.
REM Hugging Face auto-rebuilds and redeploys on every push.

echo [1/3] Ingesting latest transcripts into dev DB...
python ingest.py
if errorlevel 1 ( echo ERROR: ingest.py failed & pause & exit /b 1 )

echo [2/3] Building production DB (strips local paths, rewrites IA URLs)...
python prepare_production_db.py
if errorlevel 1 ( echo ERROR: prepare_production_db.py failed & pause & exit /b 1 )

echo [3/3] Pushing to GitHub + Hugging Face (auto-redeploy will start)...
git add archive.prod.db
git add -A
git commit -m "redeploy: refresh prod DB"

git push origin main --force
if errorlevel 1 ( echo ERROR: git push to GitHub failed & pause & exit /b 1 )

git checkout --orphan hf-deploy
git add -A
git commit -q -m "deploy"
git push hf hf-deploy:main --force
if errorlevel 1 (
  git checkout main
  git branch -D hf-deploy 2>nul
  echo ERROR: git push to Hugging Face failed & pause & exit /b 1
)
git checkout main
git branch -D hf-deploy 2>nul

echo.
echo Done! Hugging Face is rebuilding the image now.
echo Watch progress at: https://huggingface.co/spaces/xer2ten/bhoot-fm-archive
pause

@echo off
setlocal
REM ── Bhoot FM Archive — Hugging Face Spaces redeploy ───────────────
REM Pushes code to GitHub (normal history) and to Hugging Face as a
REM single-commit orphan branch so HF's LFS storage never accumulates
REM old versions of archive.prod.db (keeps us under the 1 GB limit).

cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" call .venv\Scripts\activate.bat

echo [1/4] Ingesting latest transcripts into dev DB...
python ingest.py
if errorlevel 1 ( echo ERROR: ingest.py failed & pause & exit /b 1 )

echo [2/4] Building production DB (strips local paths, rewrites IA URLs)...
python prepare_production_db.py
if errorlevel 1 ( echo ERROR: prepare_production_db.py failed & pause & exit /b 1 )

echo [3/4] Committing + pushing to GitHub...
git add archive.prod.db
git add -A
REM Commit may be empty if nothing changed -- that's fine, keep going.
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "redeploy: refresh prod DB"
    if errorlevel 1 ( echo ERROR: git commit failed & pause & exit /b 1 )
) else (
    echo    (no changes to commit -- pushing existing HEAD)
)

git push origin main
if errorlevel 1 ( echo ERROR: git push to GitHub failed & pause & exit /b 1 )

echo [4/4] Pushing fresh orphan snapshot to Hugging Face (resets LFS history)...
REM Clean up any leftover orphan branch from a previously failed run.
git show-ref --verify --quiet refs/heads/hf-deploy
if not errorlevel 1 git branch -D hf-deploy >nul 2>nul

git checkout --orphan hf-deploy
if errorlevel 1 ( echo ERROR: could not create orphan branch & pause & exit /b 1 )

git add -A
git commit -q -m "deploy"
if errorlevel 1 (
    echo ERROR: orphan commit failed
    git checkout -f main
    git branch -D hf-deploy >nul 2>nul
    pause & exit /b 1
)

git push hf hf-deploy:main --force
set HF_PUSH_ERR=%errorlevel%

REM Always return to main and clean up the orphan branch, success or not.
git checkout -f main
git branch -D hf-deploy >nul 2>nul

if not "%HF_PUSH_ERR%"=="0" (
    echo ERROR: git push to Hugging Face failed
    pause & exit /b 1
)

echo.
echo Done! Hugging Face is rebuilding the image now.
echo Watch progress at: https://huggingface.co/spaces/xer2ten/bhoot-fm-archive
pause
endlocal

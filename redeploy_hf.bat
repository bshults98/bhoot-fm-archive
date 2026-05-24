@echo off
setlocal
REM ── Bhoot FM Archive — Hugging Face Spaces redeploy ───────────────
REM
REM Production DB strategy (since the Space LFS-bloat incident):
REM   - archive.prod.db is built locally by prepare_production_db.py
REM   - then uploaded to a companion HF Dataset repo (one source of truth)
REM   - then the Space's Dockerfile urlretrieve's it at image build time
REM
REM The Space repo itself NEVER carries the DB, so its LFS bucket stays
REM at ~0 MB forever. The Dataset has a much more generous storage quota
REM and we can prune old revisions there via the HF UI if it ever grows.
REM
REM One-time setup on a fresh machine:
REM   1. pip install -r requirements.txt   (huggingface_hub now in there)
REM   2. huggingface-cli login              (token with WRITE access)
REM   3. Run this script — it'll create the dataset on first push

cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" call .venv\Scripts\activate.bat

echo [1/5] Ingesting latest transcripts into dev DB...
python ingest.py
if errorlevel 1 ( echo ERROR: ingest.py failed & pause & exit /b 1 )

echo [2/5] Building production DB (strips local paths, rewrites IA URLs)...
python prepare_production_db.py
if errorlevel 1 ( echo ERROR: prepare_production_db.py failed & pause & exit /b 1 )

echo [3/5] Uploading prod DB to companion HF Dataset...
python scripts\upload_db_to_dataset.py
if errorlevel 1 ( echo ERROR: upload_db_to_dataset.py failed & pause & exit /b 1 )

echo [4/5] Committing + pushing code to GitHub...
REM archive.prod.db is now .gitignored — it's never in the repo.
git add -A
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "redeploy"
    if errorlevel 1 ( echo ERROR: git commit failed & pause & exit /b 1 )
) else (
    echo    (no changes to commit -- pushing existing HEAD)
)

git push origin main
if errorlevel 1 ( echo ERROR: git push to GitHub failed & pause & exit /b 1 )

echo [5/5] Pushing fresh orphan snapshot to Hugging Face Space...
REM Orphan branch resets git history; no LFS objects involved anymore so
REM the bucket-bloat problem from the previous setup is gone for good.
git show-ref --verify --quiet refs/heads/hf-deploy
if not errorlevel 1 git branch -D hf-deploy >nul 2>nul

git checkout --orphan hf-deploy
if errorlevel 1 ( echo ERROR: could not create orphan branch & pause & exit /b 1 )

REM Bake a unique build-arg into the Dockerfile so the Space's Docker
REM layer cache re-runs the urlretrieve step and pulls the freshly
REM uploaded DB (otherwise the cached layer would keep the old one).
REM We use %DATE%-%TIME% which is always unique per deploy.
set DB_TAG=%DATE%-%TIME%
set DB_TAG=%DB_TAG: =0%
set DB_TAG=%DB_TAG:/=-%
set DB_TAG=%DB_TAG::=-%
set DB_TAG=%DB_TAG:.=-%
echo    cache-buster tag: %DB_TAG%

REM Patch the Dockerfile's default DATASET_DB_VERSION inline (orphan
REM branch only — the change never lands on `main`). Uses powershell so
REM we don't need sed/awk on Windows.
powershell -NoProfile -Command "(Get-Content Dockerfile -Raw) -replace 'ARG DATASET_DB_VERSION=latest', 'ARG DATASET_DB_VERSION=%DB_TAG%' | Set-Content -NoNewline Dockerfile"

git add -A
git commit -q -m "deploy %DB_TAG%"
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
echo It will pull the fresh DB from the Dataset during build.
echo Watch progress at: https://huggingface.co/spaces/xer2ten/bhoot-fm-archive
pause
endlocal

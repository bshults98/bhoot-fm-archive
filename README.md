---
title: Bhoot FM Archive
emoji: 👻
colorFrom: red
colorTo: gray
sdk: docker
app_port: 8080
pinned: false
---

# BhootFM Archive

Searchable web archive of Bhoot FM episodes. Indexes transcripts in SQLite
(FTS5) and serves the audio locally (with HTTP-Range seeking) from a
mirror of bhoot-fm.com.

## Current state

- **488 episode HTML pages** scouted (`scripts/episodes_index.py`)
- **487 mp3s downloaded** locally (~11 GB) under `audio/YYYY/`
- 1 mp3 (`2010-10-18`) is genuinely 404 on the source CDN — skipped
- DB seeded; transcripts populated as they're produced by the transcriber

## End-to-end workflow

```
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ downloader       │ -> │ batch transcriber│ -> │ archive ingest   │
│ (this repo)      │    │ (Transcriber)    │    │ (this repo)      │
└──────────────────┘    └──────────────────┘    └──────────────────┘
   mp3s in audio/         .json + .docx in       SQLite + FTS5
   + manifest.json        transcripts/           archive.db
```

## 1. Setup

```powershell
cd "C:\Users\User\Desktop\ETC\BhootFM Archive"
setup.bat
```

## 2. Download episodes

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/download_episodes.py                # everything
python scripts/download_episodes.py --year 2019    # one year
python scripts/download_episodes.py --date 2019-04-26  # one episode
python scripts/download_episodes.py --dry-run      # resolve URLs only
```

Resumable — re-runs skip files already downloaded successfully. Manifest at
`manifest.json` tracks status per episode (source URL, size, errors).

## 3. Transcribe (in the BhootFM Transcriber project)

```powershell
cd "..\BhootFM Transcriber"
.\.venv\Scripts\Activate.ps1
python batch_transcribe.py "..\BhootFM Archive\audio" --out "..\BhootFM Archive\transcripts"
```

Skips already-done files (checks for both `.docx` and `.json` sidecars).
Resumable, runs unattended overnight. ~5 min/episode × 487 = ~40 hours
total on RTX 3080 Ti with `tugstugi_bengaliai-asr_whisper-medium-ct2`.

You can cap a run with `--limit 20` to chip away in chunks.

## 4. Ingest into the archive DB

```powershell
cd "..\BhootFM Archive"
.\.venv\Scripts\Activate.ps1
python ingest.py
```

This:
- Registers all 488 episodes from `manifest.json` (with status `pending`)
- Loads every `.json` transcript from `transcripts/` (status flips to `done`)
- Links local audio paths so the server can stream with Range support

Idempotent — safe to re-run after every new batch of transcripts.

## 5. Start the server

```powershell
run.bat
```

Open <http://127.0.0.1:8000>. Tick "Transcribed only" to hide episodes
that haven't been transcribed yet.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | counts |
| GET | `/api/episodes?only_transcribed=true` | list episodes (filter) |
| GET | `/api/episode/{id}` | full segments |
| GET | `/api/episode/{id}/audio` | mp3 with HTTP Range — local or 302 to source |
| GET | `/api/search?q=...` | FTS search across segments |

`mp3_url` in responses is rewritten to `/api/episode/{id}/audio` when we
have the local file, so the frontend uses the local proxy automatically
(fast seeking, no dependency on dl.bhoot-fm.com being up at playtime).

## Files

| File | Purpose |
|---|---|
| `schema.sql` | episodes + segments + FTS5 (with `local_mp3_path`, `transcript_status`) |
| `ingest.py` | manifest + JSON transcripts → DB |
| `server.py` | FastAPI backend + static |
| `scripts/episodes_index.py` | hand-scouted episode index (488 entries) |
| `scripts/download_episodes.py` | the downloader |
| `static/index.html` etc. | frontend |
| `audio/YYYY/` | downloaded mp3s |
| `transcripts/` | drop `.json` (+ optional `.docx`) sidecars here |
| `manifest.json` | downloader state |
| `archive.db` | the SQLite database |

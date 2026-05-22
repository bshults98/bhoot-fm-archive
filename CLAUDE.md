# BhootFM Archive — context for Claude

## What this project is

A searchable web archive of **Bhoot FM** episodes (Bangladesh's iconic
late-night Bangla horror radio show on Radio Foorti 88.0 FM, hosted by
RJ Russell). Sibling project to `../BhootFM Transcriber/` which produces
the transcripts.

Public-facing site shows **only** episode metadata + clickable
timestamps. Transcript text is indexed for search but **never displayed
to the user** (deliberate UX choice + ethical hedge). User clicks a
timestamp → audio streams from Internet Archive (or dl.bhoot-fm.com as
fallback) starting at that exact moment.

## Tech stack

| Layer | Tech | Notes |
|---|---|---|
| Backend | FastAPI + SQLite + FTS5 | `unicode61` tokenizer handles Bangla |
| Frontend | Plain HTML + vanilla JS + CSS | No build step, no framework |
| Audio source | Internet Archive (primary) → dl.bhoot-fm.com (fallback) | Server `mp3_url` rewritten to IA URLs at deploy time |
| Deploy target | Fly.io free tier (Singapore) | Dockerfile + fly.toml ready, **not deployed yet** |

## File inventory

### Code
| File | Purpose |
|---|---|
| `server.py` | FastAPI app. Security headers (CSP, X-Frame-Options, etc.), CORS restricted via `BFA_PUBLIC_URL`, FTS5 search with allowlist sanitization, `/api/episode/{id}/audio` proxies local mp3 with HTTP Range support OR 302-redirects to source URL. **`/api/search` strips `snippet` server-side** so transcript text never reaches the client. |
| `ingest.py` | DB schema init + populates from `manifest.json` (registers episode metadata) and from `.json` transcript sidecars in `transcripts/`. **Date regex fixed** to require 2-digit forms (was matching `2010-08-13` as month 08 day 1). |
| `prepare_production_db.py` | Copies `archive.db` → `archive.prod.db`, strips `local_mp3_path`, **rewrites `mp3_url` from `ia_manifest.json`** to point at IA URLs, then VACUUMs. |
| `schema.sql` | episodes + segments + FTS5 + sync triggers. Includes `local_mp3_path`, `transcript_status` columns. |
| `scripts/episodes_index.py` | Hand-scouted list of all 488 episode HTML pages on bhoot-fm.com. Direct vs scrape URL classes. |
| `scripts/download_episodes.py` | Downloader. Resumable via `manifest.json`. Predicts dl.bhoot-fm.com URL first (works for ~99% of episodes), falls back to scraping the episode HTML. |
| `scripts/upload_to_archive.py` | IA uploader. Threadpool, configurable workers/retries/inter-delay. Each episode → its own IA item `bhoot-fm-YYYY-MM-DD`. Atomic manifest writes. |
| `scripts/relink_to_archive.py` | Standalone: rewrites `mp3_url` to IA URLs in dev DB |
| `static/index.html`, `style.css`, `app.js` | Spooky dark theme. Creepster + Special Elite + Noto Sans Bengali fonts. Particles, fog, scanlines, flicker animations. Mobile responsive. SEO meta + JSON-LD + sitemap. |

### Deployment
| File | Purpose |
|---|---|
| `Dockerfile` | Python 3.12-slim, copies `archive.prod.db` as `archive.db`, non-root user, port 8080 |
| `.dockerignore` | Excludes 11 GB `audio/`, `.venv/`, `transcripts/`, manifests, scripts |
| `fly.toml` | App `bhoot-fm-archive`, Singapore region, auto-stop machines, `BFA_PUBLIC_URL` env |
| `setup.bat` / `run.bat` / `run_dev.bat` | Setup + local server (prod-mode + dev-with-hot-reload) |
| `redeploy.bat` | One-shot: ingest → prep prod DB → `fly deploy` |
| `DEPLOY.md` | Step-by-step Fly deploy guide |
| `UPLOAD_TO_ARCHIVE.md` | Step-by-step IA upload guide |

### Data
| File / dir | Notes |
|---|---|
| `audio/YYYY/*.mp3` | 487 downloaded mp3s (~11 GB). NOT committed (`.dockerignore`-d). |
| `manifest.json` | Downloader state (mp3 source URLs, status, sizes) |
| `ia_manifest.json` | IA upload state (per-episode IA URLs after upload) |
| `archive.db` | Dev SQLite |
| `archive.prod.db` | Stripped + relinked DB shipped in Docker image |
| `transcripts/` | `.json` (and `.docx`) sidecars from the Transcriber. **`.json` is what `ingest.py` reads.** |

## Pipeline

```
bhoot-fm.com  ─[scripts/download_episodes.py]─►  audio/YYYY/*.mp3
                                                       │
                                                       ▼
            ─[../BhootFM Transcriber/batch_transcribe.py]─►  transcripts/*.json
                                                       │
                                                       ▼
                                              [ingest.py]  ─►  archive.db
                                                       │
                                                       │ (parallel)
audio/*.mp3 ─[scripts/upload_to_archive.py]─► archive.org    ia_manifest.json
                                                       │
                                                       ▼
                            [prepare_production_db.py] = archive.prod.db
                                                       │
                                                       ▼
                                          [redeploy.bat] → Fly.io
```

## Current state (handover)

| Step | Status |
|---|---|
| 488 episode index built | ✅ |
| 487 mp3s downloaded (11 GB) | ✅ (1 truly 404 on source: 2010-10-18) |
| Transcription | ⏳ **11 of 487 done** |
| IA upload | ⏳ **9 ok, 17 failed, ~462 not yet attempted** — IA rate-limit currently active, user is waiting for it to clear |
| Frontend redesign (spooky, hide text, animations, mobile) | ✅ |
| Security hardening | ✅ (CSP, X-Frame-Options, etc.) |
| SEO (sitemap, robots, JSON-LD, OG, dynamic meta) | ✅ |
| Adaptive "indexed only" filter | ✅ hides when ≥(eps-5) are indexed |
| Production DB prep | ✅ auto-rewrites mp3_url from `ia_manifest.json` |
| Dockerfile + fly.toml | ✅ ready, **not yet deployed** |

## Known blockers

### Internet Archive rate limit (current)
The user's IA account is currently throttled. Symptoms: "**Please reduce
your request rate**" on every upload, even at `--workers 1`. Library
retries (4×8s) weren't enough; we upped defaults to 10 retries × 30s
sleep + an explicit `--inter-delay` to pace uploads.

**Action when resuming**: wait several hours (or overnight) for IA's
throttle window to clear, do one canary upload, then resume with
gentle settings:
```powershell
python scripts/upload_to_archive.py --workers 1 --retries 15 --retries-sleep 60 --inter-delay 10
```

### IA S3 keys exposed
User shared S3 keys in a screenshot during this session. The keys
`iOleX8alMPaMjsXw` / `XCFuCjZt2cIXcGSp` are saved to
`~/.config/internetarchive/ia.ini` (outside the repo). **Recommendation
to user already given**: rotate at <https://archive.org/account/s3.php>
after uploads finish.

## Commands

```powershell
# Local dev server (with hot reload, watches code only)
.\run_dev.bat

# Local prod-like (no reload)
.\run.bat
# Then open http://127.0.0.1:8000

# Ingest new transcripts
python ingest.py

# Upload to IA (resumable, gentle settings)
python scripts/upload_to_archive.py --workers 1 --retries 15 --retries-sleep 60 --inter-delay 10

# Build production DB
python prepare_production_db.py

# Full redeploy (after first-time Fly setup)
.\redeploy.bat
```

## Important behaviours

### Security
- CSP: `default-src 'self'`, `media-src` allows archive.org + dl.bhoot-fm.com only
- CORS: restricted to `BFA_PUBLIC_URL` env in production
- `/api/search` strips matched-text snippets server-side
- `/api/episode/*` regex-validates `YYYY-MM-DD` to prevent path traversal
- Range header bounded to 16 MB per request
- Search query capped at 120 chars
- `/docs` and `/openapi.json` disabled in production

### Frontend
- Plain HTML; no framework, no build step
- All transcript-text rendering removed — only timestamps shown
- "indexed only" filter auto-hides when `/api/stats` reports
  `show_indexed_filter: false` (≥ episodes − 5 are done)
- Keyboard shortcuts: `/` focus search, `R` random, `Space` play/pause, `Esc` back
- Click the 𓁹 eye → random episode (easter egg)
- `prefers-reduced-motion` honoured

### Fly deployment (not yet done)
1. User must sign up at fly.io (card required, $0 charged at free tier)
2. Install flyctl, `fly auth login`
3. `fly launch --no-deploy --copy-config --name bhoot-fm-archive --region sin`
4. From then on: `redeploy.bat` is one command

## Next-session priority order

1. **Wait for IA rate-limit to clear**, then resume upload
2. Continue transcription in `../BhootFM Transcriber/` (run
   `batch_transcribe.py` against `audio/`)
3. When both at 100%, run `redeploy.bat` (assuming Fly account set up)
4. Rotate IA S3 keys after upload completes

## Things to NOT do

- Don't display transcript text on the public site (deliberate)
- Don't host audio files in our own deploy (relies on IA)
- Don't push `audio/` or `archive.db` to git (already in .dockerignore)
- Don't expose `/docs` or `/openapi.json` (deliberately disabled)
- Don't add inline scripts/styles — CSP forbids `'unsafe-inline'` for scripts
- Don't suggest dropping `--reload-exclude` filters in `run_dev.bat` —
  removing them re-introduces the 11 GB watch problem

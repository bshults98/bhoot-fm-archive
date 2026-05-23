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

**Live site:** <https://xer2ten-bhoot-fm-archive.hf.space/>

## Tech stack

| Layer | Tech | Notes |
|---|---|---|
| Backend | FastAPI + SQLite + FTS5 | `unicode61` tokenizer handles Bangla |
| Frontend | Plain HTML + vanilla JS + CSS | No build step, no framework |
| Audio source | Internet Archive (primary) | `mp3_url` rewritten to IA URLs at deploy time |
| Deploy target | **Hugging Face Spaces** (free tier, Docker SDK) | Repo `xer2ten/bhoot-fm-archive`. Earlier Fly.io setup is dormant. |
| Analytics | GoatCounter (`bhootfm.goatcounter.com`) | CSP must allow `https://*.goatcounter.com` for the beacon to register — easy to break. |
| Error tracking | Sentry (optional, lazy import) | Activates if `SENTRY_DSN` secret is set. |

## File inventory

### Code
| File | Purpose |
|---|---|
| `server.py` | FastAPI app. Security headers (CSP, X-Frame-Options), CORS via `BFA_PUBLIC_URL`, FTS5 search with allowlist sanitization, `/api/episode/{id}/audio` proxies local mp3 with HTTP Range OR 302-redirects to source. **`/api/search` strips `snippet` server-side** so transcript text never reaches the client. Also: SEO landing pages `/episodes/{year}` & `/episode/{id}`, `/podcast.xml` RSS feed, `/sitemap.xml`, cache-busting (`?v=<version>`) for HTML asset refs. |
| `ingest.py` | DB schema init + populates from `manifest.json` and `.json` transcript sidecars. |
| `prepare_production_db.py` | Copies `archive.db` → `archive.prod.db`, strips `local_mp3_path`, rewrites `mp3_url` from `ia_manifest.json`, VACUUMs. |
| `schema.sql` | episodes + segments + FTS5 + sync triggers. |
| `static/index.html`, `style.css`, `app.js`, `banglish.js` | Spooky dark theme. Hash-routed SPA + Media Session API + retry logic + Banglish→Bangla phonetic search. |
| `static/about.html` | About / takedown page. |
| `scripts/episodes_index.py` | Hand-scouted list of all 488 episode HTML pages on bhoot-fm.com. |
| `scripts/download_episodes.py` | Resumable downloader via `manifest.json`. |
| `scripts/upload_to_archive.py` | IA uploader (threadpool, retries, atomic manifest writes). |
| `scripts/relink_to_archive.py` | Rewrites `mp3_url` to IA URLs in dev DB. |
| `scripts/make_social_assets.py` | Generates OG image / favicons. |
| `scripts/mine_banglish.py` | Mines transcripts for top-1500 Bangla tokens, reverse-transliterates each into plausible Banglish spellings, writes `scripts/banglish_candidates.json` for review-and-paste into `static/banglish.js`. |
| `tests/test_server.py`, `tests/test_banglish.py` | Pytest covering FTS query escaping, `_EP_ID_RE` path-traversal guard, year regex, cache-buster, Banglish transliterator. JS tests use Node (skipped automatically if `node` is absent). |

### Deployment
| File | Purpose |
|---|---|
| `Dockerfile` | Python 3.12-slim. Copies `archive.prod.db` as `archive.db`, non-root user. Listens on port 7860 (HF default). |
| `.dockerignore` | Excludes `audio/`, `.venv/`, `transcripts/`, manifests, scripts. |
| `redeploy_hf.bat` | One-shot: ingest → prep prod DB → push to HF Space. |
| `redeploy_koyeb.bat`, `redeploy.bat` | Older targets, dormant. |
| `fly.toml` | Legacy from earlier Fly experiment. Not in use. |
| `setup.bat` / `run.bat` / `run_dev.bat` | Setup + local server (prod-mode + dev-with-hot-reload). |
| `.github/workflows/keep-warm.yml` | GitHub Action — twice-daily cron `curl /healthz` to prevent HF Space sleeping. |

### Data
| File / dir | Notes |
|---|---|
| `audio/YYYY/*.mp3` | 487 downloaded mp3s (~11 GB). NOT committed (`.dockerignore`-d). |
| `manifest.json` | Downloader state (mp3 source URLs, status, sizes). |
| `ia_manifest.json` | IA upload state (per-episode IA URLs after upload). |
| `archive.db` | Dev SQLite. |
| `archive.prod.db` | Stripped + relinked DB shipped in the Docker image. |
| `plays.db` | Episode play counter. **Ephemeral on free-tier HF** — wiped on every restart. Either accept the resets or upgrade to HF persistent storage and set `BFA_PLAYS_DB_PATH=/data/plays.db`. |
| `transcripts/` | `.json` (and `.docx`) sidecars from the Transcriber. **`.json` is what `ingest.py` reads.** |

## Pipeline

```
bhoot-fm.com  ──[scripts/download_episodes.py]──►  audio/YYYY/*.mp3
                                                          │
                                                          ▼
            ──[../BhootFM Transcriber/batch_transcribe.py]──►  transcripts/*.json
                                                          │
                                                          ▼
                                                 [ingest.py]  ──►  archive.db
                                                          │
                                                          │ (parallel)
audio/*.mp3 ──[scripts/upload_to_archive.py]──► archive.org    ia_manifest.json
                                                          │
                                                          ▼
                            [prepare_production_db.py] = archive.prod.db
                                                          │
                                                          ▼
                                       [redeploy_hf.bat] ──► Hugging Face Space
```

## Current state

| Step | Status |
|---|---|
| 488 episode index built | ✅ |
| 487 mp3s downloaded (11 GB) | ✅ (1 truly 404 on source: 2010-10-18) |
| Transcription | mostly done — 486 transcript JSONs present |
| IA upload | partial |
| Frontend (spooky theme, hide text, mobile, retry, MediaSession) | ✅ |
| Security hardening (CSP, headers, FTS sanitization) | ✅ |
| SEO (year pages, episode pages, sitemap, JSON-LD, OG/Twitter) | ✅ |
| Banglish→Bangla phonetic search | ✅ (curated dict + algorithmic fallback) |
| Podcast RSS feed (`/podcast.xml`) | ✅ |
| Cache-busting (asset `?v=<hash>` on each deploy) | ✅ — fixed mobile-Edge stale-cache problem |
| GoatCounter analytics | ✅ — CSP fixed to allow `https://*.goatcounter.com` |
| Tests | ✅ pytest 33 cases, all passing |
| HF Space live | ✅ <https://xer2ten-bhoot-fm-archive.hf.space/> |

## Commands

```powershell
# Local dev server (with hot reload, watches code only — never audio/)
.\run_dev.bat

# Local prod-like (no reload)
.\run.bat
# Then open http://127.0.0.1:8000

# Ingest new transcripts
python ingest.py

# Build production DB
python prepare_production_db.py

# Full redeploy to HF
.\redeploy_hf.bat

# Run all tests
python -m pytest tests/ -v

# Mine new Banglish candidates from the transcript corpus
python scripts/mine_banglish.py
# Review scripts/banglish_candidates.json and merge useful entries into
# the DICT table at the top of static/banglish.js.

# Upload more episodes to IA
python scripts/upload_to_archive.py --workers 1 --retries 15 --retries-sleep 60 --inter-delay 10
```

## Important behaviours

### Security
- CSP: `default-src 'self'`; `media-src` allows archive.org + dl.bhoot-fm.com; `connect-src` and `img-src` allow `https://*.goatcounter.com`. **Both** must include GoatCounter or analytics silently break (the script loads, but the hit beacon is blocked).
- CORS: restricted to `BFA_PUBLIC_URL` env in production.
- `/api/search` strips matched-text snippets server-side.
- `/api/episode/*` and `/episode/*` regex-validate `YYYY-MM-DD(-pt\d)?` to prevent path traversal.
- Range header bounded to 16 MB per request.
- Search query capped at 120 chars.
- `/docs` and `/openapi.json` disabled in production.
- Sentry: lazy-imported; activates only if `SENTRY_DSN` is set as an HF secret.

### Frontend
- Plain HTML; no framework, no build step.
- Banglish phonetic search: typing `hospital` → searches `হাসপাতাল`; full Banglish→Bangla logic in `static/banglish.js` (~80 curated loan/proper words + algorithmic fallback).
- All transcript-text rendering removed — only timestamps shown.
- Keyboard shortcuts: `/` focus search, `R` random, `Space` play/pause, `Esc` back.
- Click the 𓁹 eye → random episode (easter egg).
- `prefers-reduced-motion` honoured.
- **Media Session API** wired — lock-screen / dynamic island / BT-headset / media-keys all control playback with title + artwork.
- **Retry+cold-start UI**: `api()` retries network/5xx with 0.6 → 1.8 → 4.5 s backoff; home view shows "The archive is waking up…" + manual retry button on hard failure.
- **Cache-busting**: HTML rewrites asset hrefs to `?v=<version>` so a deploy invalidates JS/CSS for mobile browsers that ignore `no-cache` on cached resources. Version comes from `FLY_RELEASE_VERSION` if set, else mtime hash.

### Hugging Face deployment
- Repo: `xer2ten/bhoot-fm-archive` (Docker SDK Space, free tier).
- Public URL: `https://xer2ten-bhoot-fm-archive.hf.space/`.
- `BFA_PUBLIC_URL` env should be set to that URL inside the Space settings.
- Free tier sleeps after ~48h idle. Cold boot 30–60 s. Kept warm by `.github/workflows/keep-warm.yml` (twice-daily `curl /healthz` cron).
- Free tier has **no persistent storage** — `plays.db` resets on every restart. If continuous counts matter, upgrade to HF Persistent Storage and set `BFA_PLAYS_DB_PATH=/data/plays.db`.

### RSS / podcast feed
- `/podcast.xml` emits an iTunes-flavored RSS feed of every episode whose `mp3_url` is an external (IA / dl.bhoot-fm.com) URL.
- Audio bytes do NOT go through our server — `<enclosure>` points straight at the IA URL.
- Discoverable from index.html via `<link rel="alternate" type="application/rss+xml">` and a visible footer link.

## Next-session priority order

1. Resume IA upload when rate limit clears.
2. Continue transcription (`../BhootFM Transcriber/batch_transcribe.py`).
3. Once both at ~100%, run `redeploy_hf.bat`.
4. (Optional) Merge useful entries from `scripts/banglish_candidates.json` into `static/banglish.js` — quick win for search recall.
5. (Optional) Set `SENTRY_DSN` as an HF secret to start receiving prod error alerts.

## Things to NOT do

- Don't display transcript text on the public site (deliberate).
- Don't host audio files in our own deploy (relies on IA / dl.bhoot-fm.com).
- Don't push `audio/` or `archive.db` to git (already in `.dockerignore`).
- Don't expose `/docs` or `/openapi.json` (deliberately disabled).
- Don't add inline scripts — CSP forbids `'unsafe-inline'` for scripts.
- Don't drop `--reload-exclude` filters in `run_dev.bat` — removing them re-introduces the 11 GB watch problem.
- Don't add `gc.zgo.at` to CSP without also adding `https://*.goatcounter.com` — the script will load but every hit will be blocked silently.
- Don't remove cache-busting on HTML asset refs — mobile Edge ignores `no-cache` on cached JS/CSS and ships stale code for up to a day after redeploy without it.

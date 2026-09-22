"""BhootFM Archive — FastAPI backend.

Security-conscious:
  - CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy
  - CORS restricted to known origins
  - Input length caps on search; bounded Range header parsing
  - Generic error responses (no stack-traces / internal paths leaked)
  - All SQL is parameterized
SEO:
  - /sitemap.xml lists every episode page (hash routes)
  - /robots.txt allows all
"""

import html
import json
import logging
import mimetypes
import os
import re
import sqlite3
import threading
import time

# Windows registry sometimes maps .js to text/plain, which makes browsers
# refuse to execute the file under strict MIME checking. Register the
# correct types explicitly before anything else touches mimetypes.
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/json", ".json")
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

# ─── Config ─────────────────────────────────────────────────────────
DB_PATH = Path(__file__).parent / "archive.db"
STATIC_DIR = Path(__file__).parent / "static"

# Per-episode play counts. Lives in its own SQLite file so the read-only
# archive.db can stay read-only and so the file can be put on a persistent
# volume separately from the bundled archive. Set BFA_PLAYS_DB_PATH to a
# persistent-storage path (e.g. /data/plays.db on Fly volume or HF Spaces
# persistent storage) — without that, counts reset on every redeploy.
PLAYS_DB_PATH = Path(
    os.environ.get("BFA_PLAYS_DB_PATH", str(Path(__file__).parent / "plays.db"))
)

# Public-facing brand. Set BFA_PUBLIC_URL via env for production
# (e.g. "https://bhoot-fm-archive.fly.dev").
PUBLIC_URL = os.environ.get("BFA_PUBLIC_URL", "").rstrip("/")
ALLOWED_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]
if PUBLIC_URL:
    ALLOWED_ORIGINS.append(PUBLIC_URL)

# Hard caps on user input.
MAX_SEARCH_LEN = 120
MAX_RANGE_BYTES = 16 * 1024 * 1024   # 16 MB per Range request (plenty for audio chunks)

# Per-IP rate limit for /api/search — token bucket. Friendly enough for human
# users (a fast typer triggers a few requests/sec through the debounce), strict
# enough to stop a bored visitor from pinning the SQLite FTS5 index.
SEARCH_BURST = 12
SEARCH_REFILL_PER_SEC = 0.6     # ~36 req/min sustained
SEARCH_BUCKET_TTL = 600         # forget IPs idle longer than this

# Play-counting endpoint: gentler bucket since the client only pings once
# per (episode, device) per session, but still bounded against abuse.
PLAYS_BURST = 30
PLAYS_REFILL_PER_SEC = 0.5      # ~30 req/min sustained

log = logging.getLogger("archive")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Optional Sentry integration — only activates if SENTRY_DSN is set AND
# sentry-sdk is installed in the image. Kept import-lazy so adding/removing
# Sentry is a pure env-var + pip change with no code edits.
if os.environ.get("SENTRY_DSN"):
    try:
        import sentry_sdk  # type: ignore
        sentry_sdk.init(
            dsn=os.environ["SENTRY_DSN"],
            traces_sample_rate=0.0,
            send_default_pii=False,
            release=os.environ.get("FLY_RELEASE_VERSION") or None,
            environment=os.environ.get("FLY_APP_NAME") or "local",
        )
        log.info("sentry initialised")
    except ImportError:
        log.warning("SENTRY_DSN set but sentry-sdk not installed; skipping")


def get_db() -> sqlite3.Connection:
    # Read-only URI — we never write to the DB from request handlers.
    # Belt-and-braces against accidental writes if someone adds a query
    # that mutates state. Stays compatible with dev workflows where
    # `python ingest.py` may have written while the server is up.
    conn = sqlite3.connect(
        f"file:{DB_PATH}?mode=ro",
        uri=True,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    return conn


def get_plays_db() -> sqlite3.Connection:
    """Read-write connection to the plays counter DB."""
    conn = sqlite3.connect(str(PLAYS_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_plays_schema() -> None:
    PLAYS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_plays_db() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS plays ("
            "  episode_id TEXT PRIMARY KEY, "
            "  count INTEGER NOT NULL DEFAULT 0, "
            "  last_at INTEGER NOT NULL DEFAULT 0"
            ")"
        )
        db.execute("CREATE INDEX IF NOT EXISTS plays_count_idx ON plays(count DESC)")
        # Search logs for learning user queries and improving Banglish dictionary
        db.execute(
            "CREATE TABLE IF NOT EXISTS search_logs ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "  query TEXT NOT NULL, "
            "  bangla_query TEXT, "
            "  transliterated INTEGER DEFAULT 0, "
            "  result_count INTEGER DEFAULT 0, "
            "  created_at INTEGER NOT NULL DEFAULT 0"
            ")"
        )
        db.execute("CREATE INDEX IF NOT EXISTS search_logs_query_idx ON search_logs(query)")
        db.execute("CREATE INDEX IF NOT EXISTS search_logs_created_idx ON search_logs(created_at)")
        db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not DB_PATH.exists():
        raise RuntimeError(f"{DB_PATH.name} not found. Run ingest.py first.")
    # Warm a connection once at startup so PRAGMA defaults are applied and
    # to surface schema problems immediately rather than on first request.
    with get_db() as db:
        db.execute("SELECT 1 FROM episodes LIMIT 1").fetchone()
    _ensure_plays_schema()
    log.info("plays db at %s", PLAYS_DB_PATH)
    yield


app = FastAPI(
    title="Bhoot FM Archive",
    docs_url=None,        # hide /docs in production
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS if PUBLIC_URL else ["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
    max_age=86400,
)


# ─── Security headers middleware ────────────────────────────────────
CSP = (
    "default-src 'self'; "
    # GoatCounter falls back to an <img> pixel when sendBeacon/fetch is blocked,
    # so its hit endpoint needs to be reachable via img-src too.
    "img-src 'self' data: https://*.goatcounter.com; "
    # Allow audio from our origin, the IA CDN (the final home), and the
    # legacy bhoot-fm.com mirror used as fallback during transition.
    "media-src 'self' "
    "https://archive.org https://*.archive.org "
    "http://dl.bhoot-fm.com https://dl.bhoot-fm.com blob:; "
    "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    # gc.zgo.at serves the loader script; bhootfm.goatcounter.com is where the
    # actual hit beacon is POSTed (the data-goatcounter URL on the <script>).
    # Both must be allowed or visits silently never register.
    "script-src 'self' https://gc.zgo.at; "
    "connect-src 'self' https://gc.zgo.at https://*.goatcounter.com; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
        "magnetometer=(), microphone=(), payment=(), usb=()"
    )
    # Cross-origin isolation hardening.
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-site"
    # HSTS via the app too — Fly's edge also sets it, but this protects any
    # other HTTPS deploy. Skipped for plain-HTTP local dev.
    if PUBLIC_URL:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    # Cache policy: long-lived for versionable static assets, none for API.
    path = request.url.path
    if path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    elif path in ("/sitemap.xml", "/robots.txt"):
        response.headers.setdefault("Cache-Control", "public, max-age=3600")
    elif path == "/" or path.endswith(".html"):
        # HTML changes when we redeploy — revalidate cheaply.
        response.headers.setdefault("Cache-Control", "no-cache")
    elif "." in path.rsplit("/", 1)[-1]:  # any other static asset
        response.headers.setdefault(
            "Cache-Control", "public, max-age=86400, stale-while-revalidate=604800"
        )
    return response


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Don't leak internals; log on the server, return a sanitized response."""
    log.exception(
        "unhandled error: %s %s -> %r",
        request.method, request.url.path, exc,
    )
    return JSONResponse(
        status_code=500,
        content={"error": "Internal error"},
    )


# ─── Rate limiter ───────────────────────────────────────────────────
class _TokenBucket:
    """Per-IP token bucket. Cheap, thread-safe, in-memory.

    Resets on process restart, which is fine here: Fly auto-stops the machine
    after idle anyway, and we don't need distributed limits across regions.
    """
    __slots__ = ("_buckets", "_lock", "_last_prune")

    def __init__(self):
        self._buckets: dict[str, tuple[float, float]] = {}  # ip -> (tokens, last_ts)
        self._lock = threading.Lock()
        self._last_prune = time.monotonic()

    def take(self, key: str, capacity: int, refill_per_sec: float) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (float(capacity), now))
            tokens = min(capacity, tokens + (now - last) * refill_per_sec)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1.0, now)
            # Prune stale buckets once per minute to keep memory bounded.
            if now - self._last_prune > 60:
                self._last_prune = now
                cutoff = now - SEARCH_BUCKET_TTL
                self._buckets = {
                    k: v for k, v in self._buckets.items() if v[1] >= cutoff
                }
            return True


_search_limiter = _TokenBucket()
_plays_limiter = _TokenBucket()


def _client_ip(request: Request) -> str:
    """Best-effort real client IP. Fly sets Fly-Client-IP; XFF as backup."""
    fly = request.headers.get("fly-client-ip")
    if fly:
        return fly.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


# ─── Search helpers ─────────────────────────────────────────────────
_TOKEN_SPLIT = re.compile(r"\s+")
_DISALLOWED = re.compile(r"[^\wঀ-৿\s]", re.UNICODE)  # keep Bangla block + ASCII word chars


def fts_query(raw: str) -> str:
    raw = (raw or "").strip()[:MAX_SEARCH_LEN]
    # Strip FTS5 operators / punctuation; the regex above is allowlist-style.
    raw = _DISALLOWED.sub(" ", raw)
    parts = [w for w in _TOKEN_SPLIT.split(raw) if w]
    if not parts:
        return ""
    safe = []
    for w in parts:
        # Escape any remaining double quotes (defensive).
        w = w.replace('"', '""')
        safe.append(f'"{w}"*')
    return " ".join(safe)


# ─── Routes ─────────────────────────────────────────────────────────
@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    """Cheap liveness probe for Fly's healthcheck. No DB hit, no JSON parsing
    on the caller — just an HTTP 200 so an idle machine can be polled without
    forcing it to wake the SQLite page cache."""
    return "ok"


@app.get("/api/health")
def health():
    with get_db() as db:
        eps, segs, done = db.execute(
            "SELECT (SELECT COUNT(*) FROM episodes), "
            "       (SELECT COUNT(*) FROM segments), "
            "       (SELECT COUNT(*) FROM episodes WHERE transcript_status='done')"
        ).fetchone()
    return {"ok": True, "episodes": eps, "segments": segs, "indexed": done}


@app.get("/api/search-stats")
def search_stats(days: int = Query(30, ge=1, le=365)):
    """Search analytics for learning user queries and improving Banglish.
    Shows top queries, zero-result queries, and transliteration usage.
    Anonymous - no IPs or user identifiers stored."""
    cutoff = int(time.time()) - (days * 86400)
    with get_plays_db() as pdb:
        # Top queries
        top_queries = pdb.execute(
            "SELECT query, bangla_query, transliterated, COUNT(*) as count, "
            "AVG(result_count) as avg_results "
            "FROM search_logs WHERE created_at > ? "
            "GROUP BY query ORDER BY count DESC LIMIT 50",
            (cutoff,)
        ).fetchall()

        # Zero-result queries (need dictionary entries)
        zero_results = pdb.execute(
            "SELECT query, bangla_query, transliterated, COUNT(*) as count "
            "FROM search_logs WHERE created_at > ? AND result_count = 0 "
            "GROUP BY query ORDER BY count DESC LIMIT 50",
            (cutoff,)
        ).fetchall()

        # Transliteration stats
        translit_stats = pdb.execute(
            "SELECT "
            "  COUNT(*) as total_searches, "
            "  SUM(transliterated) as transliterated_count, "
            "  SUM(CASE WHEN result_count = 0 THEN 1 ELSE 0 END) as zero_results "
            "FROM search_logs WHERE created_at > ?",
            (cutoff,)
        ).fetchone()

        # Recent searches (for debugging)
        recent = pdb.execute(
            "SELECT query, bangla_query, transliterated, result_count, created_at "
            "FROM search_logs WHERE created_at > ? "
            "ORDER BY created_at DESC LIMIT 20",
            (cutoff,)
        ).fetchall()

    return {
        "period_days": days,
        "stats": {
            "total_searches": translit_stats["total_searches"] if translit_stats else 0,
            "transliterated_count": translit_stats["transliterated_count"] if translit_stats else 0,
            "zero_results": translit_stats["zero_results"] if translit_stats else 0,
        },
        "top_queries": [dict(r) for r in top_queries],
        "zero_result_queries": [dict(r) for r in zero_results],
        "recent_searches": [dict(r) for r in recent],
    }


_CACHEABLE_HEADERS = {
    # These two endpoints only change when we redeploy (which happens after
    # ingest of new transcripts). Cache 5 min in the browser + 30 min on any
    # CDN sitting in front (Cloudflare, Fly edge); serve-stale-while-revalidate
    # so users never wait on a refresh.
    "Cache-Control": "public, max-age=300, s-maxage=1800, stale-while-revalidate=86400"
}


@app.get("/api/stats")
def stats():
    """Tiny payload the frontend uses to decide whether to show the filter."""
    with get_db() as db:
        eps, done = db.execute(
            "SELECT (SELECT COUNT(*) FROM episodes), "
            "       (SELECT COUNT(*) FROM episodes WHERE transcript_status='done')"
        ).fetchone()
    return JSONResponse(
        {
            "episode_count": eps,
            "indexed_count": done,
            # The filter is only useful when there's a meaningful difference.
            "show_indexed_filter": done < eps and (eps - done) >= 5,
        },
        headers=_CACHEABLE_HEADERS,
    )


@app.get("/api/episodes")
def list_episodes(
    only_transcribed: bool = Query(False),
):
    with get_db() as db:
        sql = (
            "SELECT id, air_date, title, mp3_url, duration_sec, transcript_status, "
            "(local_mp3_path IS NOT NULL) AS has_local, "
            "(SELECT COUNT(*) FROM segments s WHERE s.episode_id = e.id) AS segment_count "
            "FROM episodes e "
        )
        if only_transcribed:
            sql += "WHERE transcript_status = 'done' "
        sql += "ORDER BY air_date DESC"
        rows = db.execute(sql).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("has_local"):
            d["mp3_url"] = f"/api/episode/{d['id']}/audio"
        out.append(d)
    return JSONResponse({"episodes": out}, headers=_CACHEABLE_HEADERS)


_EP_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(-pt\d)?$")


@app.post("/api/play")
async def record_play(request: Request):
    """Bump the play count for an episode. Client should call this once per
    (episode, device) after >=15 seconds of playback. Validates that the
    episode exists in the archive."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    episode_id = (body or {}).get("episode_id") if isinstance(body, dict) else None
    if not isinstance(episode_id, str) or not _EP_ID_RE.match(episode_id):
        raise HTTPException(400, "Invalid episode_id")
    ip = _client_ip(request)
    if not _plays_limiter.take(ip, PLAYS_BURST, PLAYS_REFILL_PER_SEC):
        raise HTTPException(429, "Slow down")
    with get_db() as db:
        exists = db.execute(
            "SELECT 1 FROM episodes WHERE id = ?", (episode_id,)
        ).fetchone()
    if not exists:
        raise HTTPException(404, "Episode not found")
    now = int(time.time())
    with get_plays_db() as pdb:
        pdb.execute(
            "INSERT INTO plays (episode_id, count, last_at) VALUES (?, 1, ?) "
            "ON CONFLICT(episode_id) DO UPDATE SET "
            "  count = count + 1, last_at = excluded.last_at",
            (episode_id, now),
        )
        pdb.commit()
    return {"ok": True}


@app.get("/api/popular")
def popular(limit: int = Query(3, ge=1, le=20)):
    """Top-N most-played episodes across all visitors, with episode metadata."""
    with get_plays_db() as pdb:
        rows = pdb.execute(
            "SELECT episode_id, count FROM plays "
            "ORDER BY count DESC, last_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    ids = [r["episode_id"] for r in rows]
    counts = {r["episode_id"]: r["count"] for r in rows}
    headers = {"Cache-Control": "public, max-age=60, s-maxage=300, stale-while-revalidate=600"}
    if not ids:
        return JSONResponse({"episodes": []}, headers=headers)
    placeholders = ",".join("?" * len(ids))
    with get_db() as db:
        ep_rows = db.execute(
            "SELECT id, air_date, title, mp3_url, duration_sec, transcript_status, "
            "(local_mp3_path IS NOT NULL) AS has_local "
            f"FROM episodes WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
    by_id = {r["id"]: dict(r) for r in ep_rows}
    out = []
    for eid in ids:  # preserve popularity order
        ep = by_id.get(eid)
        if not ep:
            continue
        if ep.get("has_local"):
            ep["mp3_url"] = f"/api/episode/{ep['id']}/audio"
        ep["play_count"] = counts[eid]
        out.append(ep)
    return JSONResponse({"episodes": out}, headers=headers)


@app.get("/api/episode/{episode_id}")
def episode_detail(episode_id: str):
    if not re.match(r"^\d{4}-\d{2}-\d{2}(-pt\d)?$", episode_id):
        raise HTTPException(404, "Episode not found")
    with get_db() as db:
        ep = db.execute(
            "SELECT id, air_date, title, mp3_url, duration_sec, "
            "(local_mp3_path IS NOT NULL) AS has_local "
            "FROM episodes WHERE id = ?",
            (episode_id,),
        ).fetchone()
        if not ep:
            raise HTTPException(404, "Episode not found")
        segs = db.execute(
            "SELECT id, start_sec, end_sec, text, speaker FROM segments "
            "WHERE episode_id = ? ORDER BY start_sec",
            (episode_id,),
        ).fetchall()
    epd = dict(ep)
    if epd.get("has_local"):
        epd["mp3_url"] = f"/api/episode/{epd['id']}/audio"
    return {"episode": epd, "segments": [dict(s) for s in segs]}


@app.get("/api/episode/{episode_id}/audio")
def episode_audio(episode_id: str, request: Request):
    if not re.match(r"^\d{4}-\d{2}-\d{2}(-pt\d)?$", episode_id):
        raise HTTPException(404)
    with get_db() as db:
        ep = db.execute(
            "SELECT mp3_url, local_mp3_path FROM episodes WHERE id = ?",
            (episode_id,),
        ).fetchone()
    if not ep:
        raise HTTPException(404)
    local = ep["local_mp3_path"]
    if not local or not os.path.isfile(local):
        return RedirectResponse(ep["mp3_url"], status_code=302)

    path = Path(local)
    file_size = path.stat().st_size
    range_header = request.headers.get("range") or request.headers.get("Range")
    mime = mimetypes.guess_type(str(path))[0] or "audio/mpeg"

    if range_header:
        m = re.match(r"^bytes=(\d+)-(\d*)$", range_header)
        if not m:
            raise HTTPException(416, "Invalid Range header")
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else file_size - 1
        end = min(end, file_size - 1, start + MAX_RANGE_BYTES - 1)
        if start > end or start >= file_size:
            raise HTTPException(416)
        length = end - start + 1

        def stream():
            with open(path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            stream(),
            status_code=206,
            media_type=mime,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
            },
        )
    return FileResponse(
        str(path),
        media_type=mime,
        headers={"Accept-Ranges": "bytes", "Content-Length": str(file_size)},
    )


@app.get("/api/search")
def search(
    request: Request,
    q: str = Query("", max_length=MAX_SEARCH_LEN),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10_000),
    episode_id: Optional[str] = Query(None),
    original_q: Optional[str] = Query(None, max_length=MAX_SEARCH_LEN),
    transliterated: bool = Query(False),
):
    # Rate limit before doing any DB work. Empty queries return early below,
    # but we still want to bill them against the bucket — they're cheap to
    # send and an attacker could spam them just as easily.
    if not _search_limiter.take(_client_ip(request), SEARCH_BURST, SEARCH_REFILL_PER_SEC):
        raise HTTPException(
            status_code=429,
            detail="Too many searches, slow down a moment.",
            headers={"Retry-After": "5"},
        )
    q_norm = q.strip()
    if not q_norm:
        return {"query": q, "total": 0, "results": []}
    match = fts_query(q_norm)
    if not match:
        return {"query": q, "total": 0, "results": []}
    if episode_id and not re.match(r"^\d{4}-\d{2}-\d{2}(-pt\d)?$", episode_id):
        raise HTTPException(400, "bad episode_id")

    with get_db() as db:
        total_sql = (
            "SELECT COUNT(*) FROM segments_fts "
            "JOIN segments s ON s.id = segments_fts.rowid "
            "WHERE segments_fts MATCH ?"
        )
        params: list = [match]
        if episode_id:
            total_sql += " AND s.episode_id = ?"
            params.append(episode_id)
        total = db.execute(total_sql, params).fetchone()[0]

        sql = (
            "SELECT s.id, s.episode_id, s.start_sec, s.end_sec, "
            "snippet(segments_fts, 0, '<mark>', '</mark>', '…', 12) AS snippet, "
            "e.title AS episode_title, e.air_date AS episode_date, "
            "e.mp3_url AS mp3_url, e.local_mp3_path AS local_mp3_path, "
            "bm25(segments_fts) AS rank "
            "FROM segments_fts "
            "JOIN segments s ON s.id = segments_fts.rowid "
            "JOIN episodes e ON e.id = s.episode_id "
            "WHERE segments_fts MATCH ? "
        )
        params2: list = [match]
        if episode_id:
            sql += "AND s.episode_id = ? "
            params2.append(episode_id)
        # Order by relevance (bm25, lower is better), then by date and time
        sql += "ORDER BY rank, e.air_date DESC, s.start_sec ASC LIMIT ? OFFSET ?"
        params2.extend([limit, offset])
        rows = db.execute(sql, params2).fetchall()

    results = []
    for r in rows:
        d = dict(r)
        # Rewrite mp3_url to local proxy when we have the file.
        if d.pop("local_mp3_path", None):
            d["mp3_url"] = f"/api/episode/{d['episode_id']}/audio"
        # IMPORTANT: don't expose the matched text to the client. Search
        # behaviour stays the same; the snippet is dropped server-side so
        # we never ship transcript content.
        d.pop("snippet", None)
        # Remove internal ranking score
        d.pop("rank", None)
        results.append(d)

    # Log search for learning (anonymous - no IPs or user identifiers)
    try:
        with get_plays_db() as pdb:
            # Use original_q if provided (for Banglish tracking), otherwise use q
            log_query = original_q if original_q else q_norm
            pdb.execute(
                "INSERT INTO search_logs (query, bangla_query, transliterated, result_count, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (log_query, q_norm, 1 if transliterated else 0,
                 total, int(time.time()))
            )
            pdb.commit()
    except Exception:
        pass  # Don't fail search if logging fails

    return {"query": q, "total": total, "limit": limit, "offset": offset,
            "results": results}


# ─── SEO helpers ────────────────────────────────────────────────────
@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    sitemap_url = (PUBLIC_URL or "") + "/sitemap.xml"
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        "\n"
        "User-agent: Googlebot\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        "\n"
        "User-agent: Bingbot\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        "\n"
        f"Sitemap: {sitemap_url}\n"
    )


@app.get("/podcast.xml")
def podcast_feed():
    """iTunes-flavored RSS feed for podcast apps.

    Each episode becomes an <item> with an <enclosure> pointing at the IA URL,
    so subscribers can stream the full archive from Apple Podcasts, Pocket
    Casts, AntennaPod, Overcast, etc. Audio bytes never come through us — the
    feed is just the index that tells podcast players where to fetch.

    Only includes episodes that point at an external (IA / dl.bhoot-fm.com)
    URL — locally-served mp3s would force traffic through this box and
    defeat the point of off-loading hosting to IA.
    """
    base = PUBLIC_URL or ""
    with get_db() as db:
        rows = db.execute(
            "SELECT id, air_date, title, mp3_url, duration_sec "
            "FROM episodes "
            "WHERE mp3_url LIKE 'http%' "
            "ORDER BY air_date DESC"
        ).fetchall()

    def rfc2822(date_str: str, idx: int) -> str:
        # Air dates are stored as YYYY-MM-DD. Podcast clients want RFC-2822
        # timestamps. Spread episodes one minute apart inside the day so the
        # client-side sort is deterministic when several share an air_date.
        try:
            y, m, d = (int(x) for x in date_str.split("-"))
        except Exception:
            return "Mon, 01 Jan 2007 00:00:00 +0000"
        from datetime import datetime, timezone, timedelta
        return (datetime(y, m, d, 23, 0, tzinfo=timezone.utc)
                + timedelta(minutes=idx)).strftime("%a, %d %b %Y %H:%M:%S +0000")

    items_xml = []
    for i, r in enumerate(rows):
        title = r["title"] or f"Bhoot FM — {r['air_date']}"
        guid = f"{base}/episode/{r['id']}" if base else f"/episode/{r['id']}"
        page = f"{base}/episode/{r['id']}" if base else f"/episode/{r['id']}"
        duration = int(r["duration_sec"] or 0)
        items_xml.append(
            "<item>"
            f"<title>{html.escape(title)}</title>"
            f"<link>{html.escape(page)}</link>"
            f"<guid isPermaLink=\"true\">{html.escape(guid)}</guid>"
            f"<pubDate>{rfc2822(r['air_date'] or '2007-01-01', i)}</pubDate>"
            f"<enclosure url=\"{html.escape(r['mp3_url'])}\" "
            f'type="audio/mpeg" length="0" />'
            f"<itunes:duration>{duration}</itunes:duration>"
            f"<itunes:author>RJ Russell</itunes:author>"
            f"<itunes:explicit>false</itunes:explicit>"
            f"<description>Bhoot FM episode aired on {html.escape(r['air_date'] or '')}, "
            f"hosted by RJ Russell on Radio Foorti 88.0 FM. Listener-submitted "
            f"Bangla ghost stories and paranormal encounters.</description>"
            "</item>"
        )

    cover = f"{base}/og-image.png" if base else "/og-image.png"
    feed_url = f"{base}/podcast.xml" if base else "/podcast.xml"
    site = base or "/"

    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" '
        'xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" '
        'xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:content="http://purl.org/rss/1.0/modules/content/">\n'
        '<channel>\n'
        '<title>Bhoot FM Archive</title>\n'
        f'<link>{html.escape(site)}</link>\n'
        f'<atom:link href="{html.escape(feed_url)}" rel="self" type="application/rss+xml" />\n'
        '<language>bn</language>\n'
        '<description>Every Bhoot FM episode — Bangladesh\'s longest-running '
        'late-night Bangla horror radio show, hosted by RJ Russell on Radio '
        'Foorti 88.0 FM. A non-commercial fan archive.</description>\n'
        '<itunes:author>RJ Russell · Bhoot FM</itunes:author>\n'
        '<itunes:owner><itunes:name>Bhoot FM Archive</itunes:name></itunes:owner>\n'
        '<itunes:category text="Society &amp; Culture">'
        '<itunes:category text="Documentary" /></itunes:category>\n'
        '<itunes:category text="Fiction"><itunes:category text="Drama" /></itunes:category>\n'
        '<itunes:explicit>false</itunes:explicit>\n'
        f'<itunes:image href="{html.escape(cover)}" />\n'
        f'<image><url>{html.escape(cover)}</url>'
        '<title>Bhoot FM Archive</title>'
        f'<link>{html.escape(site)}</link></image>\n'
        + "\n".join(items_xml) +
        "\n</channel>\n</rss>\n"
    )
    return Response(
        content=body,
        media_type="application/rss+xml; charset=utf-8",
        headers={"Cache-Control": "public, max-age=1800, s-maxage=3600"},
    )


@app.get("/sitemap.xml")
def sitemap():
    base = PUBLIC_URL or ""
    with get_db() as db:
        episodes = db.execute(
            "SELECT id, air_date FROM episodes ORDER BY air_date DESC"
        ).fetchall()
    years = sorted({r["air_date"][:4] for r in episodes if r["air_date"]}, reverse=True)
    urls = [
        # Homepage - highest priority
        f"<url><loc>{base}/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>",
        # About page
        f"<url><loc>{base}/about.html</loc><changefreq>monthly</changefreq><priority>0.5</priority></url>",
        # Podcast feed
        f"<url><loc>{base}/podcast.xml</loc><changefreq>weekly</changefreq><priority>0.7</priority></url>",
    ]
    # Year pages - high priority for browsing
    for y in years:
        urls.append(
            f"<url><loc>{base}/episodes/{y}</loc>"
            f"<changefreq>weekly</changefreq><priority>0.8</priority></url>"
        )
    # Episode pages - include lastmod for freshness signals
    for r in episodes:
        urls.append(
            f"<url><loc>{base}/episode/{r['id']}</loc>"
            f"<lastmod>{r['air_date']}</lastmod>"
            f"<changefreq>yearly</changefreq><priority>0.6</priority></url>"
        )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n'
        + "\n".join(urls) +
        "\n</urlset>\n"
    )
    return Response(content=body, media_type="application/xml")


# ─── SEO landing pages ──────────────────────────────────────────────
# Real, crawlable HTML for each year and each episode. Click-through into
# the SPA player happens via a normal anchor to /#/ep/{id}, so we don't
# need any inline script (which CSP would block anyway).

_MONTH_NAMES_EN = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
_YEAR_RE = re.compile(r"^\d{4}$")


def _fmt_duration(sec: Optional[int]) -> str:
    if not sec:
        return ""
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s"


def _fmt_iso_duration(sec: Optional[int]) -> str:
    if not sec:
        return ""
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    out = "PT"
    if h:
        out += f"{h}H"
    if m:
        out += f"{m}M"
    if s or not (h or m):
        out += f"{s}S"
    return out


def _page_shell(title: str, description: str, canonical_path: str,
                body: str, jsonld: list) -> str:
    base = PUBLIC_URL or ""
    canonical = f"{base}{canonical_path}" if base else canonical_path
    jsonld_blocks = "\n".join(
        f'<script type="application/ld+json">{json.dumps(obj, ensure_ascii=False)}</script>'
        for obj in jsonld
    )
    return f"""<!doctype html>
<html lang="bn">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="theme-color" content="#07070b" />
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description)}" />
<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1" />
<link rel="canonical" href="{html.escape(canonical)}" />
<link rel="icon" href="/favicon.svg" type="image/svg+xml" />
<meta property="og:type" content="website" />
<meta property="og:site_name" content="Bhoot FM Archive" />
<meta property="og:url" content="{html.escape(canonical)}" />
<meta property="og:title" content="{html.escape(title)}" />
<meta property="og:description" content="{html.escape(description)}" />
<meta property="og:image" content="{html.escape((PUBLIC_URL or '') + '/og-image.png')}" />
<meta property="og:image:width" content="1200" />
<meta property="og:image:height" content="630" />
<meta property="og:image:alt" content="Bhoot FM Archive — a one-eyed ghost beside the wordmark, on a dark backdrop." />
<meta property="og:locale" content="bn_BD" />
<meta property="og:locale:alternate" content="en_US" />
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="{html.escape(title)}" />
<meta name="twitter:description" content="{html.escape(description)}" />
<meta name="twitter:image" content="{html.escape((PUBLIC_URL or '') + '/og-image.png')}" />
<meta name="twitter:image:alt" content="Bhoot FM Archive — dark horror radio archive." />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Creepster&family=Special+Elite&family=Noto+Sans+Bengali:wght@400;500;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
<link rel="stylesheet" href="/style.css" />
{jsonld_blocks}
</head>
<body class="seo-page">
<header role="banner" class="seo-header">
  <a href="/" class="seo-home-link">
    <span class="logo" aria-hidden="true">𓁹</span>
    <span class="seo-brand">Bhoot FM <span class="accent">Archive</span></span>
  </a>
</header>
<main id="main" role="main" class="seo-main">
{body}
</main>
<footer class="seo-footer">
  <p>© 2026 · A non-commercial fan project. Audio belongs to Radio Foorti and the Bhoot FM team.
  <a href="/about.html">about &amp; takedown</a></p>
</footer>
</body>
</html>
"""


@app.get("/episodes/{year}")
def episodes_by_year(year: str):
    if not _YEAR_RE.match(year):
        raise HTTPException(404, "Not found")
    with get_db() as db:
        rows = db.execute(
            "SELECT id, air_date, title, duration_sec, transcript_status "
            "FROM episodes "
            "WHERE substr(air_date, 1, 4) = ? "
            "ORDER BY air_date DESC",
            (year,),
        ).fetchall()
    if not rows:
        raise HTTPException(404, "Not found")

    # Year navigation across the archive.
    with get_db() as db:
        all_years = [r["y"] for r in db.execute(
            "SELECT DISTINCT substr(air_date, 1, 4) AS y FROM episodes "
            "WHERE air_date IS NOT NULL ORDER BY y DESC"
        ).fetchall()]

    # Group by month for readable listings.
    by_month: dict[str, list] = {}
    for r in rows:
        mo = (r["air_date"] or "")[5:7] or "??"
        by_month.setdefault(mo, []).append(r)

    items_html_parts = []
    for mo in sorted(by_month.keys(), reverse=True):
        mo_label = _MONTH_NAMES_EN[int(mo) - 1] if mo.isdigit() and 1 <= int(mo) <= 12 else mo
        items_html_parts.append(f'<h2 class="seo-month">{html.escape(mo_label)} {html.escape(year)}</h2>')
        items_html_parts.append('<ul class="seo-ep-list">')
        for r in by_month[mo]:
            dur = _fmt_duration(r["duration_sec"])
            dur_html = f' <span class="seo-ep-dur">· {html.escape(dur)}</span>' if dur else ""
            items_html_parts.append(
                f'<li class="seo-ep-row">'
                f'<a href="/episode/{html.escape(r["id"])}" class="seo-ep-link">'
                f'<span class="seo-ep-date">{html.escape(r["air_date"] or "")}</span>'
                f'<span class="seo-ep-title">{html.escape(r["title"] or "")}</span>'
                f'</a>{dur_html}'
                f'</li>'
            )
        items_html_parts.append("</ul>")
    items_html = "\n".join(items_html_parts)

    year_nav = " · ".join(
        (f'<strong>{y}</strong>' if y == year
         else f'<a href="/episodes/{y}">{y}</a>')
        for y in all_years
    )

    body = f"""
<nav class="seo-breadcrumb"><a href="/">Home</a> / <span>Episodes from {html.escape(year)}</span></nav>
<h1 class="seo-h1">Bhoot FM episodes from {html.escape(year)}</h1>
<p class="seo-lede">
  {len(rows)} episode{'' if len(rows) == 1 else 's'} of <strong>Bhoot FM</strong>
  (<span lang="bn">ভূত এফএম</span>) — RJ Russell's late-night Bangla horror radio show
  on Radio Foorti 88.0 FM — aired in {html.escape(year)}.
  Click an episode to play it from the exact moment a story begins.
</p>
<nav class="seo-year-nav" aria-label="Browse other years">Browse other years: {year_nav}</nav>
{items_html}
<p class="seo-cta"><a href="/" class="seo-cta-link">← Search inside every episode →</a></p>
"""

    jsonld = [
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Bhoot FM Archive", "item": (PUBLIC_URL or "") + "/"},
                {"@type": "ListItem", "position": 2, "name": f"Episodes from {year}", "item": (PUBLIC_URL or "") + f"/episodes/{year}"},
            ],
        },
        {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": f"Bhoot FM episodes from {year}",
            "description": f"All Bhoot FM episodes aired in {year}, hosted by RJ Russell on Radio Foorti 88.0 FM.",
            "inLanguage": "bn",
            "isPartOf": {"@type": "RadioSeries", "name": "Bhoot FM"},
        },
    ]
    title = f"Bhoot FM episodes from {year} — Bhoot FM Archive"
    desc = (f"All {len(rows)} Bhoot FM episodes from {year} with RJ Russell on Radio Foorti 88.0 FM. "
            f"Stream every episode online for free. ভূত এফএম-এর {year} সালের সব এপিসোড।")
    return Response(
        content=_page_shell(title, desc, f"/episodes/{year}", body, jsonld),
        media_type="text/html; charset=utf-8",
    )


@app.get("/episode/{episode_id}")
def episode_page(episode_id: str):
    if not _EP_ID_RE.match(episode_id):
        raise HTTPException(404, "Not found")
    with get_db() as db:
        ep = db.execute(
            "SELECT id, air_date, title, duration_sec, mp3_url, transcript_status "
            "FROM episodes WHERE id = ?",
            (episode_id,),
        ).fetchone()
        if not ep:
            raise HTTPException(404, "Not found")
        # Adjacent episodes for prev/next nav.
        prev_ep = db.execute(
            "SELECT id, air_date, title FROM episodes "
            "WHERE air_date < ? ORDER BY air_date DESC LIMIT 1",
            (ep["air_date"],),
        ).fetchone()
        next_ep = db.execute(
            "SELECT id, air_date, title FROM episodes "
            "WHERE air_date > ? ORDER BY air_date ASC LIMIT 1",
            (ep["air_date"],),
        ).fetchone()

    year = (ep["air_date"] or "")[:4]
    dur = _fmt_duration(ep["duration_sec"])
    iso_dur = _fmt_iso_duration(ep["duration_sec"])

    prev_html = (
        f'<a href="/episode/{html.escape(prev_ep["id"])}" rel="prev" class="seo-adj">'
        f'← {html.escape(prev_ep["air_date"])}</a>'
    ) if prev_ep else '<span class="seo-adj seo-adj-disabled">← older</span>'
    next_html = (
        f'<a href="/episode/{html.escape(next_ep["id"])}" rel="next" class="seo-adj">'
        f'{html.escape(next_ep["air_date"])} →</a>'
    ) if next_ep else '<span class="seo-adj seo-adj-disabled">newer →</span>'

    # Related episodes: 5 other episodes from the same year (internal linking).
    related_html = ""
    with get_db() as db:
        related = db.execute(
            "SELECT id, air_date, title FROM episodes "
            "WHERE substr(air_date, 1, 4) = ? AND id != ? "
            "ORDER BY air_date DESC LIMIT 5",
            (year, episode_id),
        ).fetchall()
    if related:
        related_items = "".join(
            f'<li><a href="/episode/{html.escape(r["id"])}">'
            f'{html.escape(r["title"] or r["id"])}</a>'
            f' <span class="seo-rel-date">{html.escape(r["air_date"] or "")}</span></li>'
            for r in related
        )
        related_html = f"""
  <aside class="seo-related" aria-label="More episodes from {html.escape(year)}">
    <h2 class="seo-related-title">More from {html.escape(year)}</h2>
    <ul class="seo-related-list">
      {related_items}
    </ul>
  </aside>"""

    body = f"""
<nav class="seo-breadcrumb">
  <a href="/">Home</a> /
  <a href="/episodes/{html.escape(year)}">{html.escape(year)}</a> /
  <span>{html.escape(ep["air_date"] or "")}</span>
</nav>
<article class="seo-episode">
  <p class="seo-episode-kicker">Bhoot FM · <span lang="bn">ভূত এফএম</span> · {html.escape(ep["air_date"] or "")}</p>
  <h1 class="seo-h1 seo-episode-title">{html.escape(ep["title"] or "")}</h1>
  <dl class="seo-episode-meta">
    <div><dt>Aired</dt><dd>{html.escape(ep["air_date"] or "")}</dd></div>
    {'<div><dt>Duration</dt><dd>' + html.escape(dur) + '</dd></div>' if dur else ''}
    <div><dt>Host</dt><dd>RJ Russell</dd></div>
    <div><dt>Station</dt><dd>Radio Foorti 88.0 FM</dd></div>
  </dl>
  <p class="seo-episode-desc">
    Episode of <strong>Bhoot FM</strong> aired on {html.escape(ep["air_date"] or "")}.
    Listener-submitted Bangla ghost stories, paranormal encounters, and chilling
    experiences with RJ Russell. Stream the full episode for free in the player.
  </p>
  <p class="seo-cta">
    <a href="/#/ep/{html.escape(ep["id"])}" class="seo-cta-link">▶ Play this episode</a>
  </p>
  <nav class="seo-adj-nav" aria-label="Adjacent episodes">
    {prev_html}
    <a href="/episodes/{html.escape(year)}" class="seo-adj-up">All {html.escape(year)} episodes</a>
    {next_html}
  </nav>
  {related_html}
</article>
"""

    jsonld = [
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Bhoot FM Archive", "item": (PUBLIC_URL or "") + "/"},
                {"@type": "ListItem", "position": 2, "name": f"Episodes from {year}", "item": (PUBLIC_URL or "") + f"/episodes/{year}"},
                {"@type": "ListItem", "position": 3, "name": ep["title"] or ep["id"], "item": (PUBLIC_URL or "") + f"/episode/{ep['id']}"},
            ],
        },
        {
            "@context": "https://schema.org",
            "@type": "RadioEpisode",
            "name": ep["title"] or "",
            "datePublished": ep["air_date"] or "",
            "inLanguage": "bn",
            **({"duration": iso_dur} if iso_dur else {}),
            "partOfSeries": {
                "@type": "RadioSeries",
                "name": "Bhoot FM",
                "actor": {"@type": "Person", "name": "RJ Russell"},
                "productionCompany": {"@type": "RadioStation", "name": "Radio Foorti 88.0 FM"},
            },
            "url": (PUBLIC_URL or "") + f"/episode/{ep['id']}",
        },
        {
            "@context": "https://schema.org",
            "@type": "AudioObject",
            "name": ep["title"] or "",
            "description": f"Bhoot FM episode aired on {ep['air_date']}. Listener-submitted Bangla ghost stories with RJ Russell on Radio Foorti 88.0 FM.",
            "encodingFormat": "audio/mpeg",
            "contentUrl": ep["mp3_url"] or "",
            "duration": iso_dur if iso_dur else None,
            "inLanguage": "bn",
            "datePublished": ep["air_date"] or "",
            "genre": "Horror",
            "byArtist": {"@type": "Person", "name": "RJ Russell"},
            "isPartOf": {"@type": "RadioSeries", "name": "Bhoot FM"},
        },
    ]

    title = f"{ep['title']} — Bhoot FM ({ep['air_date']}) | Bhoot FM Archive"
    desc = (f"Listen to Bhoot FM episode from {ep['air_date']} with RJ Russell on Radio Foorti 88.0 FM. "
            f"{'Duration: ' + dur + '. ' if dur else ''}Free streaming, jump to any moment. ভূত এফএম।")
    return Response(
        content=_page_shell(title, desc, f"/episode/{ep['id']}", body, jsonld),
        media_type="text/html; charset=utf-8",
    )


# ─── Cache-busting for HTML entry points ────────────────────────────
# After a redeploy, mobile browsers (Edge Android in particular) cling to
# the previously-cached app.js / style.css / banglish.js even when index.html
# revalidates, because those assets have a long max-age. The fix is to make
# each asset URL change when the deploy changes: we rewrite the references
# inside index.html / about.html to include `?v=<version>`. The browser
# treats the new URL as a different resource and fetches it fresh.
#
# Version source order:
#   1. FLY_RELEASE_VERSION env (set automatically by Fly on each deploy)
#   2. Hash of (mtime) for the asset files — picks up local edits during dev
#   3. Process start time — last-resort uniqueness guarantee

import hashlib

def _compute_asset_version() -> str:
    fly = os.environ.get("FLY_RELEASE_VERSION") or os.environ.get("FLY_MACHINE_VERSION")
    if fly:
        return fly[:12]
    parts: list[str] = []
    for name in ("app.js", "banglish.js", "style.css", "index.html", "about.html"):
        p = STATIC_DIR / name
        if p.exists():
            parts.append(f"{name}:{int(p.stat().st_mtime)}")
    if parts:
        return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]
    return str(int(time.time()))


ASSET_VERSION = _compute_asset_version()
log.info("asset version: %s", ASSET_VERSION)

# Regex matches `src="app.js"` / `href="style.css"` etc. so we can splice the
# version query in without parsing HTML. Same-origin paths only — leave CDN
# URLs (Google Fonts, GoatCounter) alone since they don't share our cache.
# Match an asset reference inside a src=/href= attribute, optionally followed
# by an existing query string. We accept (and preserve) any pre-existing query
# so URLs like `a.js?x=1` come out as `a.js?x=1&v=<ver>`.
_ASSET_HREF_RE = re.compile(
    r'((?:src|href)=")'
    r'([^"#?]+\.(?:js|css|svg|png|webmanifest)(?:\?[^"#]*)?)'
    r'(")'
)


def _bust_html_cache(body: str) -> str:
    def sub(m: re.Match) -> str:
        prefix, path, suffix = m.group(1), m.group(2), m.group(3)
        # Skip absolute/protocol URLs — only own-origin assets need busting.
        if path.startswith(("http://", "https://", "//")):
            return m.group(0)
        sep = "&" if "?" in path else "?"
        return f"{prefix}{path}{sep}v={ASSET_VERSION}{suffix}"
    return _ASSET_HREF_RE.sub(sub, body)


def _serve_html_with_busting(filename: str) -> Response:
    path = STATIC_DIR / filename
    if not path.exists():
        raise HTTPException(404)
    body = path.read_text(encoding="utf-8")
    body = _bust_html_cache(body)
    # `no-cache` (not `no-store`) lets the browser keep the file but forces it
    # to revalidate every load. With ETag/Last-Modified the server returns 304
    # when unchanged — cheap, and guarantees users see the new asset URLs the
    # moment a deploy ships.
    return Response(
        content=body,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-cache", "ETag": f'W/"{ASSET_VERSION}"'},
    )


@app.get("/")
def serve_index():
    return _serve_html_with_busting("index.html")


@app.get("/index.html")
def serve_index_html():
    return _serve_html_with_busting("index.html")


@app.get("/about.html")
def serve_about_html():
    return _serve_html_with_busting("about.html")


# Static files — mounted last so /api/* and /sitemap.xml and the HTML
# rewrites above all win. The mount handles every other static asset
# (JS, CSS, fonts, images) directly from disk.
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=False), name="static")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="127.0.0.1", port=port)

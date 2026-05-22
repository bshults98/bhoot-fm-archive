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


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not DB_PATH.exists():
        raise RuntimeError(f"{DB_PATH.name} not found. Run ingest.py first.")
    # Warm a connection once at startup so PRAGMA defaults are applied and
    # to surface schema problems immediately rather than on first request.
    with get_db() as db:
        db.execute("SELECT 1 FROM episodes LIMIT 1").fetchone()
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
    "img-src 'self' data:; "
    # Allow audio from our origin, the IA CDN (the final home), and the
    # legacy bhoot-fm.com mirror used as fallback during transition.
    "media-src 'self' "
    "https://archive.org https://*.archive.org "
    "http://dl.bhoot-fm.com https://dl.bhoot-fm.com blob:; "
    "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    # gc.zgo.at is GoatCounter's analytics script (privacy-friendly, no cookies).
    "script-src 'self' https://gc.zgo.at; "
    "connect-src 'self' https://gc.zgo.at; "
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
            "e.mp3_url AS mp3_url, e.local_mp3_path AS local_mp3_path "
            "FROM segments_fts "
            "JOIN segments s ON s.id = segments_fts.rowid "
            "JOIN episodes e ON e.id = s.episode_id "
            "WHERE segments_fts MATCH ? "
        )
        params2: list = [match]
        if episode_id:
            sql += "AND s.episode_id = ? "
            params2.append(episode_id)
        sql += "ORDER BY e.air_date DESC, s.start_sec ASC LIMIT ? OFFSET ?"
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
        results.append(d)

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


@app.get("/sitemap.xml")
def sitemap():
    base = PUBLIC_URL or ""
    with get_db() as db:
        episodes = db.execute(
            "SELECT id, air_date FROM episodes "
            "WHERE transcript_status = 'done' "
            "ORDER BY air_date DESC"
        ).fetchall()
    urls = [
        f"<url><loc>{base}/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>"
    ]
    for r in episodes:
        urls.append(
            f"<url><loc>{base}/#/ep/{r['id']}</loc>"
            f"<lastmod>{r['air_date']}</lastmod>"
            f"<changefreq>yearly</changefreq><priority>0.7</priority></url>"
        )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls) +
        "\n</urlset>\n"
    )
    return Response(content=body, media_type="application/xml")


# Static files — mounted last so /api/* and /sitemap.xml win.
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="127.0.0.1", port=port)

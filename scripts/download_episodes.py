"""
BhootFM episode downloader.

Iterates the hand-scouted index from episodes_index.py, finds the actual
mp3 URL for each episode (direct or via MediaFire scrape), and downloads
into audio/YYYY/. Maintains manifest.json so it's resumable.

Usage
-----
    python scripts/download_episodes.py                 # download everything missing
    python scripts/download_episodes.py --year 2019     # one year only
    python scripts/download_episodes.py --date 2019-04-26  # single episode
    python scripts/download_episodes.py --dry-run       # just resolve URLs
    python scripts/download_episodes.py --limit 10      # cap how many

Politeness: ~1.5 sec between requests, retries with backoff, common UA.
"""

import argparse
import hashlib
import json
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

# Make episodes_index importable when running from project root.
sys.path.insert(0, str(Path(__file__).parent))
from episodes_index import all_episodes  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = ROOT / "audio"
MANIFEST = ROOT / "manifest.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"}

REQUEST_DELAY_SEC = (1.0, 2.0)   # sleep range between page requests


# ─── HTTP helpers ────────────────────────────────────────────────────

def http_get(url: str, *, timeout: int = 30, max_retries: int = 4) -> bytes:
    last_err = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = e
            backoff = 1.5 * (2 ** attempt) + random.random()
            print(f"    .. retry {attempt + 1}/{max_retries} after {backoff:.1f}s ({e})")
            time.sleep(backoff)
    raise RuntimeError(f"GET {url} failed: {last_err}")


def http_head(url: str, *, timeout: int = 20) -> tuple[int, dict]:
    """Return (status_code, headers) for a HEAD request."""
    try:
        req = urllib.request.Request(url, headers=HEADERS, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception:
        return 0, {}


def http_download(url: str, dest: Path, *, timeout: int = 600) -> int:
    """Stream-download to dest (atomic via .tmp + rename). Returns bytes."""
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers=HEADERS)
    written = 0
    with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 16)  # 64k
            if not chunk:
                break
            f.write(chunk)
            written += len(chunk)
    tmp.replace(dest)
    return written


# ─── URL resolution ──────────────────────────────────────────────────

DIRECT_URL_RX = re.compile(r"http://dl\.bhoot-fm\.com/[^\s\"'<>]+\.mp3")
MEDIAFIRE_RX = re.compile(r"http://www\.mediafire\.com/(?:download/|file/|\?)[^\s\"'<>]+", re.IGNORECASE)


def resolve_mp3(episode_html_url: str) -> tuple[Optional[str], str]:
    """Inspect the episode HTML page and return (mp3_url, source_label).
    source_label ∈ {'dl.bhoot-fm.com', 'mediafire'}."""
    html = http_get(episode_html_url).decode("utf-8", errors="replace")
    # Prefer direct dl.bhoot-fm.com link if present (newer pages have it).
    m = DIRECT_URL_RX.search(html)
    if m:
        return m.group(0), "dl.bhoot-fm.com"
    # Else look for a MediaFire URL.
    m = MEDIAFIRE_RX.search(html)
    if m:
        mf_url = m.group(0)
        # MediaFire 'download' URLs are the legacy form that 302s to the file
        # page; modern form is /file/<hash>/<name>/file. Both pages have a
        # button with the real downloadXX.mediafire.com URL inside.
        try:
            real = resolve_mediafire(mf_url)
            if real:
                return real, "mediafire"
        except Exception as e:
            print(f"    ! mediafire resolve failed for {mf_url}: {e}")
            return mf_url, "mediafire-unresolved"
    return None, "none"


MF_DOWNLOAD_BTN_RX = re.compile(
    r'href="(https?://download[0-9]+\.mediafire\.com/[^"]+)"',
    re.IGNORECASE,
)


def resolve_mediafire(mf_url: str) -> Optional[str]:
    html = http_get(mf_url).decode("utf-8", errors="replace")
    m = MF_DOWNLOAD_BTN_RX.search(html)
    return m.group(1) if m else None


def predicted_direct_mp3(date_iso: str) -> str:
    """The legacy predictable pattern for dl.bhoot-fm.com mp3 URLs."""
    year = date_iso.split("-")[0]
    return (f"http://dl.bhoot-fm.com/{year}/"
            f"Bhoot-FM_{date_iso}_(Bhoot-FM.com).mp3")


# ─── Manifest ────────────────────────────────────────────────────────

def load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {}


def save_manifest(m: dict):
    MANIFEST.write_text(json.dumps(m, indent=2), encoding="utf-8")


# ─── Per-episode action ──────────────────────────────────────────────

def local_path(date_iso: str) -> Path:
    year = date_iso.split("-")[0]
    return AUDIO_DIR / year / f"Bhoot-FM_{date_iso}.mp3"


def process_episode(date_iso: str, html_url: str, manifest: dict,
                    dry_run: bool = False) -> dict:
    """Return the manifest entry after attempting to fetch."""
    entry = manifest.get(date_iso, {})
    dest = local_path(date_iso)

    # Already downloaded and looks OK? skip.
    if entry.get("status") == "ok" and dest.exists() and dest.stat().st_size > 100_000:
        return entry

    print(f"[{date_iso}] resolving ...")
    # 1) Try the predicted direct URL first (cheap HEAD).
    pred = predicted_direct_mp3(date_iso.split("-pt")[0])  # part-N variants share base date
    status, headers = http_head(pred)
    mp3_url: Optional[str] = None
    source = ""
    if 200 <= status < 300:
        mp3_url, source = pred, "dl.bhoot-fm.com (predicted)"
    else:
        # 2) Fall back to scraping the episode page.
        try:
            mp3_url, source = resolve_mp3(html_url)
        except Exception as e:
            entry.update(status="resolve_failed", error=str(e),
                         html_url=html_url, attempted_at=int(time.time()))
            return entry

    if not mp3_url:
        entry.update(status="no_mp3_found", html_url=html_url,
                     attempted_at=int(time.time()))
        print(f"  ! no mp3 url found")
        return entry

    entry.update(html_url=html_url, mp3_url=mp3_url, source=source)
    print(f"  -> {source}: {mp3_url}")

    if dry_run:
        entry["status"] = "resolved (dry-run)"
        return entry

    print(f"  downloading -> {dest.relative_to(ROOT)}")
    t0 = time.time()
    try:
        bytes_written = http_download(mp3_url, dest)
        entry.update(
            status="ok",
            size=bytes_written,
            downloaded_at=int(time.time()),
            elapsed_sec=round(time.time() - t0, 1),
        )
        print(f"  + {bytes_written / 1e6:.1f} MB in {entry['elapsed_sec']}s")
    except Exception as e:
        entry.update(status="download_failed", error=str(e),
                     attempted_at=int(time.time()))
        print(f"  ! download failed: {e}")
    return entry


# ─── Main ────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, help="Only this year")
    ap.add_argument("--date", help="Only this date (YYYY-MM-DD)")
    ap.add_argument("--limit", type=int, default=0, help="Cap episodes processed (0 = all)")
    ap.add_argument("--dry-run", action="store_true", help="Resolve URLs only, don't download")
    ap.add_argument("--force", action="store_true",
                    help="Re-download even if status=ok")
    args = ap.parse_args()

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()

    episodes = all_episodes()
    if args.year:
        episodes = [e for e in episodes if e[0].startswith(str(args.year))]
    if args.date:
        episodes = [e for e in episodes if e[0] == args.date or e[0].startswith(args.date)]
    if args.force:
        for k in list(manifest.keys()):
            if manifest[k].get("status") == "ok":
                manifest[k]["status"] = "pending"

    if args.limit:
        episodes = episodes[: args.limit]

    print(f"Processing {len(episodes)} episodes (dry_run={args.dry_run})")
    n_ok = n_fail = n_skip = 0
    for i, (date_iso, html_url, _) in enumerate(episodes, 1):
        prior = manifest.get(date_iso, {})
        if (not args.force) and prior.get("status") == "ok" \
                and local_path(date_iso).exists():
            print(f"({i}/{len(episodes)}) [{date_iso}] skip (already ok)")
            n_skip += 1
            continue
        print(f"({i}/{len(episodes)}) ", end="")
        entry = process_episode(date_iso, html_url, manifest,
                                dry_run=args.dry_run)
        manifest[date_iso] = entry
        if entry.get("status") == "ok":
            n_ok += 1
        else:
            n_fail += 1
        # Persist progress every episode (cheap and crash-safe).
        save_manifest(manifest)
        # Be polite.
        time.sleep(random.uniform(*REQUEST_DELAY_SEC))

    print()
    print(f"Done. {n_ok} ok, {n_fail} failed, {n_skip} skipped.")
    print(f"Manifest: {MANIFEST}")


if __name__ == "__main__":
    main()

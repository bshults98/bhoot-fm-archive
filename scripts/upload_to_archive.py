"""
Upload all local mp3s to the Internet Archive.

Each episode becomes its own IA item identified as `bhoot-fm-YYYY-MM-DD`,
with structured metadata (title, creator, language, subject, year).

Resumable: writes ia_manifest.json tracking which uploads succeeded.

Prerequisites
-------------
1. Free Internet Archive account: https://archive.org/account/signup
2. Configure CLI once (interactive — asks for your email + password):
        ia configure
   This writes ~/.config/internetarchive/ia.ini with your S3-style keys.
   (You can also pass --access-key / --secret-key to this script.)
3. Run:  python scripts/upload_to_archive.py
"""

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent))

from internetarchive import upload, get_session, get_item  # noqa: E402


ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = ROOT / "audio"
LOCAL_MANIFEST = ROOT / "manifest.json"
IA_MANIFEST = ROOT / "ia_manifest.json"

DEFAULT_COLLECTION = "opensource_audio"   # publicly available IA collection
LANGUAGE = "ben"   # Bengali ISO 639-3
CREATOR = "RJ Russell"
PUBLISHER = "Radio Foorti 88.0 FM"
DESCRIPTION_TMPL = (
    "Bhoot FM is a Bangla-language horror and paranormal storytelling radio "
    "show that aired on Radio Foorti 88.0 FM, hosted by RJ Russell. "
    "Episode originally broadcast on {date_human}. "
    "Archived for preservation. Contact the original rights holder for "
    "commercial use."
)
SUBJECT_TAGS = [
    "Bhoot FM", "ভূত এফএম", "RJ Russell", "Radio Foorti", "Bangladesh",
    "Bangla horror", "Bengali horror", "ghost stories", "paranormal",
    "radio drama", "অলৌকিক",
]


def identifier_for(date_iso: str) -> str:
    """IA identifiers: lowercase, alphanumeric + dash. Stable per episode."""
    # Handle multi-part dates like '2011-10-07-pt1' → 'bhoot-fm-2011-10-07-pt1'
    return f"bhoot-fm-{date_iso}"


def human_date(date_iso: str) -> str:
    from datetime import date
    base = date_iso.split("-pt")[0]
    try:
        d = date.fromisoformat(base)
        return d.strftime("%d %B %Y")
    except ValueError:
        return date_iso


def load_manifest(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_manifest(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def find_local_mp3(date_iso: str) -> Optional[Path]:
    """Match a manifest entry (which uses the episode id) to the actual file."""
    year = date_iso.split("-")[0]
    candidate = AUDIO_DIR / year / f"Bhoot-FM_{date_iso}.mp3"
    if candidate.exists():
        return candidate
    # Multi-part episodes: stripped id format
    base = date_iso.split("-pt")[0]
    candidate = AUDIO_DIR / year / f"Bhoot-FM_{base}.mp3"
    if candidate.exists():
        return candidate
    return None


def upload_one(date_iso: str, mp3: Path, session, dry_run: bool = False,
               retries: int = 10, retries_sleep: int = 30) -> dict:
    ident = identifier_for(date_iso)
    year = date_iso.split("-")[0]
    metadata = {
        "title": f"Bhoot FM — {human_date(date_iso)}",
        "mediatype": "audio",
        "collection": DEFAULT_COLLECTION,
        "creator": CREATOR,
        "publisher": PUBLISHER,
        "date": date_iso.split("-pt")[0],
        "year": year,
        "language": LANGUAGE,
        "subject": SUBJECT_TAGS,
        "description": DESCRIPTION_TMPL.format(date_human=human_date(date_iso)),
        "licenseurl": "",                    # leave blank; falls under fair-use archival
        "source": "https://bhoot-fm.com",
        "scanner": "BhootFM Archive uploader v1",
    }
    # IA file name inside the item — keep it clean and predictable.
    target_name = f"Bhoot-FM_{date_iso.split('-pt')[0]}.mp3"
    if dry_run:
        return {"status": "dry_run", "identifier": ident, "filename": target_name}

    t0 = time.time()
    print(f"  uploading {mp3.name} -> archive.org/details/{ident}")
    try:
        responses = upload(
            ident,
            files={target_name: str(mp3)},
            metadata=metadata,
            access_key=session.access_key,
            secret_key=session.secret_key,
            retries=retries,
            retries_sleep=retries_sleep,
            verbose=False,
            queue_derive=True,
        )
    except Exception as e:
        return {"status": "failed", "error": str(e),
                "identifier": ident, "filename": target_name}

    ok = all(r.status_code in (200, 201) for r in responses)
    return {
        "status": "ok" if ok else "partial",
        "identifier": ident,
        "filename": target_name,
        "url": f"https://archive.org/download/{ident}/{target_name}",
        "elapsed_sec": round(time.time() - t0, 1),
        "http_codes": [r.status_code for r in responses],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="Cap number of uploads this run (0 = all)")
    ap.add_argument("--year", type=int, help="Only this year")
    ap.add_argument("--date", help="Only this date (YYYY-MM-DD)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="Re-upload even if status=ok in ia_manifest")
    ap.add_argument("--access-key", help="IA S3 access key (else uses ia.ini)")
    ap.add_argument("--secret-key", help="IA S3 secret key (else uses ia.ini)")
    ap.add_argument("--workers", type=int, default=4,
                    help="Parallel upload workers (default 4; IA throttles "
                         "if too high — 4–8 is the sweet spot)")
    ap.add_argument("--retries", type=int, default=10,
                    help="Retries per upload before giving up (default 10)")
    ap.add_argument("--retries-sleep", type=int, default=30,
                    help="Seconds between retries (default 30)")
    ap.add_argument("--inter-delay", type=float, default=0.0,
                    help="Sleep between starting uploads, sec "
                         "(use 2-5 when single-worker + throttled)")
    args = ap.parse_args()
    if args.workers < 1 or args.workers > 16:
        print("--workers must be between 1 and 16", file=sys.stderr)
        return 2

    if not LOCAL_MANIFEST.exists():
        print(f"ERROR: {LOCAL_MANIFEST.name} not found. "
              f"Run download_episodes.py first.", file=sys.stderr)
        return 2

    local = json.loads(LOCAL_MANIFEST.read_text(encoding="utf-8"))
    ia = load_manifest(IA_MANIFEST)

    # Prefer explicit keys (CLI/env); else let internetarchive load ia.ini.
    explicit_access = args.access_key or os.environ.get("IA_S3_ACCESS_KEY")
    explicit_secret = args.secret_key or os.environ.get("IA_S3_SECRET_KEY")
    if explicit_access and explicit_secret:
        session = get_session({"s3": {"access": explicit_access,
                                      "secret": explicit_secret}})
    else:
        session = get_session()  # reads ~/.config/internetarchive/ia.ini
    if not (session.access_key and session.secret_key):
        print("ERROR: No IA S3 keys found. Run `ia configure` once, or pass "
              "--access-key/--secret-key, or set IA_S3_ACCESS_KEY/"
              "IA_S3_SECRET_KEY env vars.\n"
              "Get keys at: https://archive.org/account/s3.php",
              file=sys.stderr)
        return 2

    # Build the work list ordered chronologically (oldest first).
    todo = []
    for date_iso, entry in sorted(local.items()):
        if args.year and not date_iso.startswith(str(args.year)):
            continue
        if args.date and not (date_iso == args.date or date_iso.startswith(args.date)):
            continue
        if entry.get("status") != "ok":
            continue
        prior = ia.get(date_iso, {})
        if (not args.force) and prior.get("status") == "ok":
            continue
        mp3 = find_local_mp3(date_iso)
        if not mp3:
            ia[date_iso] = {"status": "no_local_mp3"}
            continue
        todo.append((date_iso, mp3))

    if args.limit:
        todo = todo[: args.limit]

    print(f"To upload: {len(todo)} episodes "
          f"(dry_run={args.dry_run}, workers={args.workers})")
    if not todo:
        print("Nothing to do — everything is already on IA.")
        return 0

    manifest_lock = threading.Lock()
    delay_lock = threading.Lock()      # serialize the inter-upload wait
    counters = {"ok": 0, "fail": 0, "done": 0}
    t_start = time.time()
    cancel_flag = threading.Event()

    def do_one(date_iso: str, mp3: Path):
        if cancel_flag.is_set():
            return date_iso, {"status": "skipped_cancel"}
        # Pace ourselves IN THE WORKER so the main thread never blocks
        # waiting to submit — it can drain results immediately.
        if args.inter_delay > 0:
            with delay_lock:
                if cancel_flag.is_set():
                    return date_iso, {"status": "skipped_cancel"}
                time.sleep(args.inter_delay)
        if cancel_flag.is_set():
            return date_iso, {"status": "skipped_cancel"}
        try:
            res = upload_one(date_iso, mp3, session, dry_run=args.dry_run,
                             retries=args.retries,
                             retries_sleep=args.retries_sleep)
        except Exception as e:
            res = {"status": "failed", "error": f"{type(e).__name__}: {e}"}
        res["attempted_at"] = int(time.time())
        # Manifest writes serialized via the lock; one fsync per finish is
        # OK volume-wise and means a crash never loses more than one item.
        with manifest_lock:
            ia[date_iso] = res
            save_manifest(IA_MANIFEST, ia)
            counters["done"] += 1
            if res["status"] == "ok":
                counters["ok"] += 1
            elif res["status"] != "dry_run":
                counters["fail"] += 1
        return date_iso, res

    ex = ThreadPoolExecutor(max_workers=args.workers)
    futures = {ex.submit(do_one, d, m): d for d, m in todo}
    print(f"submitted {len(futures)} task{'s' if len(futures) != 1 else ''}, "
          f"watching for results...", flush=True)
    try:
        for fut in as_completed(futures):
            date_iso, res = fut.result()
            tag = res["status"]
            n_done = counters["done"]
            if tag == "ok":
                print(f"  + [{date_iso}] {res.get('elapsed_sec', '?')}s "
                      f"({n_done}/{len(todo)})", flush=True)
            elif tag == "dry_run":
                print(f"  · [{date_iso}] (dry-run) ({n_done}/{len(todo)})",
                      flush=True)
            elif tag == "skipped_cancel":
                pass  # quiet during cancellation
            else:
                err = (res.get('error') or '').strip()
                print(f"  ! [{date_iso}] {tag}: {err[:120]} "
                      f"({n_done}/{len(todo)})", flush=True)
            # Periodic ETA so user sees throughput
            if n_done % max(1, args.workers) == 0 and n_done < len(todo):
                elapsed = time.time() - t_start
                avg = elapsed / n_done
                eta = avg * (len(todo) - n_done)
                rate = n_done / elapsed if elapsed else 0
                print(f"  -- {counters['ok']} ok, {counters['fail']} failed, "
                      f"{rate * 60:.1f}/min,  ETA "
                      f"{int(eta // 60)}m{int(eta % 60):02d}s", flush=True)
    except KeyboardInterrupt:
        print("\n^C — cancelling pending uploads and stopping ASAP.", flush=True)
        cancel_flag.set()
        # Cancel any futures not yet started (no wait, no extra work).
        cancelled = 0
        for f in futures:
            if f.cancel():
                cancelled += 1
        print(f"  cancelled {cancelled} pending. "
              f"Workers will finish current uploads or abort on next check.",
              flush=True)
        try:
            ex.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            ex.shutdown(wait=False)
        return 130
    finally:
        # Normal completion: clean shutdown.
        if not cancel_flag.is_set():
            ex.shutdown(wait=True)

    elapsed = time.time() - t_start
    rate_per_min = (counters["ok"] + counters["fail"]) / elapsed * 60 if elapsed else 0
    print()
    print(f"Done. {counters['ok']} ok, {counters['fail']} failed in "
          f"{int(elapsed // 60)}m{int(elapsed % 60):02d}s ({rate_per_min:.1f}/min).")
    print(f"Manifest: {IA_MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

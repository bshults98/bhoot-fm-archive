"""
Produce archive.prod.db from archive.db, stripping local-only fields so the
deployed server falls back to dl.bhoot-fm.com URLs (we don't host audio).

Idempotent. Run before every deploy (redeploy.bat does this for you).
"""

import json
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "archive.db"
DST = ROOT / "archive.prod.db"
IA_MANIFEST = ROOT / "ia_manifest.json"


def main() -> int:
    if not SRC.exists():
        print(f"ERROR: {SRC} not found. Run `python ingest.py` first.", file=sys.stderr)
        return 1

    print(f"Copying {SRC.name} -> {DST.name}")
    shutil.copy2(SRC, DST)

    with sqlite3.connect(DST) as db:
        # Strip local file paths so the server doesn't try to open files that
        # don't exist on the production VM.
        n = db.execute("UPDATE episodes SET local_mp3_path = NULL").rowcount
        db.commit()

        # If we have IA upload manifest, rewrite mp3_url so production points
        # at archive.org URLs instead of dl.bhoot-fm.com.
        n_ia = 0
        if IA_MANIFEST.exists():
            ia = json.loads(IA_MANIFEST.read_text(encoding="utf-8"))
            for episode_id, entry in ia.items():
                url = entry.get("url")
                if entry.get("status") == "ok" and url:
                    db.execute(
                        "UPDATE episodes SET mp3_url = ? WHERE id = ?",
                        (url, episode_id),
                    )
                    n_ia += 1
            db.commit()

        # Compact the file (saves a few MB).
        db.execute("VACUUM")

    eps, segs, done = sqlite3.connect(DST).execute(
        "SELECT (SELECT COUNT(*) FROM episodes), "
        "       (SELECT COUNT(*) FROM segments), "
        "       (SELECT COUNT(*) FROM episodes WHERE transcript_status='done')"
    ).fetchone()
    size_mb = DST.stat().st_size / 1e6
    print(f"  - cleared local_mp3_path on {n} rows")
    if IA_MANIFEST.exists():
        print(f"  - rewrote mp3_url to IA on {n_ia} rows")
    else:
        print(f"  - (no ia_manifest.json yet; audio will redirect to dl.bhoot-fm.com)")
    print(f"  - {DST.name}: {size_mb:.1f} MB, "
          f"{eps} episodes ({done} with transcripts), {segs} segments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

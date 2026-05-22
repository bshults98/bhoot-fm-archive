"""
After episodes are uploaded to Internet Archive, rewrite mp3_url in
archive.db to point at IA URLs. Run before prepare_production_db.py.

If an episode hasn't been uploaded yet, its mp3_url is left as-is (still
pointing at dl.bhoot-fm.com — the original fallback).

Usage
-----
    python scripts/relink_to_archive.py
"""

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "archive.db"
IA_MANIFEST = ROOT / "ia_manifest.json"


def main() -> int:
    if not DB.exists():
        print(f"ERROR: {DB.name} not found. Run ingest.py first.", file=sys.stderr)
        return 2
    if not IA_MANIFEST.exists():
        print(f"ERROR: {IA_MANIFEST.name} not found. "
              f"Run scripts/upload_to_archive.py first.", file=sys.stderr)
        return 2

    ia = json.loads(IA_MANIFEST.read_text(encoding="utf-8"))
    conn = sqlite3.connect(DB)
    n_ok = n_skip = 0
    for episode_id, entry in ia.items():
        url = entry.get("url")
        if entry.get("status") != "ok" or not url:
            n_skip += 1
            continue
        conn.execute(
            "UPDATE episodes SET mp3_url = ? WHERE id = ?",
            (url, episode_id),
        )
        n_ok += 1
    conn.commit()
    conn.close()
    print(f"Re-linked {n_ok} episodes to IA URLs. Skipped {n_skip}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

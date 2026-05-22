"""
Populate archive.db from:
1. manifest.json (one entry per episode the downloader handled), AND
2. JSON sidecars produced by the transcriber.

JSON ingestion is preferred — it's structured (no docx parsing) and
includes speaker labels when diarization ran. The script still accepts
folders of .docx files for backwards compatibility.

Usage
-----
    python ingest.py                                # uses manifest.json + transcripts/
    python ingest.py --transcripts <dir>            # custom transcripts dir
    python ingest.py --legacy-docx <dir>            # parse old docx files
"""

import argparse
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

# ─── Paths ───────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "archive.db"
SCHEMA_PATH = ROOT / "schema.sql"
MANIFEST_PATH = ROOT / "manifest.json"
DEFAULT_TRANSCRIPTS = ROOT / "transcripts"
DEFAULT_AUDIO = ROOT / "audio"

# ─── Filename date detection (kept for legacy docx mode) ────────────
# NOTE: ordering of alternation matters. `0?[1-9]` was tried before `[12]\d`,
# which made "13" match as just "1". Use two-digit forms exclusively — our
# filenames are always zero-padded ISO dates anyway.
DATE_RX = [
    re.compile(r"(?P<y>20\d{2})[-_](?P<m>0[1-9]|1[0-2])[-_](?P<d>0[1-9]|[12]\d|3[01])"),
    re.compile(r"\[?(?P<d>0[1-9]|[12]\d|3[01])[-_](?P<m>0[1-9]|1[0-2])[-_](?P<y>20\d{2})\]?"),
]
MONTH_NAMES = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6,
    "july": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9, "october": 10, "oct": 10,
    "november": 11, "nov": 11, "december": 12, "dec": 12,
}
NAMED_DATE_RX_DMY = re.compile(
    r"(?P<d>\d{1,2})\s+(?P<m>" + "|".join(sorted(MONTH_NAMES, key=len, reverse=True)) + r")\s+(?P<y>20\d{2})",
    re.IGNORECASE)
NAMED_DATE_RX_MDY = re.compile(
    r"(?P<m>" + "|".join(sorted(MONTH_NAMES, key=len, reverse=True)) + r")\s+(?P<d>\d{1,2})[\s,]+(?P<y>20\d{2})",
    re.IGNORECASE)


def extract_date(s: str) -> Optional[date]:
    name = s.lower()
    for rx in DATE_RX:
        m = rx.search(name)
        if m:
            try:
                return date(int(m["y"]), int(m["m"]), int(m["d"]))
            except ValueError:
                continue
    for rx in (NAMED_DATE_RX_DMY, NAMED_DATE_RX_MDY):
        m = rx.search(name)
        if m:
            try:
                return date(int(m["y"]), MONTH_NAMES[m["m"].lower()], int(m["d"]))
            except ValueError:
                continue
    return None


# ─── DB ──────────────────────────────────────────────────────────────
def init_db(conn: sqlite3.Connection):
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def upsert_episode(conn: sqlite3.Connection, *, episode_id: str, air_date: str,
                   title: str, mp3_url: str, local_mp3_path: Optional[str],
                   duration_sec: Optional[float], status: str):
    conn.execute("""
        INSERT INTO episodes
            (id, air_date, title, mp3_url, local_mp3_path, duration_sec, transcript_status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title,
            mp3_url = excluded.mp3_url,
            local_mp3_path = COALESCE(excluded.local_mp3_path, episodes.local_mp3_path),
            duration_sec = COALESCE(excluded.duration_sec, episodes.duration_sec),
            transcript_status = excluded.transcript_status
    """, (episode_id, air_date, title, mp3_url, local_mp3_path,
          duration_sec, status))


def replace_segments(conn: sqlite3.Connection, episode_id: str,
                     segments: list[dict]):
    conn.execute("DELETE FROM segments WHERE episode_id = ?", (episode_id,))
    rows = [(episode_id, float(s["start"]), float(s["end"]),
             s["text"].strip(), s.get("speaker")) for s in segments
            if (s.get("text") or "").strip()]
    conn.executemany(
        "INSERT INTO segments (episode_id, start_sec, end_sec, text, speaker) "
        "VALUES (?, ?, ?, ?, ?)", rows)
    return len(rows)


# ─── Sources ─────────────────────────────────────────────────────────
def ingest_manifest(conn: sqlite3.Connection,
                    manifest_path: Path = MANIFEST_PATH) -> int:
    """Register every episode the downloader knows about (even those without
    transcripts yet). Idempotent."""
    if not manifest_path.exists():
        print(f"  ! manifest not found at {manifest_path}, skipping manifest ingest")
        return 0
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    n = 0
    for episode_id, entry in data.items():
        try:
            air = date.fromisoformat(episode_id.split("-pt")[0])
        except ValueError:
            print(f"  ! bad id in manifest: {episode_id}")
            continue
        title = f"Bhoot FM — {air.strftime('%d %b %Y')}"
        if "-pt" in episode_id:
            title += f" (Part {episode_id.rsplit('-pt', 1)[1]})"
        local_path = (ROOT / "audio" / str(air.year) /
                      f"Bhoot-FM_{episode_id}.mp3")
        local = str(local_path) if local_path.exists() else None
        upsert_episode(
            conn,
            episode_id=episode_id,
            air_date=air.isoformat(),
            title=title,
            mp3_url=entry.get("mp3_url") or "",
            local_mp3_path=local,
            duration_sec=None,
            status="pending",
        )
        n += 1
    return n


def ingest_json_transcripts(conn: sqlite3.Connection, root: Path) -> int:
    if not root.exists():
        print(f"  (no transcripts dir at {root})")
        return 0
    n = 0
    for jpath in sorted(root.rglob("*.json")):
        if jpath.name == "manifest.json":
            continue
        try:
            payload = json.loads(jpath.read_text(encoding="utf-8"))
            if "segments" not in payload:
                continue
        except Exception as e:
            print(f"  ! {jpath.name}: parse failed: {e}")
            continue

        air = extract_date(jpath.stem) or extract_date(
            payload.get("source_file", ""))
        if not air:
            print(f"  ! {jpath.name}: no date in filename, skipping")
            continue
        eid = air.isoformat()
        title = f"Bhoot FM — {air.strftime('%d %b %Y')}"

        upsert_episode(
            conn,
            episode_id=eid,
            air_date=eid,
            title=title,
            mp3_url=f"http://dl.bhoot-fm.com/{air.year}/Bhoot-FM_{eid}_(Bhoot-FM.com).mp3",
            local_mp3_path=None,  # leave manifest's value alone
            duration_sec=payload.get("duration_sec"),
            status="done",
        )
        added = replace_segments(conn, eid, payload["segments"])
        print(f"  + {eid}: {added} segments from {jpath.name}")
        n += 1
    return n


def ingest_legacy_docx(conn: sqlite3.Connection, root: Path) -> int:
    """Fallback: parse old .docx transcripts via paragraph timestamps."""
    try:
        from docx import Document
    except ImportError:
        print("python-docx not installed; cannot ingest docx.")
        return 0
    TS_RX = re.compile(r"^\[(\d{1,2}):(\d{2}):(\d{2})\]")
    n = 0
    for path in sorted(root.rglob("*.docx")):
        air = extract_date(path.name)
        if not air:
            print(f"  ! {path.name}: no date in filename, skip")
            continue
        eid = air.isoformat()
        doc = Document(str(path))
        segments = []
        current_start = None
        for p in doc.paragraphs:
            t = (p.text or "").strip()
            if not t:
                continue
            m = TS_RX.match(t)
            if m:
                current_start = (int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]))
                continue
            if current_start is None:
                continue
            if not any("ঀ" <= c <= "৿" for c in t):
                continue
            segments.append({"start": current_start, "end": current_start + 30,
                             "text": t, "speaker": None})
        if not segments:
            continue
        for i in range(len(segments) - 1):
            segments[i]["end"] = segments[i + 1]["start"]
        title = f"Bhoot FM — {air.strftime('%d %b %Y')}"
        upsert_episode(
            conn,
            episode_id=eid, air_date=eid, title=title,
            mp3_url=f"http://dl.bhoot-fm.com/{air.year}/Bhoot-FM_{eid}_(Bhoot-FM.com).mp3",
            local_mp3_path=None,
            duration_sec=segments[-1]["start"] if segments else None,
            status="done",
        )
        replace_segments(conn, eid, segments)
        print(f"  + {eid}: {len(segments)} segments (legacy docx)")
        n += 1
    return n


# ─── Main ────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcripts", default=str(DEFAULT_TRANSCRIPTS),
                    help="Folder of .json transcripts produced by transcriber")
    ap.add_argument("--legacy-docx", default=None,
                    help="Folder of .docx files to parse (backwards compat)")
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--no-manifest", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON;")
    init_db(conn)

    print(f"DB: {args.db}")
    if not args.no_manifest:
        print(f"\n[1/3] Manifest from {MANIFEST_PATH.name}")
        nm = ingest_manifest(conn)
        print(f"  -> {nm} episodes registered")

    print(f"\n[2/3] JSON transcripts from {args.transcripts}")
    nj = ingest_json_transcripts(conn, Path(args.transcripts))
    print(f"  -> {nj} transcripts loaded")

    if args.legacy_docx:
        print(f"\n[3/3] Legacy docx from {args.legacy_docx}")
        nd = ingest_legacy_docx(conn, Path(args.legacy_docx))
        print(f"  -> {nd} legacy transcripts loaded")

    conn.commit()
    eps = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
    done = conn.execute("SELECT COUNT(*) FROM episodes WHERE transcript_status='done'").fetchone()[0]
    segs = conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
    print(f"\nFinal: {eps} episodes ({done} with transcripts), {segs} segments.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

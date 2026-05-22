-- BhootFM Archive schema. SQLite with FTS5 for full-text Bangla search.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS episodes (
    id              TEXT PRIMARY KEY,         -- e.g. '2019-04-26'
    air_date        TEXT NOT NULL,            -- ISO date
    title           TEXT NOT NULL,
    mp3_url         TEXT NOT NULL,            -- Source URL (dl.bhoot-fm.com)
    local_mp3_path  TEXT,                     -- Path to local mp3 (audio/YYYY/...)
    duration_sec    REAL,
    transcript_status TEXT DEFAULT 'pending', -- 'pending' | 'done' | 'failed'
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS segments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id  TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    start_sec   REAL NOT NULL,
    end_sec     REAL NOT NULL,
    text        TEXT NOT NULL,
    speaker     TEXT
);

CREATE INDEX IF NOT EXISTS idx_segments_episode ON segments(episode_id, start_sec);

-- FTS5 virtual table for fast Unicode-aware search over segment text.
-- 'unicode61' tokenizer handles Bangla decently (Unicode-segmenting).
CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
    text,
    content='segments',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 0'
);

CREATE TRIGGER IF NOT EXISTS segments_ai AFTER INSERT ON segments BEGIN
    INSERT INTO segments_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS segments_ad AFTER DELETE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, text) VALUES('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS segments_au AFTER UPDATE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, text) VALUES('delete', old.id, old.text);
    INSERT INTO segments_fts(rowid, text) VALUES (new.id, new.text);
END;

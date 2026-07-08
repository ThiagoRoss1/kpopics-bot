-- 0001_initial_schema.sql
-- Retroactive baseline: the schema that already existed before the migration runner.
-- All statements are IF NOT EXISTS, so applying this against the live DB is a no-op that
-- only records the baseline; against a fresh DB it builds everything.
-- No -- DOWN: a baseline is not rolled back (and `history` must never be dropped).

BEGIN;

CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_key TEXT NOT NULL,
    bot_name TEXT NOT NULL,
    posted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_idol TEXT,
    UNIQUE(file_key, bot_name)
);

CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    group_names TEXT,
    group_tags TEXT
);

CREATE TABLE IF NOT EXISTS idols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    idol_names TEXT,
    name_tags TEXT,
    group_id INTEGER REFERENCES groups(id)
);

CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    r2_key TEXT,
    bucket_stage TEXT,
    source TEXT,
    source_url TEXT,
    ai_score REAL,
    ai_reasoning TEXT,
    status TEXT,
    reviewed_by TEXT,
    reviewed_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    date TEXT,
    urgent INTEGER,
    copies INTEGER,
    combo TEXT,
    album_id TEXT
);

CREATE TABLE IF NOT EXISTS photo_idols (
    photo_id INTEGER REFERENCES photos(id),
    idol_id INTEGER REFERENCES idols(id),
    confidence REAL,
    PRIMARY KEY (photo_id, idol_id)
);

COMMIT;

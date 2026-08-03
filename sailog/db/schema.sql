-- sailog/db/schema.sql
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  video_path TEXT NOT NULL,
  clean_path TEXT,
  date TEXT, boat TEXT, crew TEXT,
  status TEXT NOT NULL DEFAULT 'created',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS speakers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  label TEXT NOT NULL, role TEXT, voiceprint_ref TEXT
);
CREATE TABLE IF NOT EXISTS utterances (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  start_s REAL NOT NULL, end_s REAL NOT NULL,
  speaker_id INTEGER, target_speaker_id INTEGER, text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS situation_tags (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  start_s REAL, end_s REAL, kind TEXT NOT NULL, value TEXT, source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS summaries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  player TEXT NOT NULL, json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS advice (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  player TEXT NOT NULL, category TEXT, text TEXT NOT NULL, embedding BLOB
);
CREATE TABLE IF NOT EXISTS repeated_links (
  advice_id_a INTEGER NOT NULL REFERENCES advice(id),
  advice_id_b INTEGER NOT NULL REFERENCES advice(id),
  similarity REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  stage TEXT NOT NULL, status TEXT NOT NULL, error TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (session_id, stage)
);

# 芝工セイルログ MVP (Sub-project A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the end-to-end MVP pipeline — cleaned video → transcript → diarization → "who said what to whom" → Claude summary + repeated-advice — browsable in a local FastAPI/SQLite web app.

**Architecture:** A `sailog/` Python package. Independent stage modules each expose `run(session_id, store, config) -> None`, read inputs from DB/filesystem and write outputs to SQLite via a single `Store` access layer. A sequential, resumable `runner` chains stages, recording per-stage state in a `jobs` table so re-runs resume. A FastAPI app uploads videos, kicks the runner off as a background task, and renders per-session / per-player views with Jinja2 + light vanilla JS.

**Tech Stack:** Python 3.12, sqlite3 (stdlib), faster-whisper (large-v3), pyannote.audio 3.1, Anthropic SDK (Claude), sentence-transformers (multilingual embeddings), FastAPI + uvicorn + Jinja2, ffmpeg/ffprobe/rclone (already on PATH), pytest. macOS, CPU.

## Global Constraints

- Python **3.12**, run via the existing `.venv` (`.venv/bin/python`, `.venv/bin/pytest`).
- macOS, **CPU only**. whisper `compute_type="int8"`; no CUDA assumptions.
- All SQL lives in `sailog/db/store.py` — no other module issues SQL.
- Every stage entry point is `run(session_id: int, store: Store, config: Config) -> None`, idempotent (skips if its `jobs` row is already `done`).
- Secrets come from `.env` (`HF_TOKEN`, `ANTHROPIC_API_KEY`, `RCLONE_REMOTE`, `SRC_FOLDER_ID`, `DST_FOLDER_ID`); never hardcode or commit them. `.env` is gitignored; keep `.env.example` current.
- faster-whisper settings (verbatim): `language="ja"`, `beam_size=5`, `vad_filter=True`, `condition_on_previous_text=False`, `word_timestamps=True`, `compute_type="int8"`.
- pyannote settings: `min_speakers=2`, `max_speakers=4`, model `pyannote/speaker-diarization-3.1`.
- Claude: low temperature (`0.0`), structured-JSON output; resolve the current model id via the `claude-api` skill at implementation time (do not guess).
- TDD for every module (`superpowers:test-driven-development`); heavy model calls are **mocked** in unit tests. One opt-in integration test marked `@pytest.mark.integration` may load real models.
- Commit after every task. Never `git add` media (`*.MOV/*.wav/...`), `.venv/`, or `data/` — `.gitignore` already excludes them; stage files explicitly.

---

## File Structure

```
sailog/
  __init__.py
  config.py                 # Config dataclass, .env loader, path/model settings
  db/
    __init__.py
    schema.sql              # table DDL
    models.py               # row dataclasses
    store.py                # Store: the only SQL layer
  ingest/
    __init__.py
    audio.py                # ffmpeg extract/mux + ffprobe duration
    drive.py                # rclone pull/push
  stages/
    __init__.py
    s1_denoise.py           # DeepFilterNet3 wrapper (+ hang-on-exit workaround)
    s2_transcribe.py        # faster-whisper
    s3_diarize.py           # pyannote
    merge.py                # words × turns → utterances
    s5_summarize.py         # Claude summary + advice extraction
  repeated/
    __init__.py
    embed.py                # embed text -> vector bytes
    match.py                # cosine similarity -> repeated_links
  pipeline/
    __init__.py
    jobs.py                 # stage list + job-state helpers
    runner.py               # sequential resumable orchestration
  web/
    __init__.py
    app.py                  # FastAPI app + routes
    templates/              # Jinja2: base, index, session, player
    static/                 # style.css, seek.js
tests/
  conftest.py               # fixtures: tmp store, sample rows, fixture clip path
  fixtures/                 # tiny expected-rows json; short clip lives outside git
requirements.txt
.env.example
README_sailog.md
```

---

## Task 1: Package skeleton + Config

**Files:**
- Create: `sailog/__init__.py` (empty), `sailog/config.py`
- Create: `requirements.txt`, `.env.example`
- Test: `tests/test_config.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Config` dataclass with fields: `root: Path`, `data_dir: Path`, `db_path: Path`, `sessions_dir: Path`, `cleaned_dir: Path`, `gdrive_dir: Path`, `hf_token: str | None`, `anthropic_api_key: str | None`, `rclone_remote: str`, `src_folder_id: str | None`, `dst_folder_id: str | None`, `whisper_model: str = "large-v3"`, `embed_model: str = "paraphrase-multilingual-MiniLM-L12-v2"`, `repeated_threshold: float = 0.75`.
  - `Config.load(root: Path | None = None) -> Config` — reads `.env` (simple `KEY=VALUE` parser, no external dep) then `os.environ`, resolves paths relative to repo root.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from pathlib import Path
from sailog.config import Config

def test_load_reads_env_and_resolves_paths(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "HF_TOKEN=hf_abc\nANTHROPIC_API_KEY=sk-xyz\nRCLONE_REMOTE=gdrive\n"
    )
    monkeypatch.delenv("HF_TOKEN", raising=False)
    cfg = Config.load(root=tmp_path)
    assert cfg.hf_token == "hf_abc"
    assert cfg.anthropic_api_key == "sk-xyz"
    assert cfg.rclone_remote == "gdrive"
    assert cfg.db_path == tmp_path / "data" / "sailog.db"
    assert cfg.sessions_dir == tmp_path / "data" / "sessions"
    assert cfg.whisper_model == "large-v3"

def test_os_environ_overrides_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("HF_TOKEN=from_file\n")
    monkeypatch.setenv("HF_TOKEN", "from_env")
    cfg = Config.load(root=tmp_path)
    assert cfg.hf_token == "from_env"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError: sailog.config`)

- [ ] **Step 3: Write minimal implementation**

```python
# sailog/config.py
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path


def _parse_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


@dataclass
class Config:
    root: Path
    data_dir: Path
    db_path: Path
    sessions_dir: Path
    cleaned_dir: Path
    gdrive_dir: Path
    hf_token: str | None = None
    anthropic_api_key: str | None = None
    rclone_remote: str = "gdrive"
    src_folder_id: str | None = None
    dst_folder_id: str | None = None
    whisper_model: str = "large-v3"
    embed_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    repeated_threshold: float = 0.75

    @classmethod
    def load(cls, root: Path | None = None) -> "Config":
        root = Path(root) if root else Path(__file__).resolve().parents[1]
        env = {**_parse_dotenv(root / ".env"), **os.environ}
        data = root / "data"
        return cls(
            root=root,
            data_dir=data,
            db_path=data / "sailog.db",
            sessions_dir=data / "sessions",
            cleaned_dir=root / "cleaned",
            gdrive_dir=root / "gdrive",
            hf_token=env.get("HF_TOKEN"),
            anthropic_api_key=env.get("ANTHROPIC_API_KEY"),
            rclone_remote=env.get("RCLONE_REMOTE", "gdrive"),
            src_folder_id=env.get("SRC_FOLDER_ID"),
            dst_folder_id=env.get("DST_FOLDER_ID"),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS (both)

- [ ] **Step 5: Write requirements.txt, .env.example, conftest.py**

```text
# requirements.txt
faster-whisper==1.0.3
pyannote.audio==3.1.1
anthropic>=0.40
sentence-transformers>=3.0
numpy>=1.26
fastapi>=0.115
uvicorn>=0.30
jinja2>=3.1
python-multipart>=0.0.9
pytest>=8.0
```

```text
# .env.example
HF_TOKEN=
ANTHROPIC_API_KEY=
RCLONE_REMOTE=gdrive
SRC_FOLDER_ID=
DST_FOLDER_ID=
```

```python
# tests/conftest.py
import pytest
from pathlib import Path
from sailog.config import Config

@pytest.fixture
def config(tmp_path) -> Config:
    return Config.load(root=tmp_path)
```

- [ ] **Step 6: Commit**

```bash
git add sailog/__init__.py sailog/config.py tests/test_config.py tests/conftest.py requirements.txt .env.example
git commit -m "feat(config): Config dataclass + .env loader"
```

---

## Task 2: DB schema, models, and Store

**Files:**
- Create: `sailog/db/__init__.py`, `sailog/db/schema.sql`, `sailog/db/models.py`, `sailog/db/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `Config` (Task 1).
- Produces — dataclasses in `models.py`: `Session(id, video_path, clean_path, date, boat, crew, status, created_at)`, `Speaker(id, session_id, label, role, voiceprint_ref)`, `Utterance(id, session_id, start_s, end_s, speaker_id, target_speaker_id, text)`, `SituationTag(id, session_id, start_s, end_s, kind, value, source)`, `Summary(id, session_id, player, data)` (`data` is a parsed dict), `Advice(id, session_id, player, category, text, embedding)` (`embedding` is `bytes | None`), `RepeatedLink(advice_id_a, advice_id_b, similarity)`, `Job(session_id, stage, status, error, updated_at)`.
- Produces — `Store` (all methods below are relied on by later tasks):
  - `Store.open(config: Config) -> Store` (creates `data_dir`, connects, runs `init_schema`)
  - `init_schema() -> None`
  - `create_session(video_path: str, date=None, boat=None, crew=None) -> int`
  - `get_session(session_id: int) -> Session | None`
  - `list_sessions() -> list[Session]`
  - `set_session_status(session_id: int, status: str) -> None`
  - `set_clean_path(session_id: int, clean_path: str) -> None`
  - `add_speaker(session_id, label, role=None, voiceprint_ref=None) -> int`
  - `get_speakers(session_id) -> list[Speaker]`
  - `set_speaker_role(speaker_id, role) -> None`
  - `add_utterance(session_id, start_s, end_s, speaker_id, target_speaker_id, text) -> int`
  - `get_utterances(session_id) -> list[Utterance]` (ordered by `start_s`)
  - `add_situation_tag(session_id, start_s, end_s, kind, value, source) -> int`
  - `get_situation_tags(session_id) -> list[SituationTag]`
  - `add_summary(session_id, player, data: dict) -> int` (stores `json.dumps`)
  - `get_summaries(session_id) -> list[Summary]`
  - `add_advice(session_id, player, category, text, embedding: bytes | None = None) -> int`
  - `get_advice(session_id: int | None = None, player: str | None = None) -> list[Advice]`
  - `set_advice_embedding(advice_id, embedding: bytes) -> None`
  - `add_repeated_link(advice_id_a, advice_id_b, similarity) -> None`
  - `get_repeated_links(session_id) -> list[RepeatedLink]`
  - `get_job(session_id, stage) -> Job | None`
  - `set_job(session_id, stage, status, error=None) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_store.py
from sailog.db.store import Store

def test_schema_and_session_roundtrip(config):
    store = Store.open(config)
    sid = store.create_session(video_path="cleaned/x_cleaned.MOV", boat="470", crew="A/B")
    s = store.get_session(sid)
    assert s.status == "created"
    assert s.video_path.endswith("x_cleaned.MOV")
    store.set_clean_path(sid, "data/sessions/1/clean.wav")
    store.set_session_status(sid, "running")
    assert store.get_session(sid).status == "running"
    assert [x.id for x in store.list_sessions()] == [sid]

def test_speakers_utterances_ordered(config):
    store = Store.open(config)
    sid = store.create_session(video_path="v.MOV")
    coach = store.add_speaker(sid, "SPEAKER_00", role="coach")
    player = store.add_speaker(sid, "SPEAKER_01", role="player")
    store.add_utterance(sid, 5.0, 6.0, coach, player, "後ろ")
    store.add_utterance(sid, 1.0, 2.0, coach, player, "もっと引いて")
    utts = store.get_utterances(sid)
    assert [u.text for u in utts] == ["もっと引いて", "後ろ"]
    assert utts[0].speaker_id == coach and utts[0].target_speaker_id == player

def test_summary_json_and_advice_embedding(config):
    store = Store.open(config)
    sid = store.create_session(video_path="v.MOV")
    store.add_summary(sid, "playerA", {"summary": "good start", "points": [1, 2]})
    assert store.get_summaries(sid)[0].data["points"] == [1, 2]
    aid = store.add_advice(sid, "playerA", "trim", "もっと引いて")
    store.set_advice_embedding(aid, b"\x00\x01")
    got = store.get_advice(player="playerA")
    assert got[0].embedding == b"\x00\x01"

def test_jobs_upsert(config):
    store = Store.open(config)
    sid = store.create_session(video_path="v.MOV")
    assert store.get_job(sid, "s2") is None
    store.set_job(sid, "s2", "done")
    assert store.get_job(sid, "s2").status == "done"
    store.set_job(sid, "s2", "error", error="boom")
    j = store.get_job(sid, "s2")
    assert j.status == "error" and j.error == "boom"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_store.py -v`
Expected: FAIL (`ModuleNotFoundError: sailog.db.store`)

- [ ] **Step 3: Write schema.sql**

```sql
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
```

- [ ] **Step 4: Write models.py and store.py**

```python
# sailog/db/models.py
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class Session:
    id: int; video_path: str; clean_path: str | None; date: str | None
    boat: str | None; crew: str | None; status: str; created_at: str

@dataclass
class Speaker:
    id: int; session_id: int; label: str; role: str | None; voiceprint_ref: str | None

@dataclass
class Utterance:
    id: int; session_id: int; start_s: float; end_s: float
    speaker_id: int | None; target_speaker_id: int | None; text: str

@dataclass
class SituationTag:
    id: int; session_id: int; start_s: float | None; end_s: float | None
    kind: str; value: str | None; source: str

@dataclass
class Summary:
    id: int; session_id: int; player: str; data: dict

@dataclass
class Advice:
    id: int; session_id: int; player: str; category: str | None
    text: str; embedding: bytes | None

@dataclass
class RepeatedLink:
    advice_id_a: int; advice_id_b: int; similarity: float

@dataclass
class Job:
    session_id: int; stage: str; status: str; error: str | None; updated_at: str
```

```python
# sailog/db/store.py
from __future__ import annotations
import json, sqlite3
from pathlib import Path
from .models import (Session, Speaker, Utterance, SituationTag, Summary,
                     Advice, RepeatedLink, Job)

_SCHEMA = Path(__file__).with_name("schema.sql")

class Store:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    @classmethod
    def open(cls, config) -> "Store":
        config.data_dir.mkdir(parents=True, exist_ok=True)
        store = cls(sqlite3.connect(config.db_path))
        store.init_schema()
        return store

    def init_schema(self) -> None:
        self.conn.executescript(_SCHEMA.read_text())
        self.conn.commit()

    # --- sessions ---
    def create_session(self, video_path, date=None, boat=None, crew=None) -> int:
        cur = self.conn.execute(
            "INSERT INTO sessions(video_path,date,boat,crew) VALUES(?,?,?,?)",
            (video_path, date, boat, crew))
        self.conn.commit(); return cur.lastrowid

    def _session(self, r) -> Session:
        return Session(r["id"], r["video_path"], r["clean_path"], r["date"],
                       r["boat"], r["crew"], r["status"], r["created_at"])

    def get_session(self, session_id) -> Session | None:
        r = self.conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        return self._session(r) if r else None

    def list_sessions(self) -> list[Session]:
        rs = self.conn.execute("SELECT * FROM sessions ORDER BY id").fetchall()
        return [self._session(r) for r in rs]

    def set_session_status(self, session_id, status) -> None:
        self.conn.execute("UPDATE sessions SET status=? WHERE id=?", (status, session_id))
        self.conn.commit()

    def set_clean_path(self, session_id, clean_path) -> None:
        self.conn.execute("UPDATE sessions SET clean_path=? WHERE id=?", (clean_path, session_id))
        self.conn.commit()

    # --- speakers ---
    def add_speaker(self, session_id, label, role=None, voiceprint_ref=None) -> int:
        cur = self.conn.execute(
            "INSERT INTO speakers(session_id,label,role,voiceprint_ref) VALUES(?,?,?,?)",
            (session_id, label, role, voiceprint_ref))
        self.conn.commit(); return cur.lastrowid

    def get_speakers(self, session_id) -> list[Speaker]:
        rs = self.conn.execute("SELECT * FROM speakers WHERE session_id=? ORDER BY id",
                               (session_id,)).fetchall()
        return [Speaker(r["id"], r["session_id"], r["label"], r["role"],
                        r["voiceprint_ref"]) for r in rs]

    def set_speaker_role(self, speaker_id, role) -> None:
        self.conn.execute("UPDATE speakers SET role=? WHERE id=?", (role, speaker_id))
        self.conn.commit()

    # --- utterances ---
    def add_utterance(self, session_id, start_s, end_s, speaker_id, target_speaker_id, text) -> int:
        cur = self.conn.execute(
            "INSERT INTO utterances(session_id,start_s,end_s,speaker_id,target_speaker_id,text)"
            " VALUES(?,?,?,?,?,?)",
            (session_id, start_s, end_s, speaker_id, target_speaker_id, text))
        self.conn.commit(); return cur.lastrowid

    def get_utterances(self, session_id) -> list[Utterance]:
        rs = self.conn.execute(
            "SELECT * FROM utterances WHERE session_id=? ORDER BY start_s", (session_id,)).fetchall()
        return [Utterance(r["id"], r["session_id"], r["start_s"], r["end_s"],
                          r["speaker_id"], r["target_speaker_id"], r["text"]) for r in rs]

    # --- situation tags ---
    def add_situation_tag(self, session_id, start_s, end_s, kind, value, source) -> int:
        cur = self.conn.execute(
            "INSERT INTO situation_tags(session_id,start_s,end_s,kind,value,source)"
            " VALUES(?,?,?,?,?,?)", (session_id, start_s, end_s, kind, value, source))
        self.conn.commit(); return cur.lastrowid

    def get_situation_tags(self, session_id) -> list[SituationTag]:
        rs = self.conn.execute("SELECT * FROM situation_tags WHERE session_id=? ORDER BY id",
                               (session_id,)).fetchall()
        return [SituationTag(r["id"], r["session_id"], r["start_s"], r["end_s"],
                             r["kind"], r["value"], r["source"]) for r in rs]

    # --- summaries ---
    def add_summary(self, session_id, player, data: dict) -> int:
        cur = self.conn.execute(
            "INSERT INTO summaries(session_id,player,json) VALUES(?,?,?)",
            (session_id, player, json.dumps(data, ensure_ascii=False)))
        self.conn.commit(); return cur.lastrowid

    def get_summaries(self, session_id) -> list[Summary]:
        rs = self.conn.execute("SELECT * FROM summaries WHERE session_id=? ORDER BY id",
                               (session_id,)).fetchall()
        return [Summary(r["id"], r["session_id"], r["player"], json.loads(r["json"])) for r in rs]

    # --- advice ---
    def add_advice(self, session_id, player, category, text, embedding=None) -> int:
        cur = self.conn.execute(
            "INSERT INTO advice(session_id,player,category,text,embedding) VALUES(?,?,?,?,?)",
            (session_id, player, category, text, embedding))
        self.conn.commit(); return cur.lastrowid

    def get_advice(self, session_id=None, player=None) -> list[Advice]:
        q = "SELECT * FROM advice"; where=[]; args=[]
        if session_id is not None: where.append("session_id=?"); args.append(session_id)
        if player is not None: where.append("player=?"); args.append(player)
        if where: q += " WHERE " + " AND ".join(where)
        q += " ORDER BY id"
        rs = self.conn.execute(q, args).fetchall()
        return [Advice(r["id"], r["session_id"], r["player"], r["category"],
                       r["text"], r["embedding"]) for r in rs]

    def set_advice_embedding(self, advice_id, embedding: bytes) -> None:
        self.conn.execute("UPDATE advice SET embedding=? WHERE id=?", (embedding, advice_id))
        self.conn.commit()

    # --- repeated links ---
    def add_repeated_link(self, advice_id_a, advice_id_b, similarity) -> None:
        self.conn.execute(
            "INSERT INTO repeated_links(advice_id_a,advice_id_b,similarity) VALUES(?,?,?)",
            (advice_id_a, advice_id_b, similarity))
        self.conn.commit()

    def get_repeated_links(self, session_id) -> list[RepeatedLink]:
        rs = self.conn.execute(
            "SELECT rl.* FROM repeated_links rl JOIN advice a ON a.id=rl.advice_id_a"
            " WHERE a.session_id=?", (session_id,)).fetchall()
        return [RepeatedLink(r["advice_id_a"], r["advice_id_b"], r["similarity"]) for r in rs]

    # --- jobs ---
    def get_job(self, session_id, stage) -> Job | None:
        r = self.conn.execute("SELECT * FROM jobs WHERE session_id=? AND stage=?",
                              (session_id, stage)).fetchone()
        return Job(r["session_id"], r["stage"], r["status"], r["error"],
                   r["updated_at"]) if r else None

    def set_job(self, session_id, stage, status, error=None) -> None:
        self.conn.execute(
            "INSERT INTO jobs(session_id,stage,status,error,updated_at)"
            " VALUES(?,?,?,?,datetime('now'))"
            " ON CONFLICT(session_id,stage) DO UPDATE SET"
            " status=excluded.status, error=excluded.error, updated_at=excluded.updated_at",
            (session_id, stage, status, error))
        self.conn.commit()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_store.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add sailog/db/
git add tests/test_store.py
git commit -m "feat(db): schema, row models, and Store SQL layer"
```

---

## Task 3: Ingest — audio (ffmpeg extract/mux + duration)

**Files:**
- Create: `sailog/ingest/__init__.py`, `sailog/ingest/audio.py`
- Test: `tests/test_audio.py`

**Interfaces:**
- Consumes: nothing (pure subprocess helpers). Reuses the ffmpeg command shapes from `denoise_local.py`.
- Produces:
  - `extract_audio(src: Path, out_wav: Path) -> Path` — `ffmpeg -i src -vn -acodec pcm_s16le out_wav`
  - `mux_audio(src_video: Path, audio: Path, out: Path, bitrate="192k") -> Path` — maps `0:v:0` + `1:a:0`, `-c:v copy -c:a aac`
  - `audio_duration(path: Path) -> float` — ffprobe, `0.0` on failure
  - `_run(cmd: list[str]) -> subprocess.CompletedProcess` — raises on failure, surfaces stderr

Unit tests mock `subprocess.run`; do not shell out to ffmpeg in unit tests.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audio.py
from pathlib import Path
from unittest.mock import patch, MagicMock
from sailog.ingest import audio

def test_extract_audio_builds_correct_cmd(tmp_path):
    src = tmp_path / "a.MOV"; out = tmp_path / "a.wav"
    with patch("sailog.ingest.audio.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stderr="")
        result = audio.extract_audio(src, out)
    cmd = run.call_args.args[0]
    assert "-vn" in cmd and "pcm_s16le" in cmd
    assert cmd[-1] == str(out) and result == out

def test_mux_audio_maps_streams(tmp_path):
    with patch("sailog.ingest.audio.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stderr="")
        audio.mux_audio(tmp_path/"v.MOV", tmp_path/"c.wav", tmp_path/"o.MOV")
    cmd = run.call_args.args[0]
    assert "0:v:0" in cmd and "1:a:0" in cmd and "copy" in cmd

def test_audio_duration_parses_ffprobe(tmp_path):
    with patch("sailog.ingest.audio.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="12.5\n", stderr="")
        assert audio.audio_duration(tmp_path/"a.MOV") == 12.5

def test_audio_duration_returns_zero_on_error(tmp_path):
    with patch("sailog.ingest.audio.subprocess.run", side_effect=Exception("nope")):
        assert audio.audio_duration(tmp_path/"a.MOV") == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_audio.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write minimal implementation**

```python
# sailog/ingest/audio.py
from __future__ import annotations
import shutil, subprocess, sys
from pathlib import Path

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, check=True, text=True, **kw)
    except subprocess.CalledProcessError as e:
        if e.stderr: print(e.stderr.strip(), file=sys.stderr)
        raise

def extract_audio(src: Path, out_wav: Path) -> Path:
    _run([FFMPEG, "-y", "-i", str(src), "-vn", "-acodec", "pcm_s16le", str(out_wav)],
         capture_output=True)
    return out_wav

def mux_audio(src_video: Path, audio: Path, out: Path, bitrate: str = "192k") -> Path:
    _run([FFMPEG, "-y", "-i", str(src_video), "-i", str(audio),
          "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
          "-b:a", bitrate, "-shortest", str(out)], capture_output=True)
    return out

def audio_duration(path: Path) -> float:
    try:
        out = _run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                   capture_output=True).stdout.strip()
        return float(out)
    except Exception:
        return 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_audio.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add sailog/ingest/__init__.py sailog/ingest/audio.py tests/test_audio.py
git commit -m "feat(ingest): ffmpeg audio extract/mux + duration helpers"
```

---

## Task 4: Ingest — drive (rclone pull/push)

**Files:**
- Create: `sailog/ingest/drive.py`
- Test: `tests/test_drive.py`

**Interfaces:**
- Consumes: `Config` (for `rclone_remote`, folder ids).
- Produces:
  - `list_remote(config, folder_id: str) -> list[str]` — `rclone lsf <remote>: --drive-root-folder-id <id>`, returns filenames
  - `pull(config, folder_id: str, name: str, dest: Path) -> Path` — `rclone copy` one file to `dest`
  - `push(config, local: Path, folder_id: str) -> None` — `rclone copy` local file up

Unit tests mock `subprocess.run`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_drive.py
from pathlib import Path
from unittest.mock import patch, MagicMock
from sailog.ingest import drive

def test_list_remote_parses_lines(config):
    with patch("sailog.ingest.drive.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="a.MOV\nb.MOV\n", stderr="")
        names = drive.list_remote(config, "FOLDER")
    assert names == ["a.MOV", "b.MOV"]
    cmd = run.call_args.args[0]
    assert "lsf" in cmd and "FOLDER" in cmd

def test_pull_builds_copy_cmd(config, tmp_path):
    with patch("sailog.ingest.drive.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        out = drive.pull(config, "FOLDER", "a.MOV", tmp_path)
    cmd = run.call_args.args[0]
    assert "copy" in cmd and out == tmp_path / "a.MOV"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_drive.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write minimal implementation**

```python
# sailog/ingest/drive.py
from __future__ import annotations
import shutil, subprocess, sys
from pathlib import Path

RCLONE = shutil.which("rclone") or "rclone"

def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        if e.stderr: print(e.stderr.strip(), file=sys.stderr)
        raise

def list_remote(config, folder_id: str) -> list[str]:
    out = _run([RCLONE, "lsf", f"{config.rclone_remote}:",
                "--drive-root-folder-id", folder_id]).stdout
    return [ln for ln in out.splitlines() if ln.strip()]

def pull(config, folder_id: str, name: str, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    _run([RCLONE, "copy", f"{config.rclone_remote}:{name}",
          str(dest), "--drive-root-folder-id", folder_id])
    return dest / name

def push(config, local: Path, folder_id: str) -> None:
    _run([RCLONE, "copy", str(local), f"{config.rclone_remote}:",
          "--drive-root-folder-id", folder_id])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_drive.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sailog/ingest/drive.py tests/test_drive.py
git commit -m "feat(ingest): rclone drive pull/push/list"
```

---

## Task 5: Stage ① — denoise wrapper

**Files:**
- Create: `sailog/stages/__init__.py`, `sailog/stages/s1_denoise.py`
- Test: `tests/test_s1_denoise.py`

**Interfaces:**
- Consumes: `Store`, `Config`, `audio.extract_audio`/`audio_duration` (Task 3). Reuses `run_deepfilter` hang-on-exit logic from `denoise_local.py` verbatim (the DeepFilter CLI never exits — poll output size, then kill; see memory `deepfilter-hangs-on-exit`).
- Produces:
  - `run(session_id, store, config) -> None` — if the session's `video_path` already looks cleaned (lives under `cleaned/`), just extract its audio to `data/sessions/<id>/clean.wav` and `set_clean_path`; otherwise extract raw audio, run DeepFilterNet3, write `clean.wav`. Marks job `s1` done. Idempotent.
  - `run_deepfilter(raw_wav, clean_dir, expected, deadline_s) -> None` (ported).

- [ ] **Step 1: Write the failing test** (mock the model; assert DB + skip behavior)

```python
# tests/test_s1_denoise.py
from pathlib import Path
from unittest.mock import patch
from sailog.db.store import Store
from sailog.stages import s1_denoise

def test_cleaned_input_just_extracts_audio(config):
    store = Store.open(config)
    (config.cleaned_dir).mkdir(parents=True, exist_ok=True)
    src = config.cleaned_dir / "x_cleaned.MOV"; src.write_bytes(b"fake")
    sid = store.create_session(video_path=str(src))
    with patch("sailog.stages.s1_denoise.extract_audio") as ex:
        ex.side_effect = lambda s, o: (Path(o).write_bytes(b"wav"), Path(o))[1]
        s1_denoise.run(sid, store, config)
    assert store.get_session(sid).clean_path.endswith("clean.wav")
    assert store.get_job(sid, "s1").status == "done"

def test_idempotent_skip_when_done(config):
    store = Store.open(config)
    sid = store.create_session(video_path=str(config.cleaned_dir / "x_cleaned.MOV"))
    store.set_job(sid, "s1", "done")
    with patch("sailog.stages.s1_denoise.extract_audio") as ex:
        s1_denoise.run(sid, store, config)
    ex.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_s1_denoise.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write minimal implementation** (port `run_deepfilter` from `denoise_local.py` lines 48-98 unchanged; add the wrapper)

```python
# sailog/stages/s1_denoise.py
from __future__ import annotations
import subprocess, time
from pathlib import Path
from ..ingest.audio import extract_audio, audio_duration

def run_deepfilter(raw_wav: Path, clean_dir: Path, expected: Path, deadline_s: float) -> None:
    # Ported verbatim from denoise_local.py — DeepFilter hangs on exit, so we
    # poll the output size and kill it once stable. See memory deepfilter-hangs-on-exit.
    deepfilter = str(Path(__file__).resolve().parents[2] / ".venv" / "bin" / "deepFilter")
    proc = subprocess.Popen([deepfilter, str(raw_wav), "-o", str(clean_dir)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    last_size = -1; stable_since = None; start = time.monotonic()
    try:
        while True:
            exited = proc.poll() is not None
            if expected.exists():
                size = expected.stat().st_size
                if size > 0 and size == last_size:
                    if stable_since is None: stable_since = time.monotonic()
                    elif time.monotonic() - stable_since >= 3: return
                else:
                    last_size = size; stable_since = None
            if exited:
                if expected.exists() and expected.stat().st_size > 0: return
                raise RuntimeError("deepFilter exited without producing output")
            if time.monotonic() - start > deadline_s:
                raise TimeoutError(f"deepFilter exceeded {deadline_s:.0f}s")
            time.sleep(1)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill()

def run(session_id: int, store, config) -> None:
    job = store.get_job(session_id, "s1")
    if job and job.status == "done":
        return
    sess = store.get_session(session_id)
    src = Path(sess.video_path)
    out_dir = config.sessions_dir / str(session_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    clean_wav = out_dir / "clean.wav"
    try:
        already_clean = "cleaned" in src.parts or src.stem.endswith("_cleaned")
        if already_clean:
            extract_audio(src, clean_wav)
        else:
            raw = out_dir / "raw.wav"
            extract_audio(src, raw)
            clean_dir = out_dir / "df"; clean_dir.mkdir(exist_ok=True)
            expected = clean_dir / f"{raw.stem}_DeepFilterNet3.wav"
            deadline = max(300.0, audio_duration(src) * 2.0 + 120.0)
            run_deepfilter(raw, clean_dir, expected, deadline)
            expected.replace(clean_wav)
        store.set_clean_path(session_id, str(clean_wav))
        store.set_job(session_id, "s1", "done")
    except Exception as e:
        store.set_job(session_id, "s1", "error", error=str(e)); raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_s1_denoise.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sailog/stages/__init__.py sailog/stages/s1_denoise.py tests/test_s1_denoise.py
git commit -m "feat(s1): denoise stage wrapper reusing DeepFilterNet3 flow"
```

---

## Task 6: Stage ② — transcribe (faster-whisper)

**Files:**
- Create: `sailog/stages/s2_transcribe.py`
- Test: `tests/test_s2_transcribe.py`

**Interfaces:**
- Consumes: `Store`, `Config`, the session `clean_path` (from s1).
- Produces:
  - `transcribe(clean_wav: Path, config) -> list[dict]` — returns word rows `{"start": float, "end": float, "word": str}` using faster-whisper with the locked settings. The model call is isolated here so it can be mocked.
  - `run(session_id, store, config) -> None` — calls `transcribe`, writes the word list to `data/sessions/<id>/words.json`, marks job `s2` done. (Words are consumed by `merge`, not stored as rows yet.) Idempotent.

- [ ] **Step 1: Write the failing test** (mock `transcribe`)

```python
# tests/test_s2_transcribe.py
import json
from pathlib import Path
from unittest.mock import patch
from sailog.db.store import Store
from sailog.stages import s2_transcribe

def test_run_writes_words_json_and_marks_done(config):
    store = Store.open(config)
    sid = store.create_session(video_path="v.MOV")
    (config.sessions_dir / str(sid)).mkdir(parents=True)
    store.set_clean_path(sid, str(config.sessions_dir / str(sid) / "clean.wav"))
    words = [{"start": 0.1, "end": 0.4, "word": "もっと"},
             {"start": 0.4, "end": 0.7, "word": "引いて"}]
    with patch("sailog.stages.s2_transcribe.transcribe", return_value=words):
        s2_transcribe.run(sid, store, config)
    out = json.loads((config.sessions_dir / str(sid) / "words.json").read_text())
    assert out[0]["word"] == "もっと"
    assert store.get_job(sid, "s2").status == "done"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_s2_transcribe.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# sailog/stages/s2_transcribe.py
from __future__ import annotations
import json
from pathlib import Path

def transcribe(clean_wav: Path, config) -> list[dict]:
    from faster_whisper import WhisperModel
    model = WhisperModel(config.whisper_model, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        str(clean_wav), language="ja", beam_size=5, vad_filter=True,
        condition_on_previous_text=False, word_timestamps=True)
    words: list[dict] = []
    for seg in segments:
        for w in (seg.words or []):
            words.append({"start": float(w.start), "end": float(w.end),
                          "word": w.word})
    return words

def run(session_id: int, store, config) -> None:
    job = store.get_job(session_id, "s2")
    if job and job.status == "done":
        return
    sess = store.get_session(session_id)
    out_dir = config.sessions_dir / str(session_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        words = transcribe(Path(sess.clean_path), config)
        (out_dir / "words.json").write_text(
            json.dumps(words, ensure_ascii=False), encoding="utf-8")
        store.set_job(session_id, "s2", "done")
    except Exception as e:
        store.set_job(session_id, "s2", "error", error=str(e)); raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_s2_transcribe.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sailog/stages/s2_transcribe.py tests/test_s2_transcribe.py
git commit -m "feat(s2): faster-whisper transcription stage"
```

---

## Task 7: Stage ③ — diarize (pyannote)

**Files:**
- Create: `sailog/stages/s3_diarize.py`
- Test: `tests/test_s3_diarize.py`

**Interfaces:**
- Consumes: `Store`, `Config` (`hf_token`), session `clean_path`.
- Produces:
  - `diarize(clean_wav: Path, config) -> list[dict]` — returns turns `{"start": float, "end": float, "label": str}` using `pyannote/speaker-diarization-3.1` with `min_speakers=2, max_speakers=4`. Isolated for mocking.
  - `run(session_id, store, config) -> None` — calls `diarize`, writes turns to `data/sessions/<id>/turns.json`, and inserts a `speakers` row per distinct label (role left NULL — assigned manually in the UI). Marks job `s3` done. Idempotent.

- [ ] **Step 1: Write the failing test** (mock `diarize`)

```python
# tests/test_s3_diarize.py
import json
from unittest.mock import patch
from sailog.db.store import Store
from sailog.stages import s3_diarize

def test_run_persists_turns_and_speakers(config):
    store = Store.open(config)
    sid = store.create_session(video_path="v.MOV")
    (config.sessions_dir / str(sid)).mkdir(parents=True)
    store.set_clean_path(sid, "clean.wav")
    turns = [{"start": 0.0, "end": 1.0, "label": "SPEAKER_00"},
             {"start": 1.0, "end": 2.0, "label": "SPEAKER_01"},
             {"start": 2.0, "end": 3.0, "label": "SPEAKER_00"}]
    with patch("sailog.stages.s3_diarize.diarize", return_value=turns):
        s3_diarize.run(sid, store, config)
    labels = sorted(s.label for s in store.get_speakers(sid))
    assert labels == ["SPEAKER_00", "SPEAKER_01"]
    saved = json.loads((config.sessions_dir / str(sid) / "turns.json").read_text())
    assert len(saved) == 3
    assert store.get_job(sid, "s3").status == "done"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_s3_diarize.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# sailog/stages/s3_diarize.py
from __future__ import annotations
import json
from pathlib import Path

def diarize(clean_wav: Path, config) -> list[dict]:
    from pyannote.audio import Pipeline
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1", use_auth_token=config.hf_token)
    annotation = pipeline(str(clean_wav), min_speakers=2, max_speakers=4)
    turns: list[dict] = []
    for turn, _, label in annotation.itertracks(yield_label=True):
        turns.append({"start": float(turn.start), "end": float(turn.end),
                      "label": str(label)})
    return turns

def run(session_id: int, store, config) -> None:
    job = store.get_job(session_id, "s3")
    if job and job.status == "done":
        return
    sess = store.get_session(session_id)
    out_dir = config.sessions_dir / str(session_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        turns = diarize(Path(sess.clean_path), config)
        (out_dir / "turns.json").write_text(
            json.dumps(turns, ensure_ascii=False), encoding="utf-8")
        seen = set()
        for t in turns:
            if t["label"] not in seen:
                store.add_speaker(session_id, t["label"])
                seen.add(t["label"])
        store.set_job(session_id, "s3", "done")
    except Exception as e:
        store.set_job(session_id, "s3", "error", error=str(e)); raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_s3_diarize.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sailog/stages/s3_diarize.py tests/test_s3_diarize.py
git commit -m "feat(s3): pyannote diarization stage"
```

---

## Task 8: Repeated-advice — embeddings + matching

**Files:**
- Create: `sailog/repeated/__init__.py`, `sailog/repeated/embed.py`, `sailog/repeated/match.py`
- Test: `tests/test_repeated.py`

**Interfaces:**
- Consumes: `Config` (`embed_model`, `repeated_threshold`), `Store`.
- Produces:
  - `embed.encode(texts: list[str], config) -> list[bytes]` — sentence-transformers encode → float32 `np.ndarray.tobytes()` per text. Isolated for mocking.
  - `embed.to_vec(blob: bytes) -> np.ndarray` — `np.frombuffer(blob, dtype=np.float32)`.
  - `match.cosine(a: np.ndarray, b: np.ndarray) -> float`.
  - `match.find_repeats(session_id, store, config) -> int` — embeds any advice rows for the session missing embeddings (via `embed.encode`), stores them, then for each advice compares to that player's **earlier** advice (any session) and writes a `repeated_links` row when cosine ≥ threshold. Returns number of links created.

- [ ] **Step 1: Write the failing test** (mock encode with deterministic vectors)

```python
# tests/test_repeated.py
import numpy as np
from unittest.mock import patch
from sailog.db.store import Store
from sailog.repeated import match, embed

def test_cosine_basic():
    a = np.array([1, 0], dtype=np.float32); b = np.array([1, 0], dtype=np.float32)
    assert match.cosine(a, b) == 1.0

def test_find_repeats_links_similar_advice(config):
    store = Store.open(config)
    s1 = store.create_session(video_path="v1"); s2 = store.create_session(video_path="v2")
    a1 = store.add_advice(s1, "playerA", "trim", "もっとシートを引いて")
    a2 = store.add_advice(s2, "playerA", "trim", "シートをもっと引く")
    a3 = store.add_advice(s2, "playerA", "hike", "もっとハイクアウト")
    vecs = {"もっとシートを引いて": [1.0, 0.0], "シートをもっと引く": [0.99, 0.14],
            "もっとハイクアウト": [0.0, 1.0]}
    def fake_encode(texts, cfg):
        return [np.array(vecs[t], dtype=np.float32).tobytes() for t in texts]
    with patch("sailog.repeated.match.encode", side_effect=fake_encode):
        n = match.find_repeats(s2, store, config)
    links = store.get_repeated_links(s2)
    assert n == 1 and len(links) == 1
    assert {links[0].advice_id_a, links[0].advice_id_b} == {a2, a1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_repeated.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# sailog/repeated/embed.py
from __future__ import annotations
import numpy as np

_MODEL = None

def _get_model(config):
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer
        _MODEL = SentenceTransformer(config.embed_model)
    return _MODEL

def encode(texts: list[str], config) -> list[bytes]:
    model = _get_model(config)
    arr = model.encode(list(texts), convert_to_numpy=True).astype(np.float32)
    return [row.tobytes() for row in arr]

def to_vec(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)
```

```python
# sailog/repeated/match.py
from __future__ import annotations
import numpy as np
from .embed import encode, to_vec

def cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a); nb = np.linalg.norm(b)
    if na == 0 or nb == 0: return 0.0
    return float(np.dot(a, b) / (na * nb))

def find_repeats(session_id: int, store, config) -> int:
    advice = store.get_advice(session_id=session_id)
    missing = [a for a in advice if a.embedding is None]
    if missing:
        blobs = encode([a.text for a in missing], config)
        for a, blob in zip(missing, blobs):
            store.set_advice_embedding(a.id, blob)
        advice = store.get_advice(session_id=session_id)  # reload with embeddings
    created = 0
    for a in advice:
        prior = [p for p in store.get_advice(player=a.player)
                 if p.id < a.id and p.embedding is not None]
        av = to_vec(a.embedding)
        for p in prior:
            sim = cosine(av, to_vec(p.embedding))
            if sim >= config.repeated_threshold:
                store.add_repeated_link(a.id, p.id, sim)
                created += 1
    return created
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_repeated.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sailog/repeated/ tests/test_repeated.py
git commit -m "feat(repeated): embeddings + cosine repeated-advice matching"
```

---

## Task 9: Merge — words × turns → utterances

**Files:**
- Create: `sailog/stages/merge.py`
- Test: `tests/test_merge.py`

**Interfaces:**
- Consumes: `words.json` (Task 6), `turns.json` (Task 7), `Store` speakers.
- Produces:
  - `assign_speaker(word: dict, turns: list[dict]) -> str | None` — label of the turn with max temporal overlap with the word.
  - `group_utterances(words, turns) -> list[dict]` — consecutive words with the same speaker label become one utterance `{"start","end","label","text"}` (text = words joined, stripped).
  - `infer_targets(utterances, coach_label) -> None` — for each coach utterance, sets `"target"` to the label of the nearest following non-coach turn (or nearest overall); non-coach utterances get `target=None`. If no coach role assigned, all targets are `None`.
  - `run(session_id, store, config) -> None` — loads json + speakers, builds utterances, resolves labels→speaker ids, applies targeting using the coach-role speaker if set, inserts `utterances` rows, marks job `merge` done. Idempotent.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_merge.py
from sailog.stages import merge

TURNS = [{"start": 0.0, "end": 1.0, "label": "SPEAKER_00"},
         {"start": 1.0, "end": 2.0, "label": "SPEAKER_01"}]

def test_assign_speaker_by_overlap():
    assert merge.assign_speaker({"start": 0.1, "end": 0.4}, TURNS) == "SPEAKER_00"
    assert merge.assign_speaker({"start": 1.2, "end": 1.5}, TURNS) == "SPEAKER_01"

def test_group_consecutive_same_speaker():
    words = [{"start": 0.0, "end": 0.3, "word": "もっと"},
             {"start": 0.3, "end": 0.6, "word": "引いて"},
             {"start": 1.1, "end": 1.4, "word": "はい"}]
    utts = merge.group_utterances(words, TURNS)
    assert [u["text"] for u in utts] == ["もっと引いて", "はい"]
    assert utts[0]["label"] == "SPEAKER_00" and utts[1]["label"] == "SPEAKER_01"

def test_infer_targets_points_coach_to_next_player():
    utts = [{"start": 0.0, "end": 1.0, "label": "SPEAKER_00", "text": "引いて"},
            {"start": 1.0, "end": 2.0, "label": "SPEAKER_01", "text": "はい"}]
    merge.infer_targets(utts, coach_label="SPEAKER_00")
    assert utts[0]["target"] == "SPEAKER_01"
    assert utts[1]["target"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_merge.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# sailog/stages/merge.py
from __future__ import annotations
import json
from pathlib import Path

def _overlap(a0, a1, b0, b1) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))

def assign_speaker(word: dict, turns: list[dict]) -> str | None:
    best, best_ov = None, 0.0
    for t in turns:
        ov = _overlap(word["start"], word["end"], t["start"], t["end"])
        if ov > best_ov:
            best, best_ov = t["label"], ov
    return best

def group_utterances(words: list[dict], turns: list[dict]) -> list[dict]:
    out: list[dict] = []
    for w in words:
        label = assign_speaker(w, turns)
        if out and out[-1]["label"] == label:
            out[-1]["text"] += w["word"]
            out[-1]["end"] = w["end"]
        else:
            out.append({"start": w["start"], "end": w["end"],
                        "label": label, "text": w["word"]})
    for u in out:
        u["text"] = u["text"].strip()
    return out

def infer_targets(utterances: list[dict], coach_label: str | None) -> None:
    for i, u in enumerate(utterances):
        if coach_label and u["label"] == coach_label:
            nxt = next((v["label"] for v in utterances[i+1:]
                        if v["label"] != coach_label), None)
            if nxt is None:
                nxt = next((v["label"] for v in utterances
                            if v["label"] != coach_label), None)
            u["target"] = nxt
        else:
            u["target"] = None

def run(session_id: int, store, config) -> None:
    job = store.get_job(session_id, "merge")
    if job and job.status == "done":
        return
    out_dir = config.sessions_dir / str(session_id)
    try:
        words = json.loads((out_dir / "words.json").read_text())
        turns = json.loads((out_dir / "turns.json").read_text())
        speakers = store.get_speakers(session_id)
        by_label = {s.label: s.id for s in speakers}
        coach = next((s.label for s in speakers if s.role == "coach"), None)
        utts = group_utterances(words, turns)
        infer_targets(utts, coach)
        for u in utts:
            if not u["text"]:
                continue
            store.add_utterance(
                session_id, u["start"], u["end"], by_label.get(u["label"]),
                by_label.get(u["target"]) if u["target"] else None, u["text"])
        store.set_job(session_id, "merge", "done")
    except Exception as e:
        store.set_job(session_id, "merge", "error", error=str(e)); raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_merge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sailog/stages/merge.py tests/test_merge.py
git commit -m "feat(merge): align words with speaker turns into utterances"
```

---

## Task 10: Stage ⑤ — Claude summary + advice extraction

**Files:**
- Create: `sailog/stages/s5_summarize.py`
- Test: `tests/test_s5_summarize.py`

**Interfaces:**
- Consumes: `Store` utterances + speakers, `Config` (`anthropic_api_key`).
- Produces:
  - `build_prompt(session, speakers, utterances) -> str` — renders the transcript ("coach→player: text" lines) into a prompt asking for JSON.
  - `call_claude(prompt: str, config) -> dict` — Anthropic SDK call, low temp, returns parsed JSON `{"players": [{"name","summary","advice":[{"category","text"}]}]}`. Isolated for mocking. **Resolve the current Claude model id via the `claude-api` skill before writing this.**
  - `run(session_id, store, config) -> None` — builds prompt from DB, calls Claude, writes one `summaries` row per player (`data` = that player's object) and one `advice` row per advice item, marks job `s5` done. Idempotent.

- [ ] **Step 1: Write the failing test** (mock `call_claude`)

```python
# tests/test_s5_summarize.py
from unittest.mock import patch
from sailog.db.store import Store
from sailog.stages import s5_summarize

def test_run_writes_summaries_and_advice(config):
    store = Store.open(config)
    sid = store.create_session(video_path="v.MOV")
    c = store.add_speaker(sid, "SPEAKER_00", role="coach")
    p = store.add_speaker(sid, "SPEAKER_01", role="player")
    store.add_utterance(sid, 0.0, 1.0, c, p, "もっと引いて")
    fake = {"players": [{"name": "SPEAKER_01", "summary": "トリム改善余地",
             "advice": [{"category": "trim", "text": "シートを引く"}]}]}
    with patch("sailog.stages.s5_summarize.call_claude", return_value=fake):
        s5_summarize.run(sid, store, config)
    sums = store.get_summaries(sid)
    assert sums[0].player == "SPEAKER_01"
    assert sums[0].data["summary"] == "トリム改善余地"
    adv = store.get_advice(session_id=sid)
    assert adv[0].text == "シートを引く" and adv[0].category == "trim"
    assert store.get_job(sid, "s5").status == "done"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_s5_summarize.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation** (confirm model id via claude-api skill)

```python
# sailog/stages/s5_summarize.py
from __future__ import annotations
import json

# NOTE: resolve the current model id with the claude-api skill before finalizing.
CLAUDE_MODEL = "claude-opus-4-8"

_INSTRUCTIONS = (
    "あなたはセーリングのコーチング分析AIです。以下の練習の発話ログから、"
    "選手ごとに (1) 練習のサマリ、(2) 受けた指摘(category と text)を抽出し、"
    "次のJSONだけを出力してください: "
    '{"players":[{"name": <話者ラベル>, "summary": <文字列>, '
    '"advice":[{"category": <短い分類>, "text": <指摘内容>}]}]}'
)

def build_prompt(session, speakers, utterances) -> str:
    role = {s.id: (s.role or s.label) for s in speakers}
    lines = []
    for u in utterances:
        who = role.get(u.speaker_id, "?")
        to = role.get(u.target_speaker_id, "") if u.target_speaker_id else ""
        arrow = f"{who}→{to}" if to else who
        lines.append(f"[{u.start_s:.1f}s] {arrow}: {u.text}")
    return _INSTRUCTIONS + "\n\n発話ログ:\n" + "\n".join(lines)

def call_claude(prompt: str, config) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    msg = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=4096, temperature=0.0,
        messages=[{"role": "user", "content": prompt}])
    text = msg.content[0].text
    return json.loads(text)

def run(session_id: int, store, config) -> None:
    job = store.get_job(session_id, "s5")
    if job and job.status == "done":
        return
    try:
        sess = store.get_session(session_id)
        speakers = store.get_speakers(session_id)
        utterances = store.get_utterances(session_id)
        result = call_claude(build_prompt(sess, speakers, utterances), config)
        for p in result.get("players", []):
            name = p.get("name", "unknown")
            store.add_summary(session_id, name,
                              {"summary": p.get("summary", ""), "advice": p.get("advice", [])})
            for a in p.get("advice", []):
                store.add_advice(session_id, name, a.get("category"), a.get("text", ""))
        store.set_job(session_id, "s5", "done")
    except Exception as e:
        store.set_job(session_id, "s5", "error", error=str(e)); raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_s5_summarize.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sailog/stages/s5_summarize.py tests/test_s5_summarize.py
git commit -m "feat(s5): Claude summary + advice extraction stage"
```

---

## Task 11: Pipeline — jobs + runner

**Files:**
- Create: `sailog/pipeline/__init__.py`, `sailog/pipeline/jobs.py`, `sailog/pipeline/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: all stage `run` fns, `repeated.match.find_repeats`, `Store`, `Config`.
- Produces:
  - `jobs.STAGES: list[str]` = `["s1", "s2", "s3", "merge", "s5", "repeated"]`.
  - `runner.STAGE_FNS: dict[str, callable]` mapping stage → `run(session_id, store, config)` (repeated wraps `find_repeats`).
  - `runner.run(session_id, store, config) -> None` — sets session `running`, executes stages in `STAGES` order (each stage self-skips if done), sets session `done`; on any stage exception sets session `error` and stops.

- [ ] **Step 1: Write the failing test** (patch stage fns with spies)

```python
# tests/test_runner.py
from unittest.mock import patch
from sailog.db.store import Store
from sailog.pipeline import runner, jobs

def test_runner_calls_stages_in_order_and_marks_done(config):
    store = Store.open(config)
    sid = store.create_session(video_path="v.MOV")
    calls = []
    def make(stage):
        def fn(session_id, s, c): calls.append(stage)
        return fn
    fake = {st: make(st) for st in jobs.STAGES}
    with patch.dict(runner.STAGE_FNS, fake, clear=True):
        runner.run(sid, store, config)
    assert calls == jobs.STAGES
    assert store.get_session(sid).status == "done"

def test_runner_stops_and_marks_error(config):
    store = Store.open(config)
    sid = store.create_session(video_path="v.MOV")
    def boom(session_id, s, c): raise RuntimeError("x")
    def ok(session_id, s, c): pass
    fake = {st: ok for st in jobs.STAGES}; fake["s3"] = boom
    with patch.dict(runner.STAGE_FNS, fake, clear=True):
        try: runner.run(sid, store, config)
        except RuntimeError: pass
    assert store.get_session(sid).status == "error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_runner.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# sailog/pipeline/jobs.py
STAGES = ["s1", "s2", "s3", "merge", "s5", "repeated"]
```

```python
# sailog/pipeline/runner.py
from __future__ import annotations
from ..stages import s1_denoise, s2_transcribe, s3_diarize, merge, s5_summarize
from ..repeated import match
from .jobs import STAGES

def _repeated(session_id, store, config):
    job = store.get_job(session_id, "repeated")
    if job and job.status == "done":
        return
    match.find_repeats(session_id, store, config)
    store.set_job(session_id, "repeated", "done")

STAGE_FNS = {
    "s1": s1_denoise.run, "s2": s2_transcribe.run, "s3": s3_diarize.run,
    "merge": merge.run, "s5": s5_summarize.run, "repeated": _repeated,
}

def run(session_id: int, store, config) -> None:
    store.set_session_status(session_id, "running")
    try:
        for stage in STAGES:
            STAGE_FNS[stage](session_id, store, config)
        store.set_session_status(session_id, "done")
    except Exception:
        store.set_session_status(session_id, "error")
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_runner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sailog/pipeline/ tests/test_runner.py
git commit -m "feat(pipeline): resumable sequential runner + stage registry"
```

---

## Task 12: Web app — FastAPI routes + templates

**Files:**
- Create: `sailog/web/__init__.py`, `sailog/web/app.py`, `sailog/web/templates/{base,index,session,player}.html`, `sailog/web/static/{style.css,seek.js}`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `Store`, `Config`, `runner.run`.
- Produces (routes):
  - `GET /` → index: session list + form (choose a `cleaned/*.MOV` or upload).
  - `POST /upload` (form field `source`: a filename under `cleaned/`) → `create_session`, launch `runner.run` via `BackgroundTasks`, redirect to `/sessions/{id}`.
  - `GET /sessions/{id}` → status, `<video>`, utterance timeline (who→whom, click ts → seek), per-player summaries, repeated-advice callouts, manual situation-tag form.
  - `POST /sessions/{id}/tags` (fields kind, value, start_s, end_s) → `add_situation_tag(source="manual")` → redirect back.
  - `POST /sessions/{id}/roles` (field mapping label→role) → `set_speaker_role` for coach/player labels → redirect back.
  - `GET /players/{name}` → that player's advice across sessions.
  - App factory `create_app(config=None) -> FastAPI` so tests inject a tmp config.

- [ ] **Step 1: Write the failing test** (TestClient; patch `runner.run` so upload doesn't run models)

```python
# tests/test_web.py
from unittest.mock import patch
from fastapi.testclient import TestClient
from sailog.web.app import create_app
from sailog.db.store import Store

def test_index_lists_sessions(config):
    store = Store.open(config); store.create_session(video_path="cleaned/x_cleaned.MOV")
    client = TestClient(create_app(config))
    r = client.get("/")
    assert r.status_code == 200 and "x_cleaned.MOV" in r.text

def test_upload_creates_session_and_kicks_runner(config):
    (config.cleaned_dir).mkdir(parents=True, exist_ok=True)
    (config.cleaned_dir / "x_cleaned.MOV").write_bytes(b"fake")
    client = TestClient(create_app(config))
    with patch("sailog.web.app.runner.run") as run:
        r = client.post("/upload", data={"source": "x_cleaned.MOV"},
                        follow_redirects=False)
    assert r.status_code in (302, 303)
    assert run.called

def test_session_view_shows_utterances(config):
    store = Store.open(config)
    sid = store.create_session(video_path="cleaned/x_cleaned.MOV")
    c = store.add_speaker(sid, "SPEAKER_00", role="coach")
    p = store.add_speaker(sid, "SPEAKER_01", role="player")
    store.add_utterance(sid, 3.0, 4.0, c, p, "もっと引いて")
    client = TestClient(create_app(config))
    r = client.get(f"/sessions/{sid}")
    assert r.status_code == 200 and "もっと引いて" in r.text

def test_add_manual_tag(config):
    store = Store.open(config)
    sid = store.create_session(video_path="cleaned/x_cleaned.MOV")
    client = TestClient(create_app(config))
    client.post(f"/sessions/{sid}/tags",
                data={"kind": "wind", "value": "12kt", "start_s": "0", "end_s": "10"},
                follow_redirects=False)
    tags = store.get_situation_tags(sid)
    assert tags[0].kind == "wind" and tags[0].source == "manual"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_web.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# sailog/web/app.py
from __future__ import annotations
from pathlib import Path
from fastapi import FastAPI, Request, Form, BackgroundTasks
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from ..config import Config
from ..db.store import Store
from ..pipeline import runner

_DIR = Path(__file__).parent

def create_app(config: Config | None = None) -> FastAPI:
    config = config or Config.load()
    app = FastAPI()
    templates = Jinja2Templates(directory=str(_DIR / "templates"))
    app.mount("/static", StaticFiles(directory=str(_DIR / "static")), name="static")

    def store() -> Store:
        return Store.open(config)

    def _run_pipeline(sid: int) -> None:
        # Open a fresh Store in the worker thread — sqlite connections are
        # bound to the thread that created them, so the request-thread Store
        # must not cross into the background task.
        runner.run(sid, Store.open(config), config)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        sessions = store().list_sessions()
        cleaned = sorted(p.name for p in config.cleaned_dir.glob("*.MOV")) \
            if config.cleaned_dir.is_dir() else []
        return templates.TemplateResponse(
            "index.html", {"request": request, "sessions": sessions, "cleaned": cleaned})

    @app.post("/upload")
    def upload(background: BackgroundTasks, source: str = Form(...)):
        s = store()
        src = config.cleaned_dir / source
        sid = s.create_session(video_path=str(src))
        background.add_task(_run_pipeline, sid)
        return RedirectResponse(f"/sessions/{sid}", status_code=303)

    @app.get("/sessions/{sid}", response_class=HTMLResponse)
    def session_view(request: Request, sid: int):
        s = store()
        sess = s.get_session(sid)
        speakers = {sp.id: sp for sp in s.get_speakers(sid)}
        return templates.TemplateResponse("session.html", {
            "request": request, "sess": sess, "speakers": speakers,
            "utterances": s.get_utterances(sid), "summaries": s.get_summaries(sid),
            "tags": s.get_situation_tags(sid), "links": s.get_repeated_links(sid)})

    @app.get("/media/{sid}")
    def media(sid: int):
        sess = store().get_session(sid)
        return FileResponse(sess.video_path)

    @app.post("/sessions/{sid}/tags")
    def add_tag(sid: int, kind: str = Form(...), value: str = Form(""),
                start_s: float = Form(0.0), end_s: float = Form(0.0)):
        store().add_situation_tag(sid, start_s, end_s, kind, value, "manual")
        return RedirectResponse(f"/sessions/{sid}", status_code=303)

    @app.post("/sessions/{sid}/roles")
    def set_role(sid: int, speaker_id: int = Form(...), role: str = Form(...)):
        store().set_speaker_role(speaker_id, role)
        return RedirectResponse(f"/sessions/{sid}", status_code=303)

    @app.get("/players/{name}", response_class=HTMLResponse)
    def player_view(request: Request, name: str):
        advice = store().get_advice(player=name)
        return templates.TemplateResponse(
            "player.html", {"request": request, "name": name, "advice": advice})

    return app

app = create_app  # uvicorn: `uvicorn sailog.web.app:app --factory`
```

```html
<!-- sailog/web/templates/base.html -->
<!doctype html><html lang="ja"><head><meta charset="utf-8">
<title>芝工セイルログ</title><link rel="stylesheet" href="/static/style.css"></head>
<body><header><a href="/">芝工セイルログ</a></header>
<main>{% block body %}{% endblock %}</main>
<script src="/static/seek.js"></script></body></html>
```

```html
<!-- sailog/web/templates/index.html -->
{% extends "base.html" %}{% block body %}
<h1>セッション</h1>
<form method="post" action="/upload">
  <label>クリーン動画:
    <select name="source">{% for c in cleaned %}<option>{{ c }}</option>{% endfor %}</select>
  </label><button type="submit">解析する</button>
</form>
<ul>{% for s in sessions %}
  <li><a href="/sessions/{{ s.id }}">#{{ s.id }} {{ s.video_path }}</a> — {{ s.status }}</li>
{% endfor %}</ul>
{% endblock %}
```

```html
<!-- sailog/web/templates/session.html -->
{% extends "base.html" %}{% block body %}
<h1>セッション #{{ sess.id }} — {{ sess.status }}</h1>
<video id="player" src="/media/{{ sess.id }}" controls width="640"></video>
<h2>発話</h2>
<ul>{% for u in utterances %}
  <li><a href="#" class="seek" data-t="{{ u.start_s }}">[{{ '%.1f'|format(u.start_s) }}s]</a>
  {{ speakers[u.speaker_id].role or speakers[u.speaker_id].label if u.speaker_id else '?' }}
  {% if u.target_speaker_id %}→ {{ speakers[u.target_speaker_id].role or speakers[u.target_speaker_id].label }}{% endif %}:
  {{ u.text }}</li>
{% endfor %}</ul>
<h2>選手サマリ</h2>
{% for s in summaries %}<div class="summary"><h3>{{ s.player }}</h3>
<p>{{ s.data.summary }}</p><ul>{% for a in s.data.advice %}
  <li>{{ a.category }}: {{ a.text }}</li>{% endfor %}</ul></div>{% endfor %}
{% if links %}<h2>反復指摘</h2><ul>{% for l in links %}
  <li>advice {{ l.advice_id_a }} ≈ {{ l.advice_id_b }} (類似度 {{ '%.2f'|format(l.similarity) }})</li>
{% endfor %}</ul>{% endif %}
<h2>状況タグ</h2>
<form method="post" action="/sessions/{{ sess.id }}/tags">
  種別<input name="kind"> 値<input name="value">
  開始<input name="start_s" value="0"> 終了<input name="end_s" value="0">
  <button>追加</button></form>
<ul>{% for t in tags %}<li>{{ t.kind }}={{ t.value }} ({{ t.start_s }}-{{ t.end_s }})</li>{% endfor %}</ul>
{% endblock %}
```

```html
<!-- sailog/web/templates/player.html -->
{% extends "base.html" %}{% block body %}
<h1>{{ name }} の指摘履歴</h1>
<ul>{% for a in advice %}<li>[#{{ a.session_id }}] {{ a.category }}: {{ a.text }}</li>{% endfor %}</ul>
{% endblock %}
```

```css
/* sailog/web/static/style.css */
body{font-family:system-ui,sans-serif;margin:2rem;max-width:820px}
header a{font-weight:bold;text-decoration:none}
.summary{border:1px solid #ddd;padding:.5rem 1rem;margin:.5rem 0;border-radius:8px}
.seek{margin-right:.4rem}
```

```javascript
// sailog/web/static/seek.js
document.addEventListener("click", (e) => {
  const el = e.target.closest(".seek");
  if (!el) return;
  e.preventDefault();
  const v = document.getElementById("player");
  if (v) { v.currentTime = parseFloat(el.dataset.t); v.play(); }
});
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_web.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add sailog/web/ tests/test_web.py
git commit -m "feat(web): FastAPI app, session/player views, manual tags"
```

---

## Task 13: Integration test + README + full suite

**Files:**
- Create: `tests/test_integration.py`, `README_sailog.md`, `pytest.ini`
- Test: the whole suite.

**Interfaces:**
- Consumes: everything. The integration test is opt-in (`-m integration`) and runs the real pipeline on one short cleaned clip.

- [ ] **Step 1: Write pytest.ini registering the marker**

```ini
# pytest.ini
[pytest]
markers =
    integration: runs real models on a fixture clip (slow, needs HF_TOKEN + ANTHROPIC_API_KEY)
```

- [ ] **Step 2: Write the integration test (skips if creds/clip absent)**

```python
# tests/test_integration.py
import os, pytest
from pathlib import Path
from sailog.config import Config
from sailog.db.store import Store
from sailog.pipeline import runner

pytestmark = pytest.mark.integration

def test_full_pipeline_on_clip(tmp_path):
    cfg = Config.load(root=Path(__file__).resolve().parents[1])
    clip = next(iter(sorted(cfg.cleaned_dir.glob("*.MOV"))), None)
    if not (cfg.hf_token and cfg.anthropic_api_key and clip):
        pytest.skip("needs HF_TOKEN, ANTHROPIC_API_KEY, and a cleaned clip")
    cfg = Config.load(); cfg.db_path = tmp_path / "t.db"; cfg.sessions_dir = tmp_path / "s"
    store = Store.open(cfg)
    sid = store.create_session(video_path=str(clip))
    runner.run(sid, store, cfg)
    assert store.get_session(sid).status == "done"
    assert len(store.get_utterances(sid)) > 0
```

- [ ] **Step 3: Run the full unit suite (integration deselected)**

Run: `.venv/bin/pytest -m "not integration" -v`
Expected: PASS (all unit tests across tasks 1-12)

- [ ] **Step 4: Write README_sailog.md**

Document: install (`.venv/bin/pip install -r requirements.txt`), `.env` setup (copy `.env.example`, add HF + Anthropic keys, accept pyannote model terms on HuggingFace), run the app (`.venv/bin/uvicorn sailog.web.app:app --factory --reload`), and the pipeline flow. Note that ① reuses the existing DeepFilterNet3 setup and clips in `cleaned/` are already denoised.

- [ ] **Step 5: Commit**

```bash
git add tests/test_integration.py pytest.ini README_sailog.md
git commit -m "test: opt-in integration test + README + marker config"
```

---

## Task 14: End-to-end manual verification (no code)

- [ ] **Step 1:** Fill `.env` with real `HF_TOKEN` + `ANTHROPIC_API_KEY`; accept `pyannote/speaker-diarization-3.1` terms on HuggingFace.
- [ ] **Step 2:** `.venv/bin/pip install -r requirements.txt`.
- [ ] **Step 3:** `.venv/bin/uvicorn sailog.web.app:app --factory` and open the browser.
- [ ] **Step 4:** Pick one `cleaned/*.MOV`, submit, wait for status `done` (whisper + pyannote on CPU are slow — expect minutes).
- [ ] **Step 5:** Verify on the session page: timestamped who→whom utterances that seek the video, a per-player Claude summary, and (if applicable) repeated-advice callouts. Assign coach/player roles if diarization labels need it and re-open.
- [ ] **Step 6:** Use `superpowers:verification-before-completion` to confirm before declaring the MVP done.

---

## Self-Review

**Spec coverage** (MVP spec §2 components → tasks): config → T1; DB/store → T2; ingest audio → T3; ingest drive → T4; s1 → T5; s2 → T6; s3 → T7; repeated → T8; merge → T9; s5 → T10; runner+jobs → T11; web → T12; testing/integration → T13; DoD E2E → T14. All covered.

**Placeholder scan:** No "TODO/TBD/handle edge cases". The one deferred detail — the exact Claude model id — is explicitly routed through the `claude-api` skill at T10 (a real instruction, not a placeholder), with a working default.

**Type consistency:** stage entry point is uniformly `run(session_id, store, config)`; `Store` method names in tasks 5-12 match the signatures defined in T2; `encode`/`to_vec`/`cosine`/`find_repeats` names in T8 match their use in T11; `STAGES`/`STAGE_FNS` names in T11 match T11's test.

## Build order & subagent mapping

- **Foundation (sequential):** T1, T2 — shared contract; must land first.
- **Parallel fan-out (independent subagents):** T3, T4, T5, T6, T7, T8 — all depend only on T1/T2 + fixtures.
- **Join (sequential):** T9 (needs T6/T7 output shapes), T10.
- **Integrate:** T11 (needs all stages), T12 (needs T11).
- **Verify:** T13, T14.

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
        # executescript implicitly commits before and after; no explicit commit needed.
        self.conn.executescript(_SCHEMA.read_text())

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

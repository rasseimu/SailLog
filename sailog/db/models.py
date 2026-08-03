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

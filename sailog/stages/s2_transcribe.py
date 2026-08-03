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

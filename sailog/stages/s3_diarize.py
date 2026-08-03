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

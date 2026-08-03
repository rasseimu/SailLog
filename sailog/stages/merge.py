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

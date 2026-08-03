import json
from sailog.db.store import Store
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


def _setup_merge(config):
    """Create a session with speakers + word/turn JSON files for merge.run tests."""
    store = Store.open(config)
    sid = store.create_session(video_path="v.MOV")
    out_dir = config.sessions_dir / str(sid)
    out_dir.mkdir(parents=True, exist_ok=True)
    sp0 = store.add_speaker(sid, "SPEAKER_00")
    sp1 = store.add_speaker(sid, "SPEAKER_01")
    words = [
        {"start": 0.0, "end": 0.3, "word": "もっと"},
        {"start": 0.3, "end": 0.6, "word": "引いて"},
        {"start": 1.1, "end": 1.4, "word": "はい"},
    ]
    turns = [
        {"start": 0.0, "end": 1.0, "label": "SPEAKER_00"},
        {"start": 1.0, "end": 2.0, "label": "SPEAKER_01"},
    ]
    (out_dir / "words.json").write_text(json.dumps(words), encoding="utf-8")
    (out_dir / "turns.json").write_text(json.dumps(turns), encoding="utf-8")
    return store, sid


def test_merge_run_idempotent_on_reentry(config):
    """Re-running merge after a partial failure must not duplicate utterances."""
    store, sid = _setup_merge(config)

    # First run — succeeds and sets job to "done"
    merge.run(sid, store, config)
    count_after_first = len(store.get_utterances(sid))
    assert count_after_first > 0

    # Simulate partial failure by resetting job to "error"
    store.set_job(sid, "merge", "error")

    # Second run — must clear then re-insert; count must not double
    merge.run(sid, store, config)
    count_after_second = len(store.get_utterances(sid))
    assert count_after_second == count_after_first, (
        f"Utterances doubled on re-entry: {count_after_second} != {count_after_first}"
    )

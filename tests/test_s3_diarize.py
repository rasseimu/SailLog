import json
from unittest.mock import patch
from sailog.db.store import Store
from sailog.stages import s3_diarize

_TURNS = [{"start": 0.0, "end": 1.0, "label": "SPEAKER_00"},
          {"start": 1.0, "end": 2.0, "label": "SPEAKER_01"},
          {"start": 2.0, "end": 3.0, "label": "SPEAKER_00"}]


def test_run_persists_turns_and_speakers(config):
    store = Store.open(config)
    sid = store.create_session(video_path="v.MOV")
    (config.sessions_dir / str(sid)).mkdir(parents=True)
    store.set_clean_path(sid, "clean.wav")
    with patch("sailog.stages.s3_diarize.diarize", return_value=_TURNS):
        s3_diarize.run(sid, store, config)
    labels = sorted(s.label for s in store.get_speakers(sid))
    assert labels == ["SPEAKER_00", "SPEAKER_01"]
    saved = json.loads((config.sessions_dir / str(sid) / "turns.json").read_text())
    assert len(saved) == 3
    assert store.get_job(sid, "s3").status == "done"


def test_s3_diarize_idempotent_on_reentry(config):
    """Re-running s3 after a partial failure must not duplicate speakers."""
    store = Store.open(config)
    sid = store.create_session(video_path="v.MOV")
    (config.sessions_dir / str(sid)).mkdir(parents=True)
    store.set_clean_path(sid, "clean.wav")

    # First run — succeeds
    with patch("sailog.stages.s3_diarize.diarize", return_value=_TURNS):
        s3_diarize.run(sid, store, config)
    count_after_first = len(store.get_speakers(sid))
    assert count_after_first == 2

    # Simulate partial failure by resetting job to "error"
    store.set_job(sid, "s3", "error")

    # Second run — must clear then re-insert; count must not double
    with patch("sailog.stages.s3_diarize.diarize", return_value=_TURNS):
        s3_diarize.run(sid, store, config)
    count_after_second = len(store.get_speakers(sid))
    assert count_after_second == count_after_first, (
        f"Speakers doubled on re-entry: {count_after_second} != {count_after_first}"
    )

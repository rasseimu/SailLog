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

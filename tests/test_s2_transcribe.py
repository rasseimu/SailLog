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

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

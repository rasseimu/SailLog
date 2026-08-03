import os, pytest
from pathlib import Path
from sailog.config import Config
from sailog.db.store import Store
from sailog.pipeline import runner

pytestmark = pytest.mark.integration

def test_full_pipeline_on_clip(tmp_path):
    cfg = Config.load(root=Path(__file__).resolve().parents[1])
    clip = next(iter(sorted(cfg.cleaned_dir.glob("*.MOV"))), None)
    if not (cfg.hf_token and cfg.anthropic_api_key and clip):
        pytest.skip("needs HF_TOKEN, ANTHROPIC_API_KEY, and a cleaned clip")
    cfg = Config.load(); cfg.db_path = tmp_path / "t.db"; cfg.sessions_dir = tmp_path / "s"
    store = Store.open(cfg)
    sid = store.create_session(video_path=str(clip))
    runner.run(sid, store, cfg)
    assert store.get_session(sid).status == "done"
    assert len(store.get_utterances(sid)) > 0

# tests/test_runner.py
from unittest.mock import patch
from sailog.db.store import Store
from sailog.pipeline import runner, jobs

def test_runner_calls_stages_in_order_and_marks_done(config):
    store = Store.open(config)
    sid = store.create_session(video_path="v.MOV")
    calls = []
    def make(stage):
        def fn(session_id, s, c): calls.append(stage)
        return fn
    fake = {st: make(st) for st in jobs.STAGES}
    with patch.dict(runner.STAGE_FNS, fake, clear=True):
        runner.run(sid, store, config)
    assert calls == jobs.STAGES
    assert store.get_session(sid).status == "done"

def test_runner_stops_and_marks_error(config):
    store = Store.open(config)
    sid = store.create_session(video_path="v.MOV")
    def boom(session_id, s, c): raise RuntimeError("x")
    def ok(session_id, s, c): pass
    fake = {st: ok for st in jobs.STAGES}; fake["s3"] = boom
    with patch.dict(runner.STAGE_FNS, fake, clear=True):
        try: runner.run(sid, store, config)
        except RuntimeError: pass
    assert store.get_session(sid).status == "error"

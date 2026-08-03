# tests/test_store.py
from sailog.db.store import Store

def test_schema_and_session_roundtrip(config):
    store = Store.open(config)
    sid = store.create_session(video_path="cleaned/x_cleaned.MOV", boat="470", crew="A/B")
    s = store.get_session(sid)
    assert s.status == "created"
    assert s.video_path.endswith("x_cleaned.MOV")
    store.set_clean_path(sid, "data/sessions/1/clean.wav")
    store.set_session_status(sid, "running")
    assert store.get_session(sid).status == "running"
    assert [x.id for x in store.list_sessions()] == [sid]

def test_speakers_utterances_ordered(config):
    store = Store.open(config)
    sid = store.create_session(video_path="v.MOV")
    coach = store.add_speaker(sid, "SPEAKER_00", role="coach")
    player = store.add_speaker(sid, "SPEAKER_01", role="player")
    store.add_utterance(sid, 5.0, 6.0, coach, player, "後ろ")
    store.add_utterance(sid, 1.0, 2.0, coach, player, "もっと引いて")
    utts = store.get_utterances(sid)
    assert [u.text for u in utts] == ["もっと引いて", "後ろ"]
    assert utts[0].speaker_id == coach and utts[0].target_speaker_id == player

def test_summary_json_and_advice_embedding(config):
    store = Store.open(config)
    sid = store.create_session(video_path="v.MOV")
    store.add_summary(sid, "playerA", {"summary": "good start", "points": [1, 2]})
    assert store.get_summaries(sid)[0].data["points"] == [1, 2]
    aid = store.add_advice(sid, "playerA", "trim", "もっと引いて")
    store.set_advice_embedding(aid, b"\x00\x01")
    got = store.get_advice(player="playerA")
    assert got[0].embedding == b"\x00\x01"

def test_jobs_upsert(config):
    store = Store.open(config)
    sid = store.create_session(video_path="v.MOV")
    assert store.get_job(sid, "s2") is None
    store.set_job(sid, "s2", "done")
    assert store.get_job(sid, "s2").status == "done"
    store.set_job(sid, "s2", "error", error="boom")
    j = store.get_job(sid, "s2")
    assert j.status == "error" and j.error == "boom"

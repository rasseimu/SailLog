from unittest.mock import patch
from sailog.db.store import Store
from sailog.stages import s5_summarize


def test_run_writes_summaries_and_advice(config):
    store = Store.open(config)
    sid = store.create_session(video_path="v.MOV")
    c = store.add_speaker(sid, "SPEAKER_00", role="coach")
    p = store.add_speaker(sid, "SPEAKER_01", role="player")
    store.add_utterance(sid, 0.0, 1.0, c, p, "もっと引いて")
    fake = {"players": [{"name": "SPEAKER_01", "summary": "トリム改善余地",
             "advice": [{"category": "trim", "text": "シートを引く"}]}]}
    with patch("sailog.stages.s5_summarize.call_claude", return_value=fake):
        s5_summarize.run(sid, store, config)
    sums = store.get_summaries(sid)
    assert sums[0].player == "SPEAKER_01"
    assert sums[0].data["summary"] == "トリム改善余地"
    adv = store.get_advice(session_id=sid)
    assert adv[0].text == "シートを引く" and adv[0].category == "trim"
    assert store.get_job(sid, "s5").status == "done"

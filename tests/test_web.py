from unittest.mock import patch
from fastapi.testclient import TestClient
from sailog.web.app import create_app
from sailog.db.store import Store

def test_index_lists_sessions(config):
    store = Store.open(config); store.create_session(video_path="cleaned/x_cleaned.MOV")
    client = TestClient(create_app(config))
    r = client.get("/")
    assert r.status_code == 200 and "x_cleaned.MOV" in r.text

def test_upload_creates_session_and_kicks_runner(config):
    (config.cleaned_dir).mkdir(parents=True, exist_ok=True)
    (config.cleaned_dir / "x_cleaned.MOV").write_bytes(b"fake")
    client = TestClient(create_app(config))
    with patch("sailog.web.app.runner.run") as run:
        r = client.post("/upload", data={"source": "x_cleaned.MOV"},
                        follow_redirects=False)
    assert r.status_code in (302, 303)
    assert run.called

def test_session_view_shows_utterances(config):
    store = Store.open(config)
    sid = store.create_session(video_path="cleaned/x_cleaned.MOV")
    c = store.add_speaker(sid, "SPEAKER_00", role="coach")
    p = store.add_speaker(sid, "SPEAKER_01", role="player")
    store.add_utterance(sid, 3.0, 4.0, c, p, "もっと引いて")
    client = TestClient(create_app(config))
    r = client.get(f"/sessions/{sid}")
    assert r.status_code == 200 and "もっと引いて" in r.text

def test_add_manual_tag(config):
    store = Store.open(config)
    sid = store.create_session(video_path="cleaned/x_cleaned.MOV")
    client = TestClient(create_app(config))
    client.post(f"/sessions/{sid}/tags",
                data={"kind": "wind", "value": "12kt", "start_s": "0", "end_s": "10"},
                follow_redirects=False)
    tags = store.get_situation_tags(sid)
    assert tags[0].kind == "wind" and tags[0].source == "manual"

def test_upload_rejects_path_traversal(config):
    (config.cleaned_dir).mkdir(parents=True, exist_ok=True)
    store = Store.open(config)
    client = TestClient(create_app(config))
    r = client.post("/upload", data={"source": "../../etc/passwd"},
                    follow_redirects=False)
    assert r.status_code == 400
    assert store.list_sessions() == []

def test_set_speaker_role(config):
    store = Store.open(config)
    sid = store.create_session(video_path="cleaned/x_cleaned.MOV")
    sp_id = store.add_speaker(sid, "SPEAKER_00")
    client = TestClient(create_app(config))
    r = client.post(f"/sessions/{sid}/roles",
                    data={"speaker_id": str(sp_id), "role": "coach"},
                    follow_redirects=False)
    assert r.status_code == 303
    speakers = store.get_speakers(sid)
    assert speakers[0].role == "coach"

import numpy as np
from unittest.mock import patch
from sailog.db.store import Store
from sailog.repeated import match, embed

def test_cosine_basic():
    a = np.array([1, 0], dtype=np.float32); b = np.array([1, 0], dtype=np.float32)
    assert match.cosine(a, b) == 1.0

def test_find_repeats_links_similar_advice(config):
    store = Store.open(config)
    s1 = store.create_session(video_path="v1"); s2 = store.create_session(video_path="v2")
    a1 = store.add_advice(s1, "playerA", "trim", "もっとシートを引いて")
    a2 = store.add_advice(s2, "playerA", "trim", "シートをもっと引く")
    a3 = store.add_advice(s2, "playerA", "hike", "もっとハイクアウト")
    vecs = {"もっとシートを引いて": [1.0, 0.0], "シートをもっと引く": [0.99, 0.14],
            "もっとハイクアウト": [0.0, 1.0]}
    def fake_encode(texts, cfg):
        return [np.array(vecs[t], dtype=np.float32).tobytes() for t in texts]
    with patch("sailog.repeated.match.encode", side_effect=fake_encode):
        n = match.find_repeats(s2, store, config)
    links = store.get_repeated_links(s2)
    assert n == 1 and len(links) == 1
    assert {links[0].advice_id_a, links[0].advice_id_b} == {a2, a1}

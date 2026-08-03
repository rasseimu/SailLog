from __future__ import annotations
import numpy as np
from .embed import encode, to_vec

def cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a); nb = np.linalg.norm(b)
    if na == 0 or nb == 0: return 0.0
    return float(np.dot(a, b) / (na * nb))

def find_repeats(session_id: int, store, config) -> int:
    advice = store.get_advice(session_id=session_id)
    missing = [a for a in advice if a.embedding is None]
    if missing:
        blobs = encode([a.text for a in missing], config)
        for a, blob in zip(missing, blobs):
            store.set_advice_embedding(a.id, blob)
        advice = store.get_advice(session_id=session_id)  # reload with embeddings

    # Collect and embed all prior advice for this player that's missing embeddings
    prior_missing = []
    for a in advice:
        prior = [p for p in store.get_advice(player=a.player)
                 if p.id < a.id and p.embedding is None]
        prior_missing.extend(prior)
    prior_missing = list({p.id: p for p in prior_missing}.values())  # deduplicate by id
    if prior_missing:
        blobs = encode([p.text for p in prior_missing], config)
        for p, blob in zip(prior_missing, blobs):
            store.set_advice_embedding(p.id, blob)

    created = 0
    for a in advice:
        prior = [p for p in store.get_advice(player=a.player)
                 if p.id < a.id and p.embedding is not None]
        av = to_vec(a.embedding)
        for p in prior:
            sim = cosine(av, to_vec(p.embedding))
            if sim >= config.repeated_threshold:
                store.add_repeated_link(a.id, p.id, sim)
                created += 1
    return created

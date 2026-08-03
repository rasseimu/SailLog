from __future__ import annotations
import numpy as np

_MODEL = None

def _get_model(config):
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer
        _MODEL = SentenceTransformer(config.embed_model)
    return _MODEL

def encode(texts: list[str], config) -> list[bytes]:
    model = _get_model(config)
    arr = model.encode(list(texts), convert_to_numpy=True).astype(np.float32)
    return [row.tobytes() for row in arr]

def to_vec(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)

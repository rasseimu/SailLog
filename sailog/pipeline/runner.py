# sailog/pipeline/runner.py
from __future__ import annotations
from ..stages import s1_denoise, s2_transcribe, s3_diarize, merge, s5_summarize
from ..repeated import match
from .jobs import STAGES


def _repeated(session_id, store, config):
    job = store.get_job(session_id, "repeated")
    if job and job.status == "done":
        return
    match.find_repeats(session_id, store, config)
    store.set_job(session_id, "repeated", "done")


STAGE_FNS = {
    "s1": s1_denoise.run, "s2": s2_transcribe.run, "s3": s3_diarize.run,
    "merge": merge.run, "s5": s5_summarize.run, "repeated": _repeated,
}


def run(session_id: int, store, config) -> None:
    store.set_session_status(session_id, "running")
    try:
        for stage in STAGES:
            STAGE_FNS[stage](session_id, store, config)
        store.set_session_status(session_id, "done")
    except Exception:
        store.set_session_status(session_id, "error")
        raise

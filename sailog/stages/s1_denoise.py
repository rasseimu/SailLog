from __future__ import annotations
import subprocess, time
from pathlib import Path
from ..ingest.audio import extract_audio, audio_duration

def run_deepfilter(raw_wav: Path, clean_dir: Path, expected: Path, deadline_s: float) -> None:
    # Ported verbatim from denoise_local.py — DeepFilter hangs on exit, so we
    # poll the output size and kill it once stable. See memory deepfilter-hangs-on-exit.
    deepfilter = str(Path(__file__).resolve().parents[2] / ".venv" / "bin" / "deepFilter")
    proc = subprocess.Popen([deepfilter, str(raw_wav), "-o", str(clean_dir)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    last_size = -1; stable_since = None; start = time.monotonic()
    try:
        while True:
            exited = proc.poll() is not None
            if expected.exists():
                size = expected.stat().st_size
                if size > 0 and size == last_size:
                    if stable_since is None: stable_since = time.monotonic()
                    elif time.monotonic() - stable_since >= 3: return
                else:
                    last_size = size; stable_since = None
            if exited:
                if expected.exists() and expected.stat().st_size > 0: return
                raise RuntimeError("deepFilter exited without producing output")
            if time.monotonic() - start > deadline_s:
                raise TimeoutError(f"deepFilter exceeded {deadline_s:.0f}s")
            time.sleep(1)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill()

def run(session_id: int, store, config) -> None:
    job = store.get_job(session_id, "s1")
    if job and job.status == "done":
        return
    sess = store.get_session(session_id)
    src = Path(sess.video_path)
    out_dir = config.sessions_dir / str(session_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    clean_wav = out_dir / "clean.wav"
    try:
        already_clean = "cleaned" in src.parts or src.stem.endswith("_cleaned")
        if already_clean:
            extract_audio(src, clean_wav)
        else:
            raw = out_dir / "raw.wav"
            extract_audio(src, raw)
            clean_dir = out_dir / "df"; clean_dir.mkdir(exist_ok=True)
            expected = clean_dir / f"{raw.stem}_DeepFilterNet3.wav"
            deadline = max(300.0, audio_duration(src) * 2.0 + 120.0)
            run_deepfilter(raw, clean_dir, expected, deadline)
            expected.replace(clean_wav)
        store.set_clean_path(session_id, str(clean_wav))
        store.set_job(session_id, "s1", "done")
    except Exception as e:
        store.set_job(session_id, "s1", "error", error=str(e)); raise

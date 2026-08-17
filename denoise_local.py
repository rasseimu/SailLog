#!/usr/bin/env python3
"""
Local denoise pipeline: gdrive/ -> cleaned/

For every .MOV/.mov in INPUT_DIR, extract the audio, denoise it with
DeepFilterNet3, mux the cleaned audio back onto the (untouched) video stream,
and write <name>_cleaned.MOV to OUTPUT_DIR. Files already present in OUTPUT_DIR
are skipped, so re-runs are resumable.

Run:
    .venv/bin/python denoise_local.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# --- Config -----------------------------------------------------------------

INPUT_DIR = Path(__file__).with_name("gdrive")
OUTPUT_DIR = Path(__file__).with_name("cleaned")

DEEPFILTER = str(Path(__file__).with_name(".venv") / "bin" / "deepFilter")
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

AUDIO_BITRATE = "192k"
OUTPUT_SUFFIX = "_cleaned"


# --- Helpers ----------------------------------------------------------------


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command, raising on failure and surfacing captured stderr."""
    try:
        return subprocess.run(cmd, check=True, text=True, **kwargs)
    except subprocess.CalledProcessError as e:
        if e.stderr:
            print(e.stderr.strip(), file=sys.stderr)
        raise


def run_deepfilter(raw_wav: Path, clean_dir: Path, expected: Path,
                   deadline_s: float) -> None:
    """
    Run deepFilter, but don't wait for the process to exit.

    DeepFilterNet finishes writing its output wav and then hangs indefinitely
    on shutdown (a torch/torchaudio cleanup deadlock on macOS). So instead of
    blocking on process exit, we watch for the output file to appear and stop
    growing, then terminate the hung process ourselves.
    """
    proc = subprocess.Popen(
        [DEEPFILTER, str(raw_wav), "-o", str(clean_dir)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    last_size = -1
    stable_since: float | None = None
    start = time.monotonic()
    try:
        while True:
            exited = proc.poll() is not None

            if expected.exists():
                size = expected.stat().st_size
                if size > 0 and size == last_size:
                    if stable_since is None:
                        stable_since = time.monotonic()
                    # output present and unchanged for 3s -> done
                    elif time.monotonic() - stable_since >= 3:
                        return
                else:
                    last_size = size
                    stable_since = None

            if exited:
                # process ended on its own; give the file a beat to flush
                if expected.exists() and expected.stat().st_size > 0:
                    return
                raise RuntimeError("deepFilter exited without producing output")

            if time.monotonic() - start > deadline_s:
                raise TimeoutError(
                    f"deepFilter exceeded {deadline_s:.0f}s without stable output")

            time.sleep(1)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def audio_duration(path: Path) -> float:
    """Return the media duration in seconds, or 0.0 if it can't be read."""
    try:
        out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                   "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                  capture_output=True).stdout.strip()
        return float(out)
    except Exception:  # noqa: BLE001
        return 0.0


def process_one(src_mov: Path, workdir: Path) -> Path:
    """Extract audio, denoise, remux one MOV. Returns the cleaned output file."""
    stem = src_mov.stem
    raw_wav = workdir / f"{stem}.wav"
    clean_dir = workdir / "clean"
    clean_dir.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_mov = OUTPUT_DIR / f"{stem}{OUTPUT_SUFFIX}.MOV"

    print("  ♪ extracting audio")
    run([FFMPEG, "-y", "-i", str(src_mov), "-vn",
         "-acodec", "pcm_s16le", str(raw_wav)],
        capture_output=True)

    print("  ✦ denoising (DeepFilterNet3)")
    clean_wav = clean_dir / f"{stem}_DeepFilterNet3.wav"
    # DeepFilter runs ~16x faster than realtime on CPU; give a generous
    # backstop deadline before assuming it's genuinely stuck.
    deadline = max(300.0, audio_duration(src_mov) * 2.0 + 120.0)
    run_deepfilter(raw_wav, clean_dir, clean_wav, deadline)
    if not clean_wav.exists():
        candidates = list(clean_dir.glob("*.wav"))
        if not candidates:
            raise FileNotFoundError("DeepFilter produced no output wav")
        clean_wav = candidates[0]

    print("  ⧉ muxing cleaned audio onto video")
    run([FFMPEG, "-y",
         "-i", str(src_mov),
         "-i", str(clean_wav),
         "-map", "0:v:0", "-map", "1:a:0",
         "-c:v", "copy", "-c:a", "aac", "-b:a", AUDIO_BITRATE,
         "-shortest", str(out_mov)],
        capture_output=True)

    return out_mov


def main() -> int:
    if not INPUT_DIR.is_dir():
        print(f"Input folder not found: {INPUT_DIR}", file=sys.stderr)
        return 1

    src_movs = sorted(
        p for p in INPUT_DIR.iterdir()
        if p.is_file() and p.suffix.lower() == ".mov"
    )
    if not src_movs:
        print(f"No .MOV files found in {INPUT_DIR}. Nothing to do.")
        return 0

    OUTPUT_DIR.mkdir(exist_ok=True)
    existing = {p.name for p in OUTPUT_DIR.iterdir() if p.is_file()}
    print(f"Found {len(src_movs)} MOV(s) in {INPUT_DIR.name}/; "
          f"writing to {OUTPUT_DIR.name}/\n")

    processed = skipped = failed = 0

    for i, src_mov in enumerate(src_movs, 1):
        out_name = f"{src_mov.stem}{OUTPUT_SUFFIX}.MOV"
        prefix = f"[{i}/{len(src_movs)}] {src_mov.name}"
        if out_name in existing:
            print(f"{prefix} → already done, skipping")
            skipped += 1
            continue

        print(prefix)
        workdir = Path(tempfile.mkdtemp(prefix="denoise_"))
        try:
            out_mov = process_one(src_mov, workdir)
            processed += 1
            print(f"  ✓ done: {out_mov.name}")
        except subprocess.CalledProcessError as e:
            failed += 1
            print(f"  ✗ FAILED on {src_mov.name}: command exited "
                  f"{e.returncode}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001 - keep processing remaining files
            failed += 1
            print(f"  ✗ FAILED on {src_mov.name}: {e}", file=sys.stderr)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    print(f"\nSummary: {processed} processed, {skipped} skipped, {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

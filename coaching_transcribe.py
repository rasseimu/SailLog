#!/usr/bin/env python3
"""
Coaching-video denoise + transcription pipeline (コーチング(beta)).

For every video under

    My Drive/練習動画/コーチング(beta)/            (excluding cleaned_video/)

this script:

  1. extracts the audio,
  2. denoises it with DeepFilterNet3 (using the poll-and-kill workaround for
     DeepFilter's macOS shutdown hang — see denoise_local.py),
  3. muxes the cleaned audio back onto the untouched video stream and writes it
     to  コーチング(beta)/cleaned_video/<same date subfolder>/<name>_cleaned.MOV,
  4. transcribes the *denoised* audio with faster-whisper (Japanese), and
  5. appends one row **per speech segment** to a CSV, linking every segment to
     both the original and the cleaned video.

The run is resumable: videos already present in the CSV *and* whose cleaned
output already exists are skipped, so you can stop and re-run any time.

    .venv/bin/python coaching_transcribe.py            # process everything
    .venv/bin/python coaching_transcribe.py --limit 2  # smoke test on 2 files
    .venv/bin/python coaching_transcribe.py --model large-v3
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# --- Config -----------------------------------------------------------------

COACHING_DIR = Path(
    "/Users/reimurase/Library/CloudStorage/"
    "GoogleDrive-cy23247@shibaura-it.ac.jp/マイドライブ/練習動画/コーチング(beta)"
)
CLEANED_SUBDIR = "cleaned_video"          # output dir *inside* COACHING_DIR
CSV_PATH = COACHING_DIR / "transcripts.csv"

WHISPER_MODEL = "medium"                  # overridable with --model
WHISPER_LANG = "ja"

VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".avi"}

DEEPFILTER = str(Path(__file__).with_name(".venv") / "bin" / "deepFilter")
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

AUDIO_BITRATE = "192k"
OUTPUT_SUFFIX = "_cleaned"

CSV_FIELDS = [
    "source_video",     # path relative to コーチング(beta)
    "cleaned_video",    # path relative to コーチング(beta)
    "date_folder",      # top-level date subfolder name
    "num_segments",     # number of speech segments detected
    "transcript",       # full transcript for the whole video (one cell)
]

# Joined with no separator: Japanese text doesn't use spaces between clauses.
SEGMENT_JOINER = ""


# --- Shell helpers ----------------------------------------------------------


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command, raising on failure and surfacing captured stderr."""
    try:
        return subprocess.run(cmd, check=True, text=True, **kwargs)
    except subprocess.CalledProcessError as e:
        if e.stderr:
            print(e.stderr.strip(), file=sys.stderr)
        raise


def audio_duration(path: Path) -> float:
    """Return the media duration in seconds, or 0.0 if it can't be read."""
    try:
        out = run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                   "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                  capture_output=True).stdout.strip()
        return float(out)
    except Exception:  # noqa: BLE001
        return 0.0


def run_deepfilter(raw_wav: Path, clean_dir: Path, expected: Path,
                   deadline_s: float) -> None:
    """
    Run deepFilter, but don't wait for the process to exit.

    DeepFilterNet finishes writing its output wav and then hangs indefinitely on
    shutdown (a torch/torchaudio cleanup deadlock on macOS). So instead of
    blocking on process exit, watch for the output file to appear and stop
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
                    elif time.monotonic() - stable_since >= 3:
                        return  # output present and unchanged for 3s -> done
                else:
                    last_size = size
                    stable_since = None

            if exited:
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


# --- Pipeline ---------------------------------------------------------------


def find_videos(root: Path) -> list[Path]:
    """All videos under root, excluding the cleaned_video/ output tree."""
    cleaned_root = root / CLEANED_SUBDIR
    out: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if cleaned_root in p.parents:
            continue
        if p.suffix.lower() in VIDEO_EXTS:
            out.append(p)
    return sorted(out)


def cleaned_path_for(src: Path, root: Path) -> Path:
    """Mirror src's date-subfolder structure under cleaned_video/."""
    rel = src.relative_to(root)
    return root / CLEANED_SUBDIR / rel.parent / f"{src.stem}{OUTPUT_SUFFIX}.MOV"


def denoise_and_mux(src: Path, out_mov: Path, workdir: Path) -> Path:
    """Extract audio, denoise it, and return the cleaned wav (also writes out_mov)."""
    stem = src.stem
    raw_wav = workdir / f"{stem}.wav"
    clean_dir = workdir / "clean"
    clean_dir.mkdir(exist_ok=True)

    print("  ♪ extracting audio")
    run([FFMPEG, "-y", "-i", str(src), "-vn",
         "-acodec", "pcm_s16le", str(raw_wav)],
        capture_output=True)

    print("  ✦ denoising (DeepFilterNet3)")
    clean_wav = clean_dir / f"{stem}_DeepFilterNet3.wav"
    deadline = max(300.0, audio_duration(src) * 2.0 + 120.0)
    run_deepfilter(raw_wav, clean_dir, clean_wav, deadline)
    if not clean_wav.exists():
        candidates = list(clean_dir.glob("*.wav"))
        if not candidates:
            raise FileNotFoundError("DeepFilter produced no output wav")
        clean_wav = candidates[0]

    print("  ⧉ muxing cleaned audio onto video")
    out_mov.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = workdir / out_mov.name
    run([FFMPEG, "-y",
         "-i", str(src),
         "-i", str(clean_wav),
         "-map", "0:v:0", "-map", "1:a:0",
         "-c:v", "copy", "-c:a", "aac", "-b:a", AUDIO_BITRATE,
         "-shortest", str(tmp_out)],
        capture_output=True)
    # Write to a temp file first, then move into place so a crash mid-encode
    # never leaves a truncated file that a resume would treat as "done".
    shutil.move(str(tmp_out), str(out_mov))
    return clean_wav


def transcribe(clean_wav: Path, model) -> list[dict]:
    """Return speech segments: [{index, start, end, text}, ...]."""
    segments, _ = model.transcribe(
        str(clean_wav), language=WHISPER_LANG, beam_size=5, vad_filter=True,
        condition_on_previous_text=False)
    rows: list[dict] = []
    for i, seg in enumerate(segments):
        text = seg.text.strip()
        if not text:
            continue
        rows.append({"index": i, "start": float(seg.start),
                     "end": float(seg.end), "text": text})
    return rows


def load_done_sources(csv_path: Path) -> set[str]:
    """Relative source paths already present in the CSV."""
    if not csv_path.exists():
        return set()
    done: set[str] = set()
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            src = row.get("source_video")
            if src:
                done.add(src)
    return done


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0,
                    help="process at most N videos (0 = all)")
    ap.add_argument("--model", default=WHISPER_MODEL,
                    help=f"faster-whisper model (default: {WHISPER_MODEL})")
    args = ap.parse_args()

    if not COACHING_DIR.is_dir():
        print(f"Coaching folder not found: {COACHING_DIR}", file=sys.stderr)
        return 1

    videos = find_videos(COACHING_DIR)
    if not videos:
        print("No videos found. Nothing to do.")
        return 0

    done_sources = load_done_sources(CSV_PATH)
    print(f"Found {len(videos)} video(s); {len(done_sources)} already in "
          f"{CSV_PATH.name}.")
    print(f"Loading faster-whisper model '{args.model}' (CPU, int8) …")
    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8")

    csv_is_new = not CSV_PATH.exists()
    csv_file = CSV_PATH.open("a", encoding="utf-8-sig", newline="")
    writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
    if csv_is_new:
        writer.writeheader()
        csv_file.flush()

    processed = skipped = failed = 0
    considered = 0

    try:
        for src in videos:
            rel = src.relative_to(COACHING_DIR)
            out_mov = cleaned_path_for(src, COACHING_DIR)
            rel_out = out_mov.relative_to(COACHING_DIR)
            date_folder = rel.parts[0] if len(rel.parts) > 1 else ""

            if str(rel) in done_sources and out_mov.exists():
                skipped += 1
                continue

            considered += 1
            if args.limit and considered > args.limit:
                considered -= 1
                break

            print(f"\n• {rel}")
            workdir = Path(tempfile.mkdtemp(prefix="coach_"))
            try:
                clean_wav = denoise_and_mux(src, out_mov, workdir)
                print("  📝 transcribing")
                segs = transcribe(clean_wav, model)
                full_text = SEGMENT_JOINER.join(s["text"] for s in segs)
                writer.writerow({
                    "source_video": str(rel),
                    "cleaned_video": str(rel_out),
                    "date_folder": date_folder,
                    "num_segments": len(segs),
                    "transcript": full_text,
                })
                csv_file.flush()
                done_sources.add(str(rel))
                processed += 1
                print(f"  ✓ done: {rel_out}  ({len(segs)} segments)")
            except subprocess.CalledProcessError as e:
                failed += 1
                print(f"  ✗ FAILED on {rel}: command exited {e.returncode}",
                      file=sys.stderr)
            except Exception as e:  # noqa: BLE001 - keep going on remaining files
                failed += 1
                print(f"  ✗ FAILED on {rel}: {e}", file=sys.stderr)
            finally:
                shutil.rmtree(workdir, ignore_errors=True)
    finally:
        csv_file.close()

    print(f"\nSummary: {processed} processed, {skipped} skipped, "
          f"{failed} failed. CSV → {CSV_PATH}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

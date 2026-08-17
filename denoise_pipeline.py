#!/usr/bin/env python3
"""
Denoise pipeline: Google Drive -> Google Drive.

For every .MOV in the source Drive folder, extract the audio, denoise it with
DeepFilterNet3, mux the cleaned audio back onto the (untouched) video stream,
and upload the result as <name>_cleaned.MOV to the destination Drive folder.

Files whose _cleaned output already exists in the destination are skipped, so
re-runs are cheap and resumable.

Drive I/O uses rclone. Set up a remote once (see README notes at the bottom):

    rclone config      # create a Google Drive remote named "gdrive"

Then run:

    .venv/bin/python denoise_pipeline.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# --- Config -----------------------------------------------------------------

RCLONE_REMOTE = "gdrive"  # name of the rclone remote (from `rclone config`)

# Folder IDs taken from the Drive URLs (.../folders/<ID>)
SRC_FOLDER_ID = "1E4D6uMGz6PjKD7WeUQEJBbf8u0fooVTs"
DST_FOLDER_ID = "1bsYMAbIGWkk4oGBHkyZtec6bWCIeEIi8"

DEEPFILTER = str(Path(__file__).with_name(".venv") / "bin" / "deepFilter")
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
RCLONE = shutil.which("rclone") or "rclone"

AUDIO_BITRATE = "192k"
OUTPUT_SUFFIX = "_cleaned"

# Local directory where cleaned MOVs are written (and kept) before upload.
OUTPUT_DIR = Path(__file__).with_name("cleaned")


# --- Helpers ----------------------------------------------------------------


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command, raising on failure and surfacing captured stderr."""
    try:
        return subprocess.run(cmd, check=True, text=True, **kwargs)
    except subprocess.CalledProcessError as e:
        if e.stderr:
            print(e.stderr.strip(), file=sys.stderr)
        raise


def rclone_lsf(folder_id: str, extra: list[str] | None = None) -> list[str]:
    """List file names in a Drive folder (addressed by ID)."""
    cmd = [
        RCLONE, "lsf",
        f"{RCLONE_REMOTE}:",
        "--drive-root-folder-id", folder_id,
    ] + (extra or [])
    out = run(cmd, capture_output=True).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def rclone_copy_down(folder_id: str, remote_path: str, dest_dir: Path) -> None:
    run([
        RCLONE, "copyto",
        f"{RCLONE_REMOTE}:{remote_path}",
        str(dest_dir / Path(remote_path).name),
        "--drive-root-folder-id", folder_id,
    ])


def rclone_copy_up(folder_id: str, local_file: Path) -> None:
    run([
        RCLONE, "copyto",
        str(local_file),
        f"{RCLONE_REMOTE}:{local_file.name}",
        "--drive-root-folder-id", folder_id,
    ])


def process_one(remote_path: str, workdir: Path) -> Path:
    """Download, denoise, remux one MOV. Returns the local cleaned file."""
    stem = Path(remote_path).stem
    local_mov = workdir / Path(remote_path).name
    raw_wav = workdir / f"{stem}.wav"
    clean_dir = workdir / "clean"
    clean_dir.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_mov = OUTPUT_DIR / f"{stem}{OUTPUT_SUFFIX}.MOV"

    print(f"  ↓ downloading {remote_path}")
    rclone_copy_down(SRC_FOLDER_ID, remote_path, workdir)

    print("  ♪ extracting audio")
    run([FFMPEG, "-y", "-i", str(local_mov), "-vn",
         "-acodec", "pcm_s16le", str(raw_wav)],
        capture_output=True)

    print("  ✦ denoising (DeepFilterNet3)")
    run([DEEPFILTER, str(raw_wav), "-o", str(clean_dir)], capture_output=True)
    # deepFilter names its output <stem>_DeepFilterNet3.wav
    clean_wav = clean_dir / f"{stem}_DeepFilterNet3.wav"
    if not clean_wav.exists():
        # fall back to whatever single wav landed in the output dir
        candidates = list(clean_dir.glob("*.wav"))
        if not candidates:
            raise FileNotFoundError("DeepFilter produced no output wav")
        clean_wav = candidates[0]

    print("  ⧉ muxing cleaned audio onto video")
    run([FFMPEG, "-y",
         "-i", str(local_mov),
         "-i", str(clean_wav),
         "-map", "0:v:0", "-map", "1:a:0",
         "-c:v", "copy", "-c:a", "aac", "-b:a", AUDIO_BITRATE,
         "-shortest", str(out_mov)],
        capture_output=True)

    return out_mov


def main() -> int:
    print(f"Listing source folder {SRC_FOLDER_ID} …")
    src_movs = rclone_lsf(
        SRC_FOLDER_ID,
        ["-R", "--include", "*.MOV", "--include", "*.mov"],
    )
    if not src_movs:
        print("No .MOV files found in the source folder. Nothing to do.")
        return 0

    dst_existing = set(rclone_lsf(DST_FOLDER_ID))
    print(f"Found {len(src_movs)} source MOV(s); "
          f"{len(dst_existing)} file(s) already in destination.\n")

    processed = skipped = failed = 0

    for remote_path in src_movs:
        stem = Path(remote_path).stem
        out_name = f"{stem}{OUTPUT_SUFFIX}.MOV"
        if out_name in dst_existing:
            print(f"• {remote_path} → already done, skipping")
            skipped += 1
            continue

        print(f"• {remote_path}")
        workdir = Path(tempfile.mkdtemp(prefix="denoise_"))
        try:
            out_mov = process_one(remote_path, workdir)
            print(f"  ↑ uploading {out_mov.name}")
            rclone_copy_up(DST_FOLDER_ID, out_mov)
            processed += 1
            print(f"  ✓ done: {out_name}")
        except subprocess.CalledProcessError as e:
            failed += 1
            print(f"  ✗ FAILED on {remote_path}: command exited "
                  f"{e.returncode}", file=sys.stderr)
            if e.stderr:
                print(e.stderr[-2000:], file=sys.stderr)
        except Exception as e:  # noqa: BLE001 - keep processing remaining files
            failed += 1
            print(f"  ✗ FAILED on {remote_path}: {e}", file=sys.stderr)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    print(f"\nSummary: {processed} processed, {skipped} skipped, {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

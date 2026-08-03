from __future__ import annotations
import shutil, subprocess, sys
from pathlib import Path

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, check=True, text=True, **kw)
    except subprocess.CalledProcessError as e:
        if e.stderr: print(e.stderr.strip(), file=sys.stderr)
        raise

def extract_audio(src: Path, out_wav: Path) -> Path:
    _run([FFMPEG, "-y", "-i", str(src), "-vn", "-acodec", "pcm_s16le", str(out_wav)],
         capture_output=True)
    return out_wav

def mux_audio(src_video: Path, audio: Path, out: Path, bitrate: str = "192k") -> Path:
    _run([FFMPEG, "-y", "-i", str(src_video), "-i", str(audio),
          "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
          "-b:a", bitrate, "-shortest", str(out)], capture_output=True)
    return out

def audio_duration(path: Path) -> float:
    try:
        out = _run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                   capture_output=True).stdout.strip()
        return float(out)
    except Exception:
        return 0.0

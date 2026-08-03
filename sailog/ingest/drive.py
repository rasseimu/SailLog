from __future__ import annotations
import shutil, subprocess, sys
from pathlib import Path

RCLONE = shutil.which("rclone") or "rclone"

def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        if e.stderr: print(e.stderr.strip(), file=sys.stderr)
        raise

def list_remote(config, folder_id: str) -> list[str]:
    out = _run([RCLONE, "lsf", f"{config.rclone_remote}:",
                "--drive-root-folder-id", folder_id]).stdout
    return [ln for ln in out.splitlines() if ln.strip()]

def pull(config, folder_id: str, name: str, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    _run([RCLONE, "copy", f"{config.rclone_remote}:{name}",
          str(dest), "--drive-root-folder-id", folder_id])
    return dest / name

def push(config, local: Path, folder_id: str) -> None:
    _run([RCLONE, "copy", str(local), f"{config.rclone_remote}:",
          "--drive-root-folder-id", folder_id])

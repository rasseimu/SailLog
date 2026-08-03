from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path


def _parse_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


@dataclass
class Config:
    root: Path
    data_dir: Path
    db_path: Path
    sessions_dir: Path
    cleaned_dir: Path
    gdrive_dir: Path
    hf_token: str | None = None
    anthropic_api_key: str | None = None
    rclone_remote: str = "gdrive"
    src_folder_id: str | None = None
    dst_folder_id: str | None = None
    whisper_model: str = "large-v3"
    embed_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    repeated_threshold: float = 0.75

    @classmethod
    def load(cls, root: Path | None = None) -> "Config":
        root = Path(root) if root else Path(__file__).resolve().parents[1]
        env = {**_parse_dotenv(root / ".env"), **os.environ}
        data = root / "data"
        return cls(
            root=root,
            data_dir=data,
            db_path=data / "sailog.db",
            sessions_dir=data / "sessions",
            cleaned_dir=root / "cleaned",
            gdrive_dir=root / "gdrive",
            hf_token=env.get("HF_TOKEN"),
            anthropic_api_key=env.get("ANTHROPIC_API_KEY"),
            rclone_remote=env.get("RCLONE_REMOTE", "gdrive"),
            src_folder_id=env.get("SRC_FOLDER_ID"),
            dst_folder_id=env.get("DST_FOLDER_ID"),
        )

from pathlib import Path
from sailog.config import Config

def test_load_reads_env_and_resolves_paths(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "HF_TOKEN=hf_abc\nANTHROPIC_API_KEY=sk-xyz\nRCLONE_REMOTE=gdrive\n"
    )
    monkeypatch.delenv("HF_TOKEN", raising=False)
    cfg = Config.load(root=tmp_path)
    assert cfg.hf_token == "hf_abc"
    assert cfg.anthropic_api_key == "sk-xyz"
    assert cfg.rclone_remote == "gdrive"
    assert cfg.db_path == tmp_path / "data" / "sailog.db"
    assert cfg.sessions_dir == tmp_path / "data" / "sessions"
    assert cfg.whisper_model == "large-v3"

def test_os_environ_overrides_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("HF_TOKEN=from_file\n")
    monkeypatch.setenv("HF_TOKEN", "from_env")
    cfg = Config.load(root=tmp_path)
    assert cfg.hf_token == "from_env"

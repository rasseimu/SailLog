from pathlib import Path
from unittest.mock import patch, MagicMock
from sailog.ingest import audio

def test_extract_audio_builds_correct_cmd(tmp_path):
    src = tmp_path / "a.MOV"; out = tmp_path / "a.wav"
    with patch("sailog.ingest.audio.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stderr="")
        result = audio.extract_audio(src, out)
    cmd = run.call_args.args[0]
    assert "-vn" in cmd and "pcm_s16le" in cmd
    assert cmd[-1] == str(out) and result == out

def test_mux_audio_maps_streams(tmp_path):
    with patch("sailog.ingest.audio.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stderr="")
        audio.mux_audio(tmp_path/"v.MOV", tmp_path/"c.wav", tmp_path/"o.MOV")
    cmd = run.call_args.args[0]
    assert "0:v:0" in cmd and "1:a:0" in cmd and "copy" in cmd

def test_audio_duration_parses_ffprobe(tmp_path):
    with patch("sailog.ingest.audio.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="12.5\n", stderr="")
        assert audio.audio_duration(tmp_path/"a.MOV") == 12.5

def test_audio_duration_returns_zero_on_error(tmp_path):
    with patch("sailog.ingest.audio.subprocess.run", side_effect=Exception("nope")):
        assert audio.audio_duration(tmp_path/"a.MOV") == 0.0

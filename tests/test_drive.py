from pathlib import Path
from unittest.mock import patch, MagicMock
from sailog.ingest import drive

def test_list_remote_parses_lines(config):
    with patch("sailog.ingest.drive.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="a.MOV\nb.MOV\n", stderr="")
        names = drive.list_remote(config, "FOLDER")
    assert names == ["a.MOV", "b.MOV"]
    cmd = run.call_args.args[0]
    assert "lsf" in cmd and "FOLDER" in cmd

def test_pull_builds_copy_cmd(config, tmp_path):
    with patch("sailog.ingest.drive.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        out = drive.pull(config, "FOLDER", "a.MOV", tmp_path)
    cmd = run.call_args.args[0]
    assert "copy" in cmd and out == tmp_path / "a.MOV"

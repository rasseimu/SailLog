import pytest
from pathlib import Path
from sailog.config import Config

@pytest.fixture
def config(tmp_path) -> Config:
    return Config.load(root=tmp_path)

import os
from pathlib import Path
from server import config

def test_get_root_defaults_to_repo_root():
    # server/config.py -> parents[1] is the repo root
    assert (config.get_root() / "CLAUDE.md").exists()

def test_get_root_honors_env(monkeypatch, tmp_path):
    monkeypatch.setenv("QTS_ROOT", str(tmp_path))
    assert config.get_root() == tmp_path
    assert config.data_dir() == tmp_path / "data"
    assert config.views_file() == tmp_path / "views.yaml"
    assert config.snapshot_file() == tmp_path / "data" / ".snapshot.json"

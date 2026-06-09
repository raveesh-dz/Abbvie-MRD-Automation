import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo_copy(tmp_path, monkeypatch):
    """A writable temp copy of the repo bits the dashboard touches.
    Sets QTS_ROOT so every server.config path resolves into the copy."""
    for d in ("data", "metadata", "scripts", "web"):
        src = REPO / d
        if src.exists():
            shutil.copytree(src, tmp_path / d)
    (tmp_path / "web").mkdir(exist_ok=True)  # always present for the static mount
    # copy the existing run folders the seeder reads from
    out = tmp_path / "output"
    out.mkdir(exist_ok=True)
    for run in ("run_2026-06-08_001", "run_2026-06-08_002"):
        src = REPO / "output" / run
        if src.exists():
            shutil.copytree(src, out / run)
    # copy views.yaml if it already exists in the repo
    if (REPO / "views.yaml").exists():
        shutil.copy2(REPO / "views.yaml", tmp_path / "views.yaml")
    monkeypatch.setenv("QTS_ROOT", str(tmp_path))
    return tmp_path

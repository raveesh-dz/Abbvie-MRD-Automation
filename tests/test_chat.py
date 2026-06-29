from pathlib import Path

from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]


def _client(repo_copy):
    # chat endpoints need no seeded views; lifespan still inits the snapshot.
    from server.app import create_app
    return TestClient(create_app())


def test_engine_chat_dir(repo_copy):
    from server import config
    assert config.engine_chat_dir() == repo_copy / "engine_chat"

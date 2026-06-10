# tests/test_engine.py
import json
import os, subprocess, sys
from pathlib import Path

from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]


def _client(repo_copy):
    vy = repo_copy / "views.yaml"
    if not vy.exists():
        vy.write_text((REPO / "views.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    subprocess.run([sys.executable, str(REPO / "scripts" / "seed_views.py")],
                   env={**os.environ, "QTS_ROOT": str(repo_copy)}, check=True)
    from server.app import create_app
    return TestClient(create_app())


def test_ask_writes_inbox_item(repo_copy):
    with _client(repo_copy) as c:
        r = c.post("/api/engine/ask",
                   json={"question": "humira split", "build_deck": True}).json()
        assert r["status"] == "queued" and r["build_deck"] is True
        f = repo_copy / "engine_inbox" / f"{r['id']}.json"
        assert f.exists()
        assert json.loads(f.read_text(encoding="utf-8"))["question"] == "humira split"


def test_ask_rejects_empty_question(repo_copy):
    with _client(repo_copy) as c:
        assert c.post("/api/engine/ask", json={"question": "  "}).status_code == 400


def test_engine_list_and_get(repo_copy):
    with _client(repo_copy) as c:
        a = c.post("/api/engine/ask", json={"question": "q1"}).json()
        b = c.post("/api/engine/ask", json={"question": "q2"}).json()
        items = c.get("/api/engine").json()
        assert [i["id"] for i in items[:2]] == [b["id"], a["id"]]   # newest first
        assert c.get(f"/api/engine/{a['id']}").json()["question"] == "q1"
        assert c.get("/api/engine/nope").status_code == 404

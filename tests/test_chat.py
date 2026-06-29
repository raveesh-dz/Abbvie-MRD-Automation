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


def test_get_empty_returns_null(repo_copy):
    from server import chat
    assert chat.get_active() == {"thread_id": None}


def test_reset_turn_on_empty_returns_null(repo_copy):
    from server import chat
    assert chat.reset_turn() == {"thread_id": None}


def test_post_creates_thread_and_takes_engine_turn(repo_copy):
    from server import chat
    t = chat.post_message("weekly tremfya by indication")
    assert t["turn"] == "engine" and t["status"] == "awaiting_engine"
    assert t["messages"][0]["seq"] == 1
    assert t["messages"][0]["text"] == "weekly tremfya by indication"
    assert t["thread_id"].startswith("chat_")
    assert (repo_copy / "engine_chat" / "active.json").exists()


def test_post_empty_text_raises(repo_copy):
    import pytest
    from server import chat
    with pytest.raises(ValueError):
        chat.post_message("   ")


def test_post_while_engine_turn_conflicts(repo_copy):
    import pytest
    from server import chat
    chat.post_message("q1")
    with pytest.raises(chat.Conflict):
        chat.post_message("q2")


def test_reset_turn_then_second_message_increments_seq(repo_copy):
    from server import chat
    chat.post_message("q1")
    r = chat.reset_turn()
    assert r["turn"] == "user" and r["engine_status"] is None
    assert r["status"] == "awaiting_user"
    t = chat.post_message("q2", in_reply_to=1, chosen="q2")
    assert [m["seq"] for m in t["messages"]] == [1, 2]
    assert t["messages"][-1]["in_reply_to"] == 1
    assert t["messages"][-1]["chosen"] == "q2"


def test_new_archives_nonempty_and_clears(repo_copy):
    import pytest
    from server import chat
    t = chat.post_message("q1")
    tid = t["thread_id"]
    with pytest.raises(chat.Conflict):
        chat.new_chat()                       # engine turn, no force
    assert chat.new_chat(force=True) == {"thread_id": None}
    assert chat.get_active() == {"thread_id": None}
    assert (repo_copy / "engine_chat" / "archive" / f"{tid}.json").exists()


def test_post_cross_process_write_conflicts(repo_copy, monkeypatch):
    # Drive the detect-and-reject branch: a second _read_raw (the post-lock
    # re-read) returns different bytes than the first, as if the loop wrote mid-hold.
    import pytest
    from server import chat
    real = chat._read_raw
    calls = {"n": 0}

    def racy():
        calls["n"] += 1
        return '{"thread_id":"chat_x","turn":"user","messages":[]}' if calls["n"] == 2 else real()

    monkeypatch.setattr(chat, "_read_raw", racy)
    with pytest.raises(chat.Conflict):
        chat.post_message("q1")


def test_api_post_and_get(repo_copy):
    with _client(repo_copy) as c:
        t = c.post("/api/chat/message", json={"text": "weekly tremfya by indication"}).json()
        assert t["turn"] == "engine"
        assert c.get("/api/chat").json()["messages"][0]["text"] == "weekly tremfya by indication"


def test_api_empty_text_400(repo_copy):
    with _client(repo_copy) as c:
        assert c.post("/api/chat/message", json={"text": "  "}).status_code == 400


def test_api_engine_turn_409(repo_copy):
    with _client(repo_copy) as c:
        c.post("/api/chat/message", json={"text": "q1"})
        assert c.post("/api/chat/message", json={"text": "q2"}).status_code == 409


def test_api_reset_turn(repo_copy):
    with _client(repo_copy) as c:
        c.post("/api/chat/message", json={"text": "q1"})
        t = c.post("/api/chat/reset-turn").json()
        assert t["turn"] == "user"
        assert c.post("/api/chat/message", json={"text": "q2"}).status_code == 200


def test_api_new_force_and_guard(repo_copy):
    with _client(repo_copy) as c:
        c.post("/api/chat/message", json={"text": "q1"})
        assert c.post("/api/chat/new").status_code == 409
        assert c.post("/api/chat/new", json={"force": True}).json() == {"thread_id": None}
        assert c.get("/api/chat").json() == {"thread_id": None}

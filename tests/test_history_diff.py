# tests/test_history_diff.py
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


def _write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_diff_new_rows_and_deltas(repo_copy):
    folder = repo_copy / "output" / "tremfya_ibd_split"
    _write(folder / "result_prev.csv",
           "WEEK_ENDING,UC,CD,TOTAL\n2026-05-01,100,200,300\n2026-05-08,110,210,320\n")
    _write(folder / "result.csv",
           "WEEK_ENDING,UC,CD,TOTAL\n2026-05-01,100,200,300\n"
           "2026-05-08,115,210,325\n2026-05-15,120,220,340\n")
    with _client(repo_copy) as c:
        d = c.get("/api/views/tremfya_ibd_split/diff").json()
        assert d["available"] is True
        assert d["new_rows"] == ["2026-05-15"]
        assert d["compared_at"] == "2026-05-08"
        assert d["latest_deltas"]["UC"] == {"prev": 110.0, "curr": 115.0, "delta": 5.0}
        assert "CD" not in d["latest_deltas"]        # unchanged → omitted


def test_diff_unavailable_without_prev(repo_copy):
    with _client(repo_copy) as c:
        assert c.get("/api/views/tremfya_ibd_split/diff").json()["available"] is False


def test_history_endpoint(repo_copy):
    folder = repo_copy / "output" / "tremfya_ibd_split"
    _write(folder / "run_history.json",
           json.dumps([{"last_run_at": "2026-06-01T00:00:00", "ok": True}]))
    with _client(repo_copy) as c:
        h = c.get("/api/views/tremfya_ibd_split/history").json()
        assert h[0]["ok"] is True


def test_result_spec_fallback_without_deck_spec(repo_copy):
    # Folder setup must happen INSIDE the client block: _client runs
    # seed_views.py, which re-copies deck_spec.json into the view folder —
    # unlinking before the client would be silently undone.
    folder = repo_copy / "output" / "tremfya_ibd_split"
    with _client(repo_copy) as c:
        _write(folder / "result.csv",
               "WEEK_ENDING,UC,CD,TOTAL\n2026-05-01,100,200,300\n")
        (folder / "deck_spec.json").unlink(missing_ok=True)
        r = c.get("/api/views/tremfya_ibd_split/result").json()
        assert r["spec"]["inferred"] is True
        assert r["spec"]["date_column"] == "WEEK_ENDING"
        assert r["spec"]["series_columns"] == ["UC", "CD"]
        assert r["spec"]["total_column"] == "TOTAL"


def test_diff_and_history_on_placeholder_view_no_500(repo_copy):
    with _client(repo_copy) as c:
        assert c.get("/api/views/humira_ibd_split/diff").json()["available"] is False
        assert c.get("/api/views/humira_ibd_split/history").json() == []

# tests/test_pipeline.py
import os, subprocess, sys, time
from pathlib import Path

import pytest
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


def _wait_job(c, jid, timeout=300):
    for _ in range(timeout * 2):
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "failed"):
            return j
        time.sleep(0.5)
    raise AssertionError("job timed out")


def _seed_meta(repo_copy, vid):
    """Seeded view folders have no run_meta.json (the seeder copies code, not
    run state) — and never-run views are NOT stale by design. Seed a current
    meta so a subsequent simulate makes the view genuinely stale."""
    import json
    from server import views, datasets
    v = views.view_by_id(vid)
    folder = repo_copy / v["folder"]
    folder.mkdir(parents=True, exist_ok=True)
    cur = {t["name"]: t["max_date"] for t in datasets.all_tables()}
    (folder / "run_meta.json").write_text(json.dumps({
        "last_run_at": "2026-06-01T00:00:00",
        "data_max_at_run": {n: cur[n] for n in views.declared_tables(v)},
        "validation_status": "pass", "row_count": 1, "deck_available": False,
    }), encoding="utf-8")


def test_pipeline_check_mode(repo_copy):
    with _client(repo_copy) as c:
        r = c.post("/api/pipeline/run", json={"mode": "check"}).json()
        assert set(r) >= {"schema", "tables", "changed_tables", "stale_views"}


def test_pipeline_data_mode_acknowledges(repo_copy):
    with _client(repo_copy) as c:
        c.post("/api/data/simulate")
        r = c.post("/api/pipeline/run", json={"mode": "data"}).json()
        assert r["acknowledged"] is True
        assert "Weekly_Data_Tabular" in r["changed_tables"]
        again = c.post("/api/pipeline/run", json={"mode": "check"}).json()
        assert again["changed_tables"] == []


def test_pipeline_bad_mode_400(repo_copy):
    with _client(repo_copy) as c:
        assert c.post("/api/pipeline/run", json={"mode": "nope"}).status_code == 400


def test_jobs_404(repo_copy):
    with _client(repo_copy) as c:
        assert c.get("/api/jobs/nope").status_code == 404


@pytest.mark.slow
def test_pipeline_full_runs_stale_views_and_acknowledges(repo_copy):
    with _client(repo_copy) as c:
        _seed_meta(repo_copy, "tremfya_ibd_split")   # make staleness possible
        c.post("/api/data/simulate")                 # …and now real
        r = c.post("/api/pipeline/run", json={"mode": "full"}).json()
        job = _wait_job(c, r["job_id"])
        assert job["status"] == "done"
        assert job["summary"]["views_run"] >= 1
        check = c.post("/api/pipeline/run", json={"mode": "check"}).json()
        assert check["changed_tables"] == []
        assert check["stale_views"] == []


@pytest.mark.slow
def test_batch_run_selected(repo_copy):
    with _client(repo_copy) as c:
        r = c.post("/api/views/run", json={"views": ["tremfya_ibd_split"]}).json()
        job = _wait_job(c, r["job_id"])
        assert job["status"] == "done"
        assert job["summary"]["results"][0]["ok"] is True

import subprocess, sys, os
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
    # Build a FRESH app per fixture so its StaticFiles mount (which captures
    # config.web_dir() at construction) is bound to THIS test's QTS_ROOT. Importing
    # the cached module-level `app` would leak the first test's temp copy into later ones.
    from server.app import create_app
    return TestClient(create_app())   # `with` triggers lifespan (snapshot init)

def test_tables_endpoint(repo_copy):
    with _client(repo_copy) as c:
        tables = c.get("/api/tables").json()
        names = {t["name"] for t in tables}
        assert {"Weekly_Data_Tabular", "Monthly_Data_Tabular"} <= names
        weekly = next(t for t in tables if t["name"] == "Weekly_Data_Tabular")
        assert weekly["updated"] is False  # snapshot was just initialized

def test_simulate_then_tables_flag_updated(repo_copy):
    with _client(repo_copy) as c:
        assert c.post("/api/data/simulate").status_code == 200
        check = c.post("/api/data/refresh-check").json()
        assert "Weekly_Data_Tabular" in check["changed_tables"]

@pytest.mark.slow
def test_run_then_result(repo_copy):
    with _client(repo_copy) as c:
        run = c.post("/api/views/tremfya_ibd_split/run").json()
        assert run["ok"] is True
        result = c.get("/api/views/tremfya_ibd_split/result").json()
        assert result["spec"]["series_columns"] == ["UC", "CD"]
        assert len(result["rows"]) > 0

def test_reset_without_backup_returns_400(repo_copy):
    with _client(repo_copy) as c:
        assert c.post("/api/data/reset").status_code == 400

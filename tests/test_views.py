import subprocess, sys, os
from pathlib import Path

from server import views

REPO = Path(__file__).resolve().parents[1]

def _seed(repo_copy):
    vy = repo_copy / "views.yaml"
    if not vy.exists():
        vy.write_text((REPO / "views.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    subprocess.run([sys.executable, str(REPO / "scripts" / "seed_views.py")],
                   env={**os.environ, "QTS_ROOT": str(repo_copy)}, check=True)

def test_registry_lists_built_and_placeholders(repo_copy):
    _seed(repo_copy)
    statuses = {v["id"]: v for v in views.all_view_status()}
    assert statuses["tremfya_ibd_split"]["status"] == "built"
    assert statuses["payer_mix"]["status"] == "placeholder"
    assert statuses["payer_mix"]["tag"] == "data-gap"

def test_run_view_produces_result_and_meta(repo_copy):
    _seed(repo_copy)
    res = views.run_view("tremfya_ibd_split")
    assert res["ok"] is True
    assert res["validation"] == "pass"
    folder = repo_copy / "output" / "tremfya_ibd_split"
    assert (folder / "result.csv").exists()
    meta = views.read_run_meta({"folder": "output/tremfya_ibd_split", "status": "built"})
    assert meta["data_max_at_run"] == "2026-05-08"
    assert meta["row_count"] > 0

def test_view_becomes_stale_after_simulate(repo_copy):
    from server import simulate
    _seed(repo_copy)
    views.run_view("tremfya_ibd_split")
    simulate.simulate()  # advances weekly max beyond data_max_at_run
    st = {v["id"]: v for v in views.all_view_status()}
    assert st["tremfya_ibd_split"]["stale"] is True

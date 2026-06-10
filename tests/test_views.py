import subprocess, sys, os
from pathlib import Path

import pytest
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

@pytest.mark.slow
def test_run_view_produces_result_and_meta(repo_copy):
    _seed(repo_copy)
    res = views.run_view("tremfya_ibd_split")
    assert res["ok"] is True
    assert res["validation"] == "pass"
    folder = repo_copy / "output" / "tremfya_ibd_split"
    assert (folder / "result.csv").exists()
    meta = views.read_run_meta({"folder": "output/tremfya_ibd_split", "status": "built"})
    from server import datasets
    cur = {t["name"]: t["max_date"] for t in datasets.all_tables()}
    assert meta["data_max_at_run"]["Weekly_Data_Tabular"] == cur["Weekly_Data_Tabular"]
    assert "Monthly_Data_Tabular" in meta["data_max_at_run"]
    assert meta["row_count"] > 0

@pytest.mark.slow
def test_view_becomes_stale_after_simulate(repo_copy):
    from server import simulate
    _seed(repo_copy)
    views.run_view("tremfya_ibd_split")
    simulate.simulate()  # advances weekly max beyond data_max_at_run
    st = {v["id"]: v for v in views.all_view_status()}
    assert st["tremfya_ibd_split"]["stale"] is True


def test_parse_validation_extracts_checks():
    from server import views
    out = (
        "============\nRESULT VALIDATION — x\n============\n"
        "Rows: 106 | Columns: ['WEEK_ENDING', 'UC', 'CD']\n"
        "  [WARN]  106 rows exceeds slide-size default (15).\n"
        "\nRESULT: PASS with warnings.\n"
    )
    d = views.parse_validation(out, 2)
    assert d["verdict"] == "warnings"
    assert d["rows"] == 106
    assert d["checks"] == [{"level": "warn",
                            "message": "106 rows exceeds slide-size default (15)."}]
    assert "null audit on metric columns" in d["ran"]


def test_append_history_caps_at_50(tmp_path):
    from server import views
    for i in range(55):
        views._append_history(tmp_path, {"last_run_at": str(i)}, ok=True)
    import json
    hist = json.loads((tmp_path / "run_history.json").read_text(encoding="utf-8"))
    assert len(hist) == 50
    assert hist[-1]["last_run_at"] == "54"


def test_append_history_strips_validation_detail(tmp_path):
    import json
    from server import views
    views._append_history(tmp_path, {"last_run_at": "x",
                                     "validation_detail": {"big": "blob"}}, ok=True)
    hist = json.loads((tmp_path / "run_history.json").read_text(encoding="utf-8"))
    assert "validation_detail" not in hist[0]


def _seed_meta(repo_copy, vid, data_max):
    import json
    from server import views
    v = views.view_by_id(vid)
    folder = repo_copy / v["folder"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run_meta.json").write_text(json.dumps({
        "last_run_at": "2026-06-01T00:00:00", "data_max_at_run": data_max,
        "validation_status": "pass", "row_count": 1, "deck_available": False,
    }), encoding="utf-8")


def test_stale_on_monthly_only_change(repo_copy):
    from server import datasets, views
    # weekly CURRENT (read live, not a literal — survives data changes),
    # monthly behind → STALE even though weekly didn't move
    cur = {t["name"]: t["max_date"] for t in datasets.all_tables()}
    cur["Monthly_Data_Tabular"] = "2020-01-01"
    _seed_meta(repo_copy, "tremfya_ibd_split", cur)
    s = next(x for x in views.all_view_status() if x["id"] == "tremfya_ibd_split")
    assert s["stale"] is True


def test_not_stale_when_all_tables_current(repo_copy):
    from server import views, datasets
    cur = {t["name"]: t["max_date"] for t in datasets.all_tables()}
    _seed_meta(repo_copy, "tremfya_ibd_split", cur)
    s = next(x for x in views.all_view_status() if x["id"] == "tremfya_ibd_split")
    assert s["stale"] is False


def test_backward_compat_string_data_max(repo_copy):
    from server import views
    _seed_meta(repo_copy, "tremfya_ibd_split", "2020-01-01")  # old string format
    s = next(x for x in views.all_view_status() if x["id"] == "tremfya_ibd_split")
    assert s["stale"] is True   # weekly has moved past 2020

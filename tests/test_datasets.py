from server import datasets

def test_weekly_table_info_against_real_data(repo_copy):
    # repo_copy points QTS_ROOT at a temp copy, so this never reads the mutable
    # real /data (simulate.py appends to it when QTS_ROOT is unset).
    info = {t["name"]: t for t in datasets.all_tables()}
    w = info["Weekly_Data_Tabular"]
    assert w["grain"] == "one row per product per week"
    assert w["date_column"] == "WEEK_ENDING"
    assert w["min_date"] == "2024-05-03"
    assert w["max_date"] == "2026-05-08"
    assert w["row_count"] > 0

def test_monthly_min_max(repo_copy):
    info = {t["name"]: t for t in datasets.all_tables()}
    m = info["Monthly_Data_Tabular"]
    assert m["date_column"] == "MONTH_DATE"
    assert m["min_date"] == "2020-05-01"
    assert m["max_date"] == "2026-04-01"

def test_table_info_quality_fields(repo_copy):
    from server import datasets
    t = datasets.table_info("Weekly_Data_Tabular")
    assert t["metric_nulls"] >= 0
    assert t["periods"] > 100        # ~106 weeks

from server import simulate, datasets, config

def _maxes():
    return {t["name"]: t["max_date"] for t in datasets.all_tables()}

def test_simulate_advances_both_maxes(repo_copy):
    before = _maxes()
    simulate.simulate()
    after = _maxes()
    assert after["Weekly_Data_Tabular"] > before["Weekly_Data_Tabular"]
    assert after["Monthly_Data_Tabular"] > before["Monthly_Data_Tabular"]

def test_reset_restores_byte_identical(repo_copy):
    weekly = config.data_dir() / "Weekly_Data_Tabular.csv"
    monthly = config.data_dir() / "Monthly_Data_Tabular.csv"
    orig_w, orig_m = weekly.read_bytes(), monthly.read_bytes()
    simulate.simulate()
    assert weekly.read_bytes() != orig_w  # changed
    assert simulate.reset() is True
    assert weekly.read_bytes() == orig_w  # byte-identical restore
    assert monthly.read_bytes() == orig_m

def test_reset_without_backup_is_noop(repo_copy):
    assert simulate.reset() is False

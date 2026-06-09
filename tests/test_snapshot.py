from server import snapshot

def test_fresh_snapshot_reports_no_change(repo_copy):
    snapshot.init_if_missing()
    cmp = snapshot.compare()
    assert all(v["changed"] is False for v in cmp.values())

def test_snapshot_detects_a_changed_max(repo_copy):
    snapshot.init_if_missing()
    # hand-edit the snapshot to an older weekly max
    snap = snapshot.read_snapshot()
    snap["Weekly_Data_Tabular"]["max"] = "2026-04-10"
    snapshot.write_snapshot(snap)
    cmp = snapshot.compare()
    assert cmp["Weekly_Data_Tabular"]["changed"] is True
    assert cmp["Weekly_Data_Tabular"]["current_max"] == "2026-05-08"

def test_acknowledge_clears_change(repo_copy):
    snapshot.init_if_missing()
    snap = snapshot.read_snapshot()
    snap["Weekly_Data_Tabular"]["max"] = "2026-04-10"
    snapshot.write_snapshot(snap)
    snapshot.acknowledge()
    assert all(v["changed"] is False for v in snapshot.compare().values())

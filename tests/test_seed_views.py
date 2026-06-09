import subprocess, sys
from pathlib import Path

from server import runner

REPO = Path(__file__).resolve().parents[1]

def test_seed_creates_normalized_folders(repo_copy):
    # views.yaml must exist in the copy for downstream tasks; copy it in if absent
    vy = repo_copy / "views.yaml"
    if not vy.exists():
        vy.write_text((REPO / "views.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    rc = subprocess.run([sys.executable, str(REPO / "scripts" / "seed_views.py")],
                        env={**__import__("os").environ, "QTS_ROOT": str(repo_copy)},
                        capture_output=True, text=True).returncode
    assert rc == 0
    for vid in ("tremfya_ibd_split", "skyrizi_ibd_split"):
        folder = repo_copy / "output" / vid
        assert (folder / "analysis_code.py").exists()
        assert (folder / "deck_spec.json").exists()
        plan = (folder / "analysis_plan.md").read_text(encoding="utf-8")
        assert "full grain" in plan.lower()
        assert "expected_row_count: 106" not in plan

def test_validate_result_exit_codes_end_to_end(tmp_path):
    """Drive the REAL scripts/validate_result.py — not just validation_ok on bare
    ints — to prove the seed normalization + exit-code contract: a >15-row plan
    with no 'full grain' warns (exit 2 = pass); a normalized full-grain plan passes
    (exit 0/2); an un-normalized pinned count that mismatches fails (exit 1)."""
    import scripts.seed_views as seed
    vr = str(REPO / "scripts" / "validate_result.py")

    def _folder(name, rows, plan_text):
        f = tmp_path / name
        f.mkdir()
        body = "WEEK_ENDING,TRX\n" + "".join(f"2026-01-{i + 1:02d},{i}\n" for i in range(rows))
        (f / "result.csv").write_text(body, encoding="utf-8")
        (f / "analysis_plan.md").write_text(plan_text, encoding="utf-8")
        return f

    # >15 rows, no 'full grain', no pinned count -> warning -> exit 2 (treated as pass)
    warn = _folder("warn", 20, "analysis of weekly trx\n")
    assert runner.run_script([vr, str(warn)])[0] == 2
    assert runner.validation_ok(2) is True

    # normalized full-grain plan -> pass (exit 0 or 2)
    fg = _folder("fg", 20, seed.normalize_plan("expected_row_count: 106\n"))
    assert "full grain" in (fg / "analysis_plan.md").read_text().lower()
    assert runner.validation_ok(runner.run_script([vr, str(fg)])[0]) is True

    # un-normalized pinned count that mismatches the row count -> exit 1 (fail)
    pinned = _folder("pinned", 3, "expected_row_count: 106\n")
    rc = runner.run_script([vr, str(pinned)])[0]
    assert rc == 1
    assert runner.validation_ok(rc) is False

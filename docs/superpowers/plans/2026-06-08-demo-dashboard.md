# Demo Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local FastAPI + vanilla-JS dashboard that lists the project's datasets and already-built analyses ("views"), detects when `/data` has advanced, and re-runs any selected view against current data — regenerating its result table, an in-browser chart, and its single-slide deck.

**Architecture:** A FastAPI backend (the only component that touches the filesystem or runs Python) exposes JSON endpoints and serves one static branded page. Backend logic is split into small single-responsibility modules under `server/`, each independently testable by pointing the `QTS_ROOT` env var at a temp copy of the repo. The dashboard re-executes the existing committed `analysis_code.py` / `validate_result.py` / `build_deck_pptx.py` scripts via subprocess — it never re-derives analysis logic and never calls an LLM.

**Tech Stack:** Python 3.14 (`py -3`), FastAPI + uvicorn, pandas, PyYAML, python-pptx (all run via subprocess), pytest + FastAPI TestClient (httpx). Frontend: vanilla HTML/CSS/JS, hand-rolled SVG chart, no build step.

---

## Conventions for this plan

- **Git is intentionally NOT initialized** in this project (per `MEMORY.md`). Every "Checkpoint" step below replaces the usual git commit — **do not run any `git` command.** A checkpoint = "all tests in this task pass; move on."
- Always invoke Python as **`py -3`** in PowerShell (the `py` launcher is not on the Bash PATH).
- All backend paths derive from `server/config.py:get_root()`, which reads the `QTS_ROOT` env var (default = repo root). Tests set `QTS_ROOT` to a temp copy so they never mutate real data.
- Reference spec: `docs/superpowers/specs/2026-06-08-demo-dashboard-design.md`.

## File structure

```
run_dashboard.py            # launcher: uvicorn on 127.0.0.1:8000
server/
  __init__.py
  config.py                 # QTS_ROOT-based path helpers
  datasets.py               # tables + dictionaries -> min/max/grain/rowcount
  snapshot.py               # data/.snapshot.json read/compare/acknowledge
  simulate.py               # clone-last-period append + backup/reset
  runner.py                 # subprocess wrapper + in-flight lock + exit-code map
  views.py                  # views.yaml registry, run a view, staleness
  app.py                    # FastAPI routes + static mount
scripts/
  seed_views.py             # one-time: build canonical output/<view_id>/ folders
views.yaml                  # view registry (cards source of truth)
web/
  index.html
  styles.css
  app.js
tests/
  conftest.py               # repo_copy fixture
  test_datasets.py
  test_snapshot.py
  test_simulate.py
  test_runner.py
  test_seed_views.py
  test_views.py
  test_api.py
output/<view_id>/           # canonical per-view folders (created by seed_views.py)
data/_original/             # raw CSV backup (created on first simulate)
data/.snapshot.json         # last-acknowledged min/max
```

---

## Task 0: Install dependencies and scaffold the package

**Files:**
- Create: `server/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)

- [ ] **Step 1: Install FastAPI + uvicorn**

Run (PowerShell):
```
py -3 -m pip install fastapi uvicorn
```
Expected: installs `fastapi`, `uvicorn`, `starlette`. (`httpx`, `pandas`, `pyyaml`, `python-pptx`, `pytest` are already present.)

- [ ] **Step 2: Verify imports**

Run:
```
py -3 -c "import fastapi, uvicorn, starlette, httpx, pandas, yaml, pptx, pytest; print('all deps ok')"
```
Expected: `all deps ok`

- [ ] **Step 3: Create empty package markers**

Create `server/__init__.py` (empty file) and `tests/__init__.py` (empty file).

- [ ] **Step 4: Checkpoint** — deps import cleanly; package dirs exist.

---

## Task 1: `server/config.py` — path helpers

**Files:**
- Create: `server/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import os
from pathlib import Path
from server import config

def test_get_root_defaults_to_repo_root():
    # server/config.py -> parents[1] is the repo root
    assert (config.get_root() / "CLAUDE.md").exists()

def test_get_root_honors_env(monkeypatch, tmp_path):
    monkeypatch.setenv("QTS_ROOT", str(tmp_path))
    assert config.get_root() == tmp_path
    assert config.data_dir() == tmp_path / "data"
    assert config.views_file() == tmp_path / "views.yaml"
    assert config.snapshot_file() == tmp_path / "data" / ".snapshot.json"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.config'`

- [ ] **Step 3: Write the implementation**

```python
# server/config.py
"""Path helpers. Every path derives from QTS_ROOT (default = repo root) so tests
can redirect the whole app at a temp copy by setting one env var."""
import os
from pathlib import Path

_DEFAULT_ROOT = Path(__file__).resolve().parents[1]  # server/ -> repo root


def get_root() -> Path:
    return Path(os.environ.get("QTS_ROOT", str(_DEFAULT_ROOT)))


def data_dir() -> Path:
    return get_root() / "data"


def metadata_dir() -> Path:
    return get_root() / "metadata"


def output_dir() -> Path:
    return get_root() / "output"


def scripts_dir() -> Path:
    return get_root() / "scripts"


def web_dir() -> Path:
    return get_root() / "web"


def views_file() -> Path:
    return get_root() / "views.yaml"


def snapshot_file() -> Path:
    return data_dir() / ".snapshot.json"


def original_backup_dir() -> Path:
    return data_dir() / "_original"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Checkpoint.**

---

## Task 2: `server/datasets.py` — table metadata + live min/max

**Files:**
- Create: `server/datasets.py`
- Test: `tests/test_datasets.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_datasets.py
from server import datasets

def test_weekly_table_info_against_real_data():
    info = {t["name"]: t for t in datasets.all_tables()}
    w = info["Weekly_Data_Tabular"]
    assert w["grain"] == "one row per product per week"
    assert w["date_column"] == "WEEK_ENDING"
    assert w["min_date"] == "2024-05-03"
    assert w["max_date"] == "2026-05-08"
    assert w["row_count"] > 0

def test_monthly_min_max():
    info = {t["name"]: t for t in datasets.all_tables()}
    m = info["Monthly_Data_Tabular"]
    assert m["date_column"] == "MONTH_DATE"
    assert m["min_date"] == "2020-05-01"
    assert m["max_date"] == "2026-04-01"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_datasets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.datasets'`

- [ ] **Step 3: Write the implementation**

```python
# server/datasets.py
"""Read each table's data dictionary + CSV and report grain, date range, rows."""
import pandas as pd
import yaml

from . import config

DATE_TYPE = "date"


def _load_dict(name: str) -> dict:
    with open(config.metadata_dir() / f"{name}.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def date_column(d: dict):
    for c in d.get("columns", []):
        if c.get("type") == DATE_TYPE:
            return c["name"]
    return None


def table_names() -> list:
    names = []
    for f in sorted(config.metadata_dir().glob("*.yaml")):
        if f.name == "relationships.yaml" or f.name.startswith("_"):
            continue
        names.append(f.stem)
    return names


def table_info(name: str) -> dict:
    d = _load_dict(name)
    df = pd.read_csv(config.data_dir() / f"{name}.csv")
    dcol = date_column(d)
    dates = pd.to_datetime(df[dcol], errors="coerce") if dcol else None
    return {
        "name": d.get("table", name),
        "description": d.get("description", ""),
        "grain": d.get("grain", ""),
        "refresh": d.get("refresh", ""),
        "date_column": dcol,
        "min_date": dates.min().strftime("%Y-%m-%d") if dcol else None,
        "max_date": dates.max().strftime("%Y-%m-%d") if dcol else None,
        "row_count": int(len(df)),
    }


def all_tables() -> list:
    return [table_info(n) for n in table_names()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_datasets.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Checkpoint.**

---

## Task 3: `server/snapshot.py` — data-change detection

**Files:**
- Create: `server/snapshot.py`
- Create: `tests/conftest.py`
- Test: `tests/test_snapshot.py`

- [ ] **Step 1: Write the shared fixture**

```python
# tests/conftest.py
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo_copy(tmp_path, monkeypatch):
    """A writable temp copy of the repo bits the dashboard touches.
    Sets QTS_ROOT so every server.config path resolves into the copy."""
    for d in ("data", "metadata", "scripts", "web"):
        src = REPO / d
        if src.exists():
            shutil.copytree(src, tmp_path / d)
    # copy the existing run folders the seeder reads from
    out = tmp_path / "output"
    out.mkdir(exist_ok=True)
    for run in ("run_2026-06-08_001", "run_2026-06-08_002"):
        src = REPO / "output" / run
        if src.exists():
            shutil.copytree(src, out / run)
    # copy views.yaml if it already exists in the repo
    if (REPO / "views.yaml").exists():
        shutil.copy2(REPO / "views.yaml", tmp_path / "views.yaml")
    monkeypatch.setenv("QTS_ROOT", str(tmp_path))
    return tmp_path
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_snapshot.py
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_snapshot.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.snapshot'`

- [ ] **Step 4: Write the implementation**

```python
# server/snapshot.py
"""Compare each table's live min/max against the last acknowledged snapshot."""
import json

from . import config, datasets


def current_minmax() -> dict:
    return {t["name"]: {"min": t["min_date"], "max": t["max_date"]}
            for t in datasets.all_tables()}


def read_snapshot() -> dict:
    p = config.snapshot_file()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def write_snapshot(data: dict) -> None:
    config.snapshot_file().write_text(json.dumps(data, indent=2), encoding="utf-8")


def init_if_missing() -> dict:
    if not config.snapshot_file().exists():
        snap = current_minmax()
        write_snapshot(snap)
        return snap
    return read_snapshot()


def compare() -> dict:
    snap = read_snapshot()
    out = {}
    for name, mm in current_minmax().items():
        prev = snap.get(name, {})
        out[name] = {
            "snapshot_max": prev.get("max"),
            "current_max": mm["max"],
            "changed": prev.get("max") != mm["max"],
        }
    return out


def acknowledge() -> dict:
    snap = current_minmax()
    write_snapshot(snap)
    return snap
```

- [ ] **Step 5: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_snapshot.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Checkpoint.**

---

## Task 4: `server/simulate.py` — clone-last-period + reset

**Files:**
- Create: `server/simulate.py`
- Test: `tests/test_simulate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_simulate.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_simulate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.simulate'`

- [ ] **Step 3: Write the implementation**

```python
# server/simulate.py
"""Demo helper: append a cloned 'next period' to both CSVs (reversible).

Cloning the latest period's rows preserves MARKET_TOTAL rows, NON_APPROVED
flags and every product/indication automatically — no per-row synthesis.
The untouched originals are backed up on first use so reset() restores them
byte-for-byte."""
import shutil

import pandas as pd

from . import config

WEEKLY = "Weekly_Data_Tabular"
MONTHLY = "Monthly_Data_Tabular"
GROWTH = 1.02  # per-period multiplier on the cloned numeric column


def _csv(name):
    return config.data_dir() / f"{name}.csv"


def ensure_backup() -> None:
    bdir = config.original_backup_dir()
    bdir.mkdir(exist_ok=True)
    for name in (WEEKLY, MONTHLY):
        dst = bdir / f"{name}.csv"
        if not dst.exists():
            shutil.copy2(_csv(name), dst)


def has_backup() -> bool:
    bdir = config.original_backup_dir()
    return all((bdir / f"{n}.csv").exists() for n in (WEEKLY, MONTHLY))


def _append(name, date_col, value_col, new_dates):
    df = pd.read_csv(_csv(name))
    dts = pd.to_datetime(df[date_col])
    latest = df[dts == dts.max()].copy()
    frames = [df]
    for k, new_dt in enumerate(new_dates(dts.max()), start=1):
        blk = latest.copy()
        blk[date_col] = new_dt.strftime("%Y-%m-%d")
        blk[value_col] = (pd.to_numeric(blk[value_col], errors="coerce")
                          * (GROWTH ** k)).round(6)
        frames.append(blk)
    pd.concat(frames, ignore_index=True).to_csv(_csv(name), index=False)


def simulate() -> dict:
    ensure_backup()
    _append(WEEKLY, "WEEK_ENDING", "TRX_ADJUSTED",
            lambda m: [m + pd.Timedelta(days=7 * k) for k in range(1, 5)])
    _append(MONTHLY, "MONTH_DATE", "TRX_VOLUME",
            lambda m: [m + pd.offsets.MonthBegin(1)])
    from . import datasets
    return {t["name"]: {"min": t["min_date"], "max": t["max_date"]}
            for t in datasets.all_tables()}


def reset() -> bool:
    if not has_backup():
        return False
    bdir = config.original_backup_dir()
    for name in (WEEKLY, MONTHLY):
        shutil.copy2(bdir / f"{name}.csv", _csv(name))
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_simulate.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Checkpoint.**

---

## Task 5: `server/runner.py` — subprocess wrapper + lock + exit-code map

**Files:**
- Create: `server/runner.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_runner.py
import pytest
from server import runner

def test_run_script_captures_output():
    rc, out, err = runner.run_script(["-c", "print('hi')"])
    assert rc == 0
    assert out.strip() == "hi"

def test_validation_ok_treats_2_as_pass():
    assert runner.validation_ok(0) is True
    assert runner.validation_ok(2) is True   # warnings = pass
    assert runner.validation_ok(1) is False  # only 1 fails

def test_lock_rejects_reentry():
    with runner.run_lock():
        with pytest.raises(runner.Busy):
            with runner.run_lock():
                pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.runner'`

- [ ] **Step 3: Write the implementation**

```python
# server/runner.py
"""Run the project's existing scripts via subprocess, with a single in-flight
lock and the validate_result exit-code convention (0/2 = pass, 1 = fail)."""
import subprocess
import sys
import threading


class Busy(Exception):
    """Raised when a run is already in progress."""


_LOCK = threading.Lock()


class run_lock:
    def __enter__(self):
        if not _LOCK.acquire(blocking=False):
            raise Busy("another run is in progress")
        return self

    def __exit__(self, *exc):
        _LOCK.release()
        return False


def run_script(args, cwd=None):
    """Run `<this python> <args...>`; return (returncode, stdout, stderr).
    sys.executable is the py -3 interpreter running the server, so spawned
    analysis_code.py / validate_result.py / build_deck_pptx.py see the same
    pandas/pptx install. analysis_code.py finds the project root via parents[2]
    of its own location, so cwd is irrelevant to it."""
    proc = subprocess.run([sys.executable, *args], cwd=cwd,
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def validation_ok(code: int) -> bool:
    return code in (0, 2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_runner.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Checkpoint.**

---

## Task 6: `scripts/seed_views.py` + `views.yaml` — canonical view folders

**Files:**
- Create: `scripts/seed_views.py`
- Create: `views.yaml`
- Test: `tests/test_seed_views.py`

- [ ] **Step 1: Create the view registry**

```yaml
# views.yaml
views:
  - id: tremfya_ibd_split
    title: "TREMFYA — IBD Indication Split"
    brand: TREMFYA
    description: "Weekly TRx split across UC / CD, full series."
    status: built
    kind: indication_split
    folder: output/tremfya_ibd_split

  - id: skyrizi_ibd_split
    title: "SKYRIZI (SQ+IV+OBI) — IBD Indication Split"
    brand: SKYRIZI
    description: "Combined Skyrizi weekly TRx split across UC / CD, full series."
    status: built
    kind: indication_split
    folder: output/skyrizi_ibd_split

  - id: humira_ibd_split
    title: "HUMIRA — IBD Indication Split"
    brand: HUMIRA
    description: "Same indication-split method, applied to Humira."
    status: placeholder
    tag: capability-ready

  - id: stelara_ibd_split
    title: "STELARA — IBD Indication Split"
    brand: STELARA
    description: "Same indication-split method, applied to Stelara."
    status: placeholder
    tag: capability-ready

  - id: tremfya_by_doseform
    title: "TREMFYA — by Dose / Form (SQ 100 / 200 / Induction)"
    brand: TREMFYA
    description: "Weekly TRx broken out by dosage presentation."
    status: placeholder
    tag: capability-ready

  - id: monthly_indication_trend
    title: "Monthly Indication Trend — all brands"
    description: "Monthly TRx by indication across the immunology markets."
    status: placeholder
    tag: capability-ready

  - id: payer_mix
    title: "Payer Mix"
    description: "Needs payer data not present in any current table."
    status: placeholder
    tag: data-gap
    note: "Honest boundary — no payer dimension exists in the data."
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_seed_views.py
import subprocess, sys
from pathlib import Path

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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_seed_views.py -v`
Expected: FAIL — `seed_views.py` does not exist (non-zero rc / FileNotFound)

- [ ] **Step 4: Write the implementation**

```python
# scripts/seed_views.py
"""One-time, idempotent: build canonical output/<view_id>/ folders from the best
existing runs, normalizing the analysis_plan so validation survives data growth.

Kept directly under output/ so analysis_code.py's parents[2] still resolves to
the project root. Honors QTS_ROOT (default = repo root)."""
import os
import re
from pathlib import Path

ROOT = Path(os.environ.get("QTS_ROOT", str(Path(__file__).resolve().parents[1])))

SEEDS = {
    "tremfya_ibd_split": "run_2026-06-08_001",
    "skyrizi_ibd_split": "run_2026-06-08_002",
}
COPY = ["analysis_code.py", "analysis_plan.md", "deck_spec.json",
        "context.md", "takeaways.md", "query.txt"]


def normalize_plan(text: str) -> str:
    """Drop the pinned numeric row count and mark the series full-grain, so
    validate_result.py passes as weeks accrue."""
    return re.sub(
        r"expected_row_count:.*",
        "expected_row_count: full grain — one row per WEEK_ENDING (grows with data)",
        text,
    )


def main():
    out = ROOT / "output"
    for vid, src in SEEDS.items():
        s, d = out / src, out / vid
        d.mkdir(parents=True, exist_ok=True)
        for f in COPY:
            sp = s / f
            if not sp.exists():
                continue
            text = sp.read_text(encoding="utf-8")
            if f == "analysis_plan.md":
                text = normalize_plan(text)
            (d / f).write_text(text, encoding="utf-8")
        print(f"seeded {vid} from {src}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_seed_views.py -v`
Expected: PASS (1 passed)

- [ ] **Step 6: Seed the real repo** (so the dashboard has live folders to run)

Run: `py -3 scripts/seed_views.py`
Expected: prints `seeded tremfya_ibd_split from run_2026-06-08_001` and the SKYRIZI line; folders `output/tremfya_ibd_split/` and `output/skyrizi_ibd_split/` now exist.

- [ ] **Step 7: Checkpoint.**

---

## Task 7: `server/views.py` — registry, run, staleness

**Files:**
- Create: `server/views.py`
- Test: `tests/test_views.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_views.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_views.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.views'`

- [ ] **Step 3: Write the implementation**

```python
# server/views.py
"""View registry + deterministic re-run of a built view's committed scripts."""
import json
from datetime import datetime

import pandas as pd
import yaml

from . import config, datasets, runner


def load_registry() -> list:
    data = yaml.safe_load(config.views_file().read_text(encoding="utf-8")) or {}
    return data.get("views", [])


def view_by_id(vid: str):
    for v in load_registry():
        if v["id"] == vid:
            return v
    return None


def _folder(v):
    return config.get_root() / v["folder"]


def _weekly_max():
    for t in datasets.all_tables():
        if t["name"] == "Weekly_Data_Tabular":
            return t["max_date"]
    return None


def read_run_meta(v) -> dict:
    p = _folder(v) / "run_meta.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def view_status(v) -> dict:
    base = {"id": v["id"], "title": v["title"], "status": v["status"],
            "tag": v.get("tag"), "brand": v.get("brand"),
            "description": v.get("description", ""), "note": v.get("note")}
    if v["status"] != "built":
        return base
    meta = read_run_meta(v)
    wk = _weekly_max()
    base.update({
        "last_run_at": meta.get("last_run_at"),
        "validation": meta.get("validation_status"),
        "row_count": meta.get("row_count"),
        "deck_available": meta.get("deck_available", False),
        "data_max_at_run": meta.get("data_max_at_run"),
        "never_run": not bool(meta),
        "stale": bool(meta and meta.get("data_max_at_run") and wk
                      and wk > meta["data_max_at_run"]),
    })
    return base


def all_view_status() -> list:
    return [view_status(v) for v in load_registry()]


def _finish(v, folder, ok, validation, deck, log):
    rp = folder / "result.csv"
    rows = int(len(pd.read_csv(rp))) if rp.exists() else None
    meta = {
        "last_run_at": datetime.now().isoformat(timespec="seconds"),
        "data_max_at_run": _weekly_max(),
        "validation_status": validation,
        "row_count": rows,
        "deck_available": deck,
    }
    (folder / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"id": v["id"], "ok": ok, "validation": validation,
            "deck_available": deck, "row_count": rows, "log": "\n".join(log)}


def run_view(vid: str) -> dict:
    """① analysis_code.py → result.csv  ② validate_result.py (0/2 ok)
    ③ build_deck_pptx.py (only for indication_split). Writes run_meta.json."""
    v = view_by_id(vid)
    if v is None or v.get("status") != "built":
        return {"id": vid, "ok": False, "log": "not a runnable built view"}
    folder = _folder(v)
    log = []
    with runner.run_lock():
        rc, out, err = runner.run_script([str(folder / "analysis_code.py")])
        log.append(f"$ analysis_code.py -> {rc}\n{out}{err}".rstrip())
        if rc != 0:
            return _finish(v, folder, ok=False, validation=None, deck=False, log=log)

        vrc, vo, ve = runner.run_script(
            [str(config.scripts_dir() / "validate_result.py"), str(folder)])
        log.append(f"$ validate_result.py -> {vrc}\n{vo}{ve}".rstrip())
        validation = "pass" if runner.validation_ok(vrc) else "fail"
        if validation == "fail":
            return _finish(v, folder, ok=False, validation=validation, deck=False, log=log)

        deck_ok = False
        if v.get("kind") == "indication_split":
            drc, do, de = runner.run_script(
                [str(config.scripts_dir() / "build_deck_pptx.py"), str(folder)])
            log.append(f"$ build_deck_pptx.py -> {drc}\n{do}{de}".rstrip())
            deck_ok = drc == 0
        return _finish(v, folder, ok=True, validation=validation, deck=deck_ok, log=log)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_views.py -v`
Expected: PASS (3 passed). (These spawn the real analysis + deck build, so they take a few seconds each.)

- [ ] **Step 5: Checkpoint.**

---

## Task 8: `server/app.py` — FastAPI routes

**Files:**
- Create: `server/app.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api.py
import subprocess, sys, os
from pathlib import Path

from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]

def _client(repo_copy):
    vy = repo_copy / "views.yaml"
    if not vy.exists():
        vy.write_text((REPO / "views.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    subprocess.run([sys.executable, str(REPO / "scripts" / "seed_views.py")],
                   env={**os.environ, "QTS_ROOT": str(repo_copy)}, check=True)
    from server.app import app
    return TestClient(app)   # `with` triggers lifespan (snapshot init)

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.app'`

- [ ] **Step 3: Write the implementation**

```python
# server/app.py
"""FastAPI surface. Declares /api routes, then mounts the static web/ page at /."""
import csv
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, datasets, runner, simulate, snapshot, views


@asynccontextmanager
async def lifespan(app: FastAPI):
    snapshot.init_if_missing()
    yield


app = FastAPI(title="Query-to-Slide Dashboard", lifespan=lifespan)


@app.get("/api/tables")
def api_tables():
    tables = datasets.all_tables()
    cmp = snapshot.compare()
    for t in tables:
        t["updated"] = cmp.get(t["name"], {}).get("changed", False)
    return tables


@app.get("/api/views")
def api_views():
    return views.all_view_status()


@app.post("/api/data/refresh-check")
def api_refresh_check():
    rc, out, err = runner.run_script(
        [str(config.scripts_dir() / "validate_schema.py"), "--root", str(config.get_root())])
    schema = {0: "clear", 1: "drift", 2: "warnings"}.get(rc, "unknown")
    cmp = snapshot.compare()
    stale = [s["id"] for s in views.all_view_status() if s.get("stale")]
    return {"schema": schema, "schema_log": (out + err).strip(), "tables": cmp,
            "changed_tables": [k for k, v in cmp.items() if v["changed"]],
            "stale_views": stale}


@app.post("/api/data/acknowledge")
def api_acknowledge():
    return snapshot.acknowledge()


@app.post("/api/data/simulate")
def api_simulate():
    try:
        with runner.run_lock():
            return simulate.simulate()
    except runner.Busy:
        raise HTTPException(409, "busy")


@app.post("/api/data/reset")
def api_reset():
    try:
        with runner.run_lock():
            ok = simulate.reset()
    except runner.Busy:
        raise HTTPException(409, "busy")
    if not ok:
        raise HTTPException(400, "no backup to reset from")
    return {"reset": True}


@app.post("/api/views/{vid}/run")
def api_run(vid: str):
    try:
        return views.run_view(vid)
    except runner.Busy:
        raise HTTPException(409, "busy")


@app.get("/api/views/{vid}/result")
def api_result(vid: str):
    v = views.view_by_id(vid)
    if not v or v.get("status") != "built":
        raise HTTPException(404, "no such built view")
    folder = config.get_root() / v["folder"]
    rp = folder / "result.csv"
    if not rp.exists():
        raise HTTPException(404, "not run yet")
    with open(rp, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    spec = json.loads((folder / "deck_spec.json").read_text(encoding="utf-8"))
    tk = folder / "takeaways.md"
    return {"rows": rows, "spec": spec,
            "takeaways": tk.read_text(encoding="utf-8") if tk.exists() else ""}


@app.get("/api/views/{vid}/deck")
def api_deck(vid: str):
    v = views.view_by_id(vid)
    if not v:
        raise HTTPException(404, "no such view")
    deck = config.get_root() / v["folder"] / "deck.pptx"
    if not deck.exists():
        raise HTTPException(404, "no deck")
    return FileResponse(deck, filename=f"{vid}.pptx")


# Static page LAST so explicit /api routes win.
app.mount("/", StaticFiles(directory=str(config.web_dir()), html=True), name="web")
```

> Note: the `StaticFiles` mount requires `web/` to exist. Task 9 creates it. If you run `test_api.py` before Task 9, create an empty `web/` dir first (`mkdir web`), or run Task 9 first — the API tests don't depend on the page contents.

- [ ] **Step 4: Ensure `web/` exists, then run tests**

Run: `py -3 -c "import os; os.makedirs('web', exist_ok=True)"` then `py -3 -m pytest tests/test_api.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Checkpoint.**

---

## Task 9: `web/` — branded single page

**Files:**
- Create: `web/index.html`
- Create: `web/styles.css`
- Create: `web/app.js`

This task is verified by manual QA (Step 4), not pytest.

- [ ] **Step 1: Write `web/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Query-to-Slide · Control Panel</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@500;600;700&family=Roboto:wght@400;500&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/styles.css" />
</head>
<body>
  <header class="topbar">
    <div class="brand"><span class="mark">▶</span> DataZymes <span class="sep">·</span> Query-to-Slide</div>
    <div id="freshness" class="freshness"></div>
  </header>

  <main>
    <section>
      <h2>Datasets</h2>
      <div id="tables" class="grid"></div>
    </section>

    <section>
      <div class="controls">
        <button id="btn-refresh" class="btn primary">Data Refresh</button>
        <button id="btn-simulate" class="btn">Simulate new month</button>
        <button id="btn-reset" class="btn ghost">Reset demo data</button>
      </div>
      <div id="banner" class="banner hidden"></div>
    </section>

    <section>
      <div class="views-head">
        <h2>Views</h2>
        <div class="views-actions">
          <label class="selall"><input type="checkbox" id="select-all" /> Select all</label>
          <button id="btn-run" class="btn primary">Run selected</button>
        </div>
      </div>
      <div id="views" class="grid"></div>
    </section>

    <section id="result-section" class="hidden">
      <h2 id="result-title">Result</h2>
      <div class="result-wrap">
        <div id="chart"></div>
        <div id="takeaways" class="takeaways"></div>
      </div>
      <details><summary>Run log</summary><pre id="runlog"></pre></details>
      <div id="result-table"></div>
    </section>
  </main>

  <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `web/styles.css`**

```css
/* DataZymes brand tokens — must match build_deck_pptx.py */
:root{
  --navy:#071D49; --teal:#07B2AC; --magenta:#E40D62; --gray:#50535A;
  --pink:#FBE3EA; --bluefill:#ECF1F8; --rule:#D9DEE8; --bg:#F7F9FC; --white:#fff;
  --title:"Montserrat","Segoe UI",sans-serif; --body:"Roboto","Segoe UI",sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--navy);font-family:var(--body)}
h2{font-family:var(--title);font-weight:700;font-size:18px;margin:0 0 12px}
.topbar{display:flex;justify-content:space-between;align-items:center;
  background:var(--navy);color:#fff;padding:14px 28px;font-family:var(--title)}
.brand{font-weight:700;letter-spacing:.3px}.brand .mark{color:var(--magenta)}
.brand .sep{opacity:.5;margin:0 6px}
.freshness{font-size:12px;opacity:.85;font-family:var(--body)}
main{max-width:1180px;margin:0 auto;padding:24px 28px 64px}
section{margin-bottom:32px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
.card{background:#fff;border:1px solid var(--rule);border-radius:10px;padding:16px;
  box-shadow:0 1px 2px rgba(7,29,73,.04)}
.card h3{font-family:var(--title);font-size:15px;margin:0 0 8px}
.card .meta{font-size:13px;color:var(--gray);line-height:1.55}
.card .meta b{color:var(--navy)}
.badge{display:inline-block;font-size:11px;font-weight:600;padding:2px 8px;border-radius:999px}
.badge.updated{background:var(--pink);color:var(--magenta)}
.badge.stale{background:#FFF3D6;color:#9A6B00}
.tag{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.4px}
.tag.capability-ready{color:var(--teal)} .tag.data-gap{color:var(--magenta)}
.view-card{position:relative;cursor:pointer}
.view-card.placeholder{opacity:.5;background:#F1F4F9;cursor:not-allowed}
.view-card .status{font-size:12px;color:var(--gray);margin-top:8px}
.view-card.selected{border-color:var(--teal);box-shadow:0 0 0 2px rgba(7,178,172,.35)}
.view-card .runstate{font-size:12px;margin-top:8px;font-weight:600}
.runstate.ok{color:var(--teal)} .runstate.fail{color:var(--magenta)} .runstate.running{color:var(--gray)}
.controls{display:flex;gap:10px;flex-wrap:wrap}
.btn{font-family:var(--title);font-weight:600;font-size:13px;border-radius:8px;
  border:1px solid var(--rule);background:#fff;color:var(--navy);padding:9px 16px;cursor:pointer}
.btn.primary{background:var(--magenta);border-color:var(--magenta);color:#fff}
.btn.ghost{color:var(--gray)} .btn:disabled{opacity:.5;cursor:default}
.banner{margin-top:14px;padding:12px 16px;border-radius:8px;font-size:14px;
  background:var(--bluefill);border-left:4px solid var(--teal)}
.banner.warn{background:var(--pink);border-left-color:var(--magenta)}
.banner.hidden,.hidden{display:none}
.views-head{display:flex;justify-content:space-between;align-items:center}
.views-actions{display:flex;gap:14px;align-items:center}
.selall{font-size:13px;color:var(--gray)}
.result-wrap{display:grid;grid-template-columns:2fr 1fr;gap:18px;align-items:start}
.takeaways{font-size:13px;color:var(--gray);white-space:pre-wrap;
  background:#fff;border:1px solid var(--rule);border-radius:10px;padding:14px}
#chart{background:#fff;border:1px solid var(--rule);border-radius:10px;padding:12px}
pre{background:#0d1530;color:#cfe3ff;padding:12px;border-radius:8px;overflow:auto;font-size:12px}
table{border-collapse:collapse;width:100%;font-size:12px;margin-top:12px}
th,td{border-bottom:1px solid var(--rule);padding:5px 8px;text-align:right}
th:first-child,td:first-child{text-align:left}
```

- [ ] **Step 3: Write `web/app.js`**

```javascript
const $ = (s) => document.querySelector(s);
const api = async (m, p, b) => {
  const r = await fetch(p, b ? {method:m, headers:{'Content-Type':'application/json'}, body:JSON.stringify(b)} : {method:m});
  if (!r.ok) throw new Error((await r.json().catch(()=>({}))).detail || r.status);
  return r.headers.get('content-type')?.includes('json') ? r.json() : r;
};

let SELECTED = new Set();

async function loadTables(){
  const tables = await api('GET','/api/tables');
  let maxStamp = '';
  $('#tables').innerHTML = tables.map(t=>{
    if (t.max_date > maxStamp) maxStamp = t.max_date;
    return `<div class="card">
      <h3>${t.name} ${t.updated?'<span class="badge updated">data updated</span>':''}</h3>
      <div class="meta">
        <div>${t.description||''}</div>
        <div><b>Grain:</b> ${t.grain}</div>
        <div><b>Date range:</b> ${t.min_date} → ${t.max_date}</div>
        <div><b>Rows:</b> ${t.row_count.toLocaleString()} · <b>Refresh:</b> ${t.refresh}</div>
      </div></div>`;
  }).join('');
  $('#freshness').textContent = `Latest data: ${maxStamp}`;
}

async function loadViews(){
  const views = await api('GET','/api/views');
  $('#views').innerHTML = views.map(v=>{
    if (v.status !== 'built'){
      return `<div class="card view-card placeholder">
        <h3>${v.title}</h3>
        <div class="meta">${v.description||''}</div>
        <div class="tag ${v.tag}">${v.tag==='data-gap'?'Data gap':'Capability ready'}</div>
        ${v.note?`<div class="status">${v.note}</div>`:''}</div>`;
    }
    const stale = v.stale?'<span class="badge stale">stale</span>':'';
    const last = v.never_run?'never run':`last run ${v.last_run_at} · ${v.row_count} rows`;
    return `<div class="card view-card${SELECTED.has(v.id)?' selected':''}" data-id="${v.id}">
      <h3>${v.title} ${stale}</h3>
      <div class="meta">${v.description||''}</div>
      <div class="status">${last}</div>
      <div class="runstate" id="rs-${v.id}"></div></div>`;
  }).join('');
  document.querySelectorAll('.view-card:not(.placeholder)').forEach(el=>{
    el.onclick = ()=>{
      const id = el.dataset.id;
      if (SELECTED.has(id)){SELECTED.delete(id); el.classList.remove('selected');}
      else {SELECTED.add(id); el.classList.add('selected');}
    };
  });
}

async function dataRefresh(){
  const r = await api('POST','/api/data/refresh-check');
  const b = $('#banner'); b.classList.remove('hidden');
  if (r.changed_tables.length){
    b.className = 'banner warn';
    b.innerHTML = `Data has updated (${r.changed_tables.join(', ')}). `+
      `${r.stale_views.length} view(s) can be refreshed. `+
      `<button class="btn" id="btn-ack">Acknowledge</button>`;
    $('#btn-ack').onclick = async()=>{ await api('POST','/api/data/acknowledge'); await refreshAll(); $('#banner').classList.add('hidden'); };
  } else {
    b.className = 'banner';
    b.textContent = `No new data. Schema: ${r.schema}. All views up to date.`;
  }
  if (r.schema === 'drift') b.innerHTML += `<div>⚠ schema drift — check dictionaries.</div>`;
}

async function runSelected(){
  if (!SELECTED.size){ alert('Select at least one view.'); return; }
  $('#btn-run').disabled = true;
  for (const id of SELECTED){
    const rs = $('#rs-'+id); if (rs){rs.className='runstate running'; rs.textContent='running…';}
    try{
      const res = await api('POST',`/api/views/${id}/run`);
      if (rs){ rs.className='runstate '+(res.ok?'ok':'fail');
        rs.textContent = res.ok?`✓ ${res.row_count} rows · validation ${res.validation}`:'✗ failed'; }
      if (res.ok) await showResult(id, res.log);
    }catch(e){ if (rs){rs.className='runstate fail'; rs.textContent='✗ '+e.message;} }
  }
  $('#btn-run').disabled = false;
  await loadViews();
}

async function showResult(id, log){
  const data = await api('GET',`/api/views/${id}/result`);
  $('#result-section').classList.remove('hidden');
  $('#result-title').textContent = data.spec.title?.replace(/\n/g,' ') || id;
  $('#takeaways').textContent = data.takeaways || '';
  $('#runlog').textContent = log || '';
  drawChart(data.rows, data.spec);
  drawTable(data.rows, data.spec);
}

function drawChart(rows, spec){
  const W=620,H=320,P=40;
  const date=spec.date_column, series=spec.series_columns;
  const colors={UC:'#07B2AC',CD:'#E40D62'};
  const xs=rows.map((_,i)=>i);
  const all=series.flatMap(s=>rows.map(r=>+r[s]));
  const ymax=Math.max(...all,1);
  const px=i=>P+i*(W-2*P)/Math.max(rows.length-1,1);
  const py=v=>H-P-(v/ymax)*(H-2*P);
  const line=s=>rows.map((r,i)=>`${i?'L':'M'}${px(i).toFixed(1)},${py(+r[s]).toFixed(1)}`).join(' ');
  const legend=series.map((s,i)=>`<text x="${P+i*130}" y="18" fill="${colors[s]||'#071D49'}" font-size="12" font-weight="700">● ${s}</text>`).join('');
  const paths=series.map(s=>`<path d="${line(s)}" fill="none" stroke="${colors[s]||'#071D49'}" stroke-width="2.25"/>`).join('');
  $('#chart').innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="100%">
    ${legend}
    <line x1="${P}" y1="${H-P}" x2="${W-P}" y2="${H-P}" stroke="#D9DEE8"/>
    <line x1="${P}" y1="${P}" x2="${P}" y2="${H-P}" stroke="#D9DEE8"/>
    <text x="${P}" y="${H-P+16}" font-size="10" fill="#50535A">${rows[0][date]}</text>
    <text x="${W-P}" y="${H-P+16}" font-size="10" fill="#50535A" text-anchor="end">${rows[rows.length-1][date]}</text>
    ${paths}</svg>`;
}

function drawTable(rows, spec){
  const cols=[spec.date_column,...spec.series_columns,spec.total_column];
  const head=cols.map(c=>`<th>${c}</th>`).join('');
  const body=rows.map(r=>`<tr>${cols.map(c=>`<td>${isNaN(+r[c])?r[c]:(+r[c]).toLocaleString(undefined,{maximumFractionDigits:1})}</td>`).join('')}</tr>`).join('');
  $('#result-table').innerHTML=`<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

async function refreshAll(){ await loadTables(); await loadViews(); }

$('#btn-refresh').onclick = dataRefresh;
$('#btn-run').onclick = runSelected;
$('#btn-simulate').onclick = async()=>{ await api('POST','/api/data/simulate'); await refreshAll(); await dataRefresh(); };
$('#btn-reset').onclick = async()=>{ try{ await api('POST','/api/data/reset'); await refreshAll(); $('#banner').classList.add('hidden'); }catch(e){ alert(e.message);} };
$('#select-all').onclick = (e)=>{
  document.querySelectorAll('.view-card:not(.placeholder)').forEach(el=>{
    if (e.target.checked){SELECTED.add(el.dataset.id); el.classList.add('selected');}
    else {SELECTED.delete(el.dataset.id); el.classList.remove('selected');}
  });
};
refreshAll();
```

- [ ] **Step 4: Manual QA**

Run the server (`py -3 run_dashboard.py` — created in Task 10) and open `http://127.0.0.1:8000`. Confirm:
- Two dataset cards show correct grain + `2024-05-03 → 2026-05-08` (weekly) / `2020-05-01 → 2026-04-01` (monthly); no "data updated" badge on first load.
- 2 selectable view cards (TREMFYA, SKYRIZI) + 5 greyed placeholders; placeholders aren't selectable; `Payer Mix` shows the `Data gap` tag.
- "Simulate new month" → dataset dates advance, "data updated" badge + banner appear, stale flags on built views.
- Selecting TREMFYA + "Run selected" → runstate goes running → ✓, chart (teal UC / magenta CD) + table + takeaways render; row count grew after simulate.
- "Acknowledge" clears the banner; "Reset demo data" restores original dates.
- Colors are navy/teal/magenta; headings render in Montserrat.

- [ ] **Step 5: Checkpoint.**

---

## Task 10: Launcher + README

**Files:**
- Create: `run_dashboard.py`
- Create: `web/README.md` (run instructions)

- [ ] **Step 1: Write `run_dashboard.py`**

```python
# run_dashboard.py
"""Launch the demo dashboard:  py -3 run_dashboard.py  ->  http://127.0.0.1:8000"""
import uvicorn

from server.app import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
```

- [ ] **Step 2: Write `web/README.md`**

```markdown
# Query-to-Slide — Demo Dashboard

## First-time setup
1. `py -3 -m pip install fastapi uvicorn`
2. `py -3 scripts/seed_views.py`   # builds output/tremfya_ibd_split + output/skyrizi_ibd_split

## Run
`py -3 run_dashboard.py` then open http://127.0.0.1:8000

## What it does
- Lists datasets (grain, date range, rows) and built views (+ greyed placeholders).
- **Data Refresh**: re-checks min/max dates, runs schema validation, flags stale views.
- **Simulate new month** / **Reset demo data**: append a cloned next period to /data, or restore the originals byte-for-byte.
- **Run selected**: re-executes each view's analysis_code.py against current /data, validates, rebuilds the single-slide deck, and renders the table + chart.

It re-runs the existing committed scripts — it never calls an LLM. Building a *new* view still goes through Claude + CLAUDE.md.
```

- [ ] **Step 3: Full regression run**

Run: `py -3 -m pytest tests/ -v`
Expected: all tests pass.

- [ ] **Step 4: End-to-end smoke**

Run `py -3 run_dashboard.py`, perform the Task 9 Step 4 QA flow once more end-to-end, then Ctrl-C.

- [ ] **Step 5: Checkpoint — feature complete.**

---

## Spec coverage map

| Spec section | Task(s) |
|---|---|
| §3 Architecture / module layout | 0–10 |
| §4 View registry (`views.yaml`) | 6 |
| §5 Seeding canonical views + plan normalization | 6 |
| §6 API endpoints | 8 (logic in 2,3,4,5,7) |
| §7 Simulate + snapshot lifecycle | 3, 4 |
| §8 Frontend (datasets, controls, views grid, result panel, SVG chart) | 9 |
| §9 Error handling (exit codes, lock/409, no-backup, never-run, deck guard) | 5, 7, 8 |
| §10 Testing (min/max, snapshot diff, simulate↔reset byte-identical, run→meta, exit-code map) | 2,3,4,5,7,8 |
| §11 Build order | Task order 0→10 |
```

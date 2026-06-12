"""View registry + deterministic re-run of a built view's committed scripts."""
import json
import re
import shutil
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


def declared_tables(v) -> list:
    return v.get("tables") or ["Weekly_Data_Tabular", "Monthly_Data_Tabular"]


def _current_max(tables=None) -> dict:
    tables = tables if tables is not None else datasets.all_tables()
    return {t["name"]: t["max_date"] for t in tables}


def _declared_max(v) -> dict:
    cur = _current_max()
    return {n: cur[n] for n in declared_tables(v) if n in cur}


def _is_stale(v, meta, cur: dict) -> bool:
    rec = meta.get("data_max_at_run")
    if not rec:
        return False
    if isinstance(rec, str):                       # pre-v2 metas: weekly only
        rec = {"Weekly_Data_Tabular": rec}
    return any(cur.get(n) and m and cur[n] > m for n, m in rec.items())


def read_run_meta(v) -> dict:
    p = _folder(v) / "run_meta.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def parse_validation(out: str, rc: int) -> dict:
    """Structure validate_result.py stdout for the transparency panel."""
    checks = []
    for line in out.splitlines():
        ls = line.strip()
        if ls.startswith("[WARN]"):
            checks.append({"level": "warn", "message": ls[6:].strip()})
        elif ls.startswith("[ERROR]"):
            checks.append({"level": "error", "message": ls[7:].strip()})
    m = re.search(r"Rows:\s*(\d+)", out)
    return {"verdict": {0: "pass", 2: "warnings"}.get(rc, "fail"),
            "rows": int(m.group(1)) if m else None,
            "checks": checks,
            "ran": ["result.csv exists & non-empty", "row count vs plan",
                    "slide-size convention", "null audit on metric columns",
                    "duplicate-row check"]}


def _append_history(folder, meta: dict, ok: bool) -> None:
    hp = folder / "run_history.json"
    hist = json.loads(hp.read_text(encoding="utf-8")) if hp.exists() else []
    slim = {k: v for k, v in meta.items() if k != "validation_detail"}
    hist.append({**slim, "ok": ok})
    hp.write_text(json.dumps(hist[-50:], indent=2), encoding="utf-8")


def view_status(v, cur=None) -> dict:
    base = {"id": v["id"], "title": v["title"], "status": v["status"],
            "tag": v.get("tag"), "brand": v.get("brand"),
            "description": v.get("description", ""), "note": v.get("note")}
    if v["status"] != "built":
        return base
    meta = read_run_meta(v)
    cur = cur if cur is not None else _current_max()
    base.update({
        "last_run_at": meta.get("last_run_at"),
        "validation": meta.get("validation_status"),
        "row_count": meta.get("row_count"),
        "deck_available": meta.get("deck_available", False),
        "data_max_at_run": meta.get("data_max_at_run"),
        "never_run": not bool(meta),
        "stale": _is_stale(v, meta, cur),
    })
    return base


def all_view_status(tables=None) -> list:
    cur = _current_max(tables)
    return [view_status(v, cur) for v in load_registry()]


def _finish(v, folder, ok, validation, deck, log, vdetail=None):
    rp = folder / "result.csv"
    rows = int(len(pd.read_csv(rp))) if rp.exists() else None
    meta = {
        "last_run_at": datetime.now().isoformat(timespec="seconds"),
        "data_max_at_run": _declared_max(v),
        "validation_status": validation,
        "validation_detail": vdetail,
        "row_count": rows,
        "deck_available": deck,
    }
    (folder / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    _append_history(folder, meta, ok)
    return {"id": v["id"], "ok": ok, "validation": validation,
            "deck_available": deck, "row_count": rows, "log": "\n".join(log)}


def run_view_core(v, on_stage=None) -> dict:
    """analysis → validate → deck, NO locking (caller holds the run lock).
    on_stage(stage, status, detail) fires at each transition for job steppers."""
    folder = _folder(v)
    log = []

    def stage(name, status, detail=""):
        if on_stage:
            on_stage(name, status, detail)

    rp = folder / "result.csv"
    if rp.exists():                      # keep prior output for run-over-run diff
        shutil.copy2(rp, folder / "result_prev.csv")

    stage("analysis", "running")
    rc, out, err = runner.run_script([str(folder / "analysis_code.py")])
    log.append(f"$ analysis_code.py -> {rc}\n{out}{err}".rstrip())
    if rc != 0:
        stage("analysis", "fail", (out + err)[-400:])
        return _finish(v, folder, ok=False, validation=None, deck=False, log=log)
    stage("analysis", "ok")

    stage("validate", "running")
    vrc, vo, ve = runner.run_script(
        [str(config.scripts_dir() / "validate_result.py"), str(folder)])
    log.append(f"$ validate_result.py -> {vrc}\n{vo}{ve}".rstrip())
    validation = "pass" if runner.validation_ok(vrc) else "fail"
    vdetail = parse_validation(vo, vrc)
    if validation == "fail":
        stage("validate", "fail")
        return _finish(v, folder, ok=False, validation=validation, deck=False,
                       log=log, vdetail=vdetail)
    stage("validate", "ok")

    deck_ok = False
    # deck intent: indication_split kind, an explicit deck: true in views.yaml
    # (engine-registered views — ENGINE_INBOX.md step 4), or a deck_spec.json
    # already in the folder from a previous deck build.
    spec_p = folder / "deck_spec.json"
    if (v.get("kind") == "indication_split" or v.get("deck") or spec_p.exists()):
        stage("deck", "running")
        # dispatch builder by spec shape so non-UC/CD decks aren't mis-rendered
        builder = "build_deck_pptx.py"
        if spec_p.exists():
            try:
                ck = json.loads(spec_p.read_text(encoding="utf-8")).get("chart_kind")
            except Exception:
                ck = None
            if ck == "monthly_multiline":
                builder = "build_deck_monthly.py"
        drc, do, de = runner.run_script(
            [str(config.scripts_dir() / builder), str(folder)])
        log.append(f"$ {builder} -> {drc}\n{do}{de}".rstrip())
        deck_ok = drc == 0
        stage("deck", "ok" if deck_ok else "fail")
    return _finish(v, folder, ok=True, validation=validation, deck=deck_ok,
                   log=log, vdetail=vdetail)


def run_view(vid: str) -> dict:
    """Synchronous single-view run (legacy endpoint). Locks, then delegates."""
    v = view_by_id(vid)
    if v is None or v.get("status") != "built":
        return {"id": vid, "ok": False, "log": "not a runnable built view"}
    with runner.run_lock():
        return run_view_core(v)


def run_diff(v) -> dict:
    """Compare result.csv to result_prev.csv: rows added + latest-common-row deltas."""
    if "folder" not in v:                      # placeholder views have no folder
        return {"available": False}
    folder = _folder(v)
    cur_p, prev_p = folder / "result.csv", folder / "result_prev.csv"
    if not (cur_p.exists() and prev_p.exists()):
        return {"available": False}
    cur, prev = pd.read_csv(cur_p), pd.read_csv(prev_p)
    date_col = cur.columns[0]
    new_rows = sorted(set(cur[date_col].astype(str)) - set(prev[date_col].astype(str)))
    common = sorted(set(cur[date_col].astype(str)) & set(prev[date_col].astype(str)))
    deltas = {}
    if common:
        last = common[-1]
        c_row = cur[cur[date_col].astype(str) == last].iloc[-1]
        p_row = prev[prev[date_col].astype(str) == last].iloc[-1]
        for col in cur.select_dtypes("number").columns:
            if col in prev.columns:
                pc, cc = float(p_row[col]), float(c_row[col])
                if pc != cc:
                    deltas[col] = {"prev": pc, "curr": cc, "delta": round(cc - pc, 2)}
    return {"available": True, "new_rows": new_rows,
            "compared_at": common[-1] if common else None, "latest_deltas": deltas}


def read_history(v) -> list:
    if "folder" not in v:                      # placeholder views have no folder
        return []
    hp = _folder(v) / "run_history.json"
    return json.loads(hp.read_text(encoding="utf-8")) if hp.exists() else []

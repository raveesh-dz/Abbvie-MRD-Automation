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


def view_status(v, weekly_max=None) -> dict:
    base = {"id": v["id"], "title": v["title"], "status": v["status"],
            "tag": v.get("tag"), "brand": v.get("brand"),
            "description": v.get("description", ""), "note": v.get("note")}
    if v["status"] != "built":
        return base
    meta = read_run_meta(v)
    wk = weekly_max if weekly_max is not None else _weekly_max()
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


def _weekly_max_from(tables):
    return next((t["max_date"] for t in tables
                 if t["name"] == "Weekly_Data_Tabular"), None)


def all_view_status(tables=None) -> list:
    # Weekly max is identical for every view; parse the CSVs once, not N times.
    wk = _weekly_max_from(tables) if tables is not None else _weekly_max()
    return [view_status(v, wk) for v in load_registry()]


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

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

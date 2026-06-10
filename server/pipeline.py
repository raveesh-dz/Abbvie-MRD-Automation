"""Refresh orchestration: check (read-only) / data (check+acknowledge) /
full (check → run stale views → acknowledge) plus batch view-run jobs."""
from . import config, datasets, jobs, runner, snapshot, views


def check() -> dict:
    rc, out, err = runner.run_script(
        [str(config.scripts_dir() / "validate_schema.py"),
         "--root", str(config.get_root())])
    schema = {0: "clear", 1: "drift", 2: "warnings"}.get(rc, "unknown")
    tables = datasets.all_tables()
    snap = snapshot.read_snapshot()
    cmp = {t["name"]: {"snapshot_max": snap.get(t["name"], {}).get("max"),
                       "current_max": t["max_date"],
                       "changed": snap.get(t["name"], {}).get("max") != t["max_date"]}
           for t in tables}
    stale = [s["id"] for s in views.all_view_status(tables=tables) if s.get("stale")]
    return {"schema": schema, "schema_log": (out + err).strip(), "tables": cmp,
            "changed_tables": [k for k, v in cmp.items() if v["changed"]],
            "stale_views": stale}


def data_refresh() -> dict:
    rep = check()
    snapshot.acknowledge()
    rep["acknowledged"] = True
    return rep


def _run_one(job, idx, vid):
    v = views.view_by_id(vid)
    if not v or v.get("status") != "built":
        jobs.update_step(job, idx, "fail", "not a runnable built view")
        return {"id": vid, "ok": False}
    jobs.update_step(job, idx, "running")

    def on_stage(stage, status, detail="", _i=idx):
        jobs.update_step(job, _i, "running", f"{stage}: {status}")

    res = views.run_view_core(v, on_stage=on_stage)
    if res["ok"]:
        jobs.update_step(job, idx, "ok",
                         f"validation {res.get('validation')} · {res.get('row_count')} rows")
    else:
        # surface the failure inline — the stepper detail is the run log here
        jobs.update_step(job, idx, "fail", (res.get("log") or "run failed")[-400:])
    return res


def _summary(results):
    return {"views_run": len(results),
            "views_ok": sum(1 for r in results if r["ok"]),
            "results": [{**{k: r.get(k) for k in
                            ("id", "ok", "validation", "row_count", "deck_available")},
                         # failures carry their log so the frontend can show it
                         "log": None if r.get("ok") else r.get("log")}
                        for r in results]}


def run_views_job(view_ids: list) -> dict:
    steps = [{"name": f"run {vid}", "view_id": vid} for vid in view_ids]
    job = jobs.create_job("views", steps)

    def target(job):
        with runner.run_lock(block=True):
            return _summary([_run_one(job, i, vid) for i, vid in enumerate(view_ids)])
    return jobs.start(job, target)


def full_refresh_job(view_ids=None) -> dict:
    # Callers that just ran check() (the frontend pre-flight) pass its
    # stale_views as view_ids — no duplicate check/subprocess here. Only
    # bare API calls (view_ids=None) pay one extra check() to build steps.
    targets = view_ids if view_ids is not None else check()["stale_views"]
    steps = ([{"name": "schema & data check"}]
             + [{"name": f"run {vid}", "view_id": vid} for vid in targets]
             + [{"name": "acknowledge data"}])
    job = jobs.create_job("pipeline", steps)

    def target(job):
        with runner.run_lock(block=True):
            jobs.update_step(job, 0, "running")
            rep = check()        # authoritative re-check UNDER the lock
            if rep["schema"] == "drift":
                jobs.update_step(job, 0, "fail", "schema drift — fix dictionaries first")
                raise RuntimeError("schema drift — pipeline halted")
            jobs.update_step(job, 0, "ok",
                             "changed: " + (", ".join(rep["changed_tables"]) or "none"))
            still_stale = set(rep["stale_views"])
            results = []
            for i, vid in enumerate(targets, start=1):
                if vid not in still_stale:
                    # an earlier queued job already refreshed it
                    jobs.update_step(job, i, "ok", "already fresh — skipped")
                    continue
                results.append(_run_one(job, i, vid))
            last = len(job["steps"]) - 1
            jobs.update_step(job, last, "running")
            snapshot.acknowledge()
            jobs.update_step(job, last, "ok")
            return _summary(results)
    return jobs.start(job, target)

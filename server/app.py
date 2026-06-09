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


def create_app() -> FastAPI:
    """Build a fresh app. Used by the launcher (module-level `app` below) AND by
    tests, which call create_app() AFTER setting QTS_ROOT so the StaticFiles mount
    — which binds its directory at construction, not per request — points at that
    test's temp copy instead of leaking the first import's path into every test."""
    app = FastAPI(title="Query-to-Slide Dashboard", lifespan=lifespan)

    @app.get("/api/tables")
    def api_tables():
        tables = datasets.all_tables()       # one parse of each CSV
        snap = snapshot.read_snapshot()      # snapshot file only — no CSV parse
        for t in tables:
            t["updated"] = snap.get(t["name"], {}).get("max") != t["max_date"]
        return tables

    @app.get("/api/views")
    def api_views():
        return views.all_view_status()

    @app.post("/api/data/refresh-check")
    def api_refresh_check():
        rc, out, err = runner.run_script(
            [str(config.scripts_dir() / "validate_schema.py"), "--root", str(config.get_root())])
        schema = {0: "clear", 1: "drift", 2: "warnings"}.get(rc, "unknown")
        tables = datasets.all_tables()       # parse once; reuse for both checks below
        snap = snapshot.read_snapshot()
        cmp = {t["name"]: {"snapshot_max": snap.get(t["name"], {}).get("max"),
                           "current_max": t["max_date"],
                           "changed": snap.get(t["name"], {}).get("max") != t["max_date"]}
               for t in tables}
        stale = [s["id"] for s in views.all_view_status(tables=tables) if s.get("stale")]
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
        meta = views.read_run_meta(v)
        return {"rows": rows, "spec": spec,
                "data_max_at_run": meta.get("data_max_at_run") if meta else None,
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

    # Static page mounted LAST so explicit /api routes win. check_dir=False so
    # construction never fails when web/ is absent (temp repo copy, or before Task 9).
    app.mount("/", StaticFiles(directory=str(config.web_dir()), html=True, check_dir=False), name="web")
    return app


# Module-level instance for the launcher (run_dashboard.py imports this).
app = create_app()

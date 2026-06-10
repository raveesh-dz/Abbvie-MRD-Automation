"""FastAPI surface. Declares /api routes, then mounts the static web/ page at /."""
import csv
import json
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, datasets, jobs, pipeline, runner, simulate, snapshot, views


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
        return pipeline.check()

    @app.post("/api/data/acknowledge")
    def api_acknowledge():
        return snapshot.acknowledge()

    @app.post("/api/data/simulate")
    def api_simulate(body: dict | None = Body(None)):
        try:
            with runner.run_lock():
                return simulate.simulate(weeks=(body or {}).get("weeks", 4))
        except runner.Busy:
            raise HTTPException(409, "busy")

    @app.get("/api/data/demo-status")
    def api_demo_status():
        return {"demo_active": simulate.has_backup()}

    @app.post("/api/data/reset")
    def api_reset():
        try:
            with runner.run_lock():
                ok = simulate.reset()
        except runner.Busy:
            raise HTTPException(409, "busy")
        if not ok:
            raise HTTPException(400, "no backup to reset from")
        snapshot.acknowledge()      # snapshot follows the restored originals
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
        spec_p = folder / "deck_spec.json"
        if spec_p.exists():
            spec = json.loads(spec_p.read_text(encoding="utf-8"))
        else:                                   # infer from result.csv header
            cols = list(rows[0].keys()) if rows else []

            def _num(c):
                try:
                    float(rows[0][c]); return True
                except (ValueError, TypeError):
                    return False
            numeric = [c for c in cols[1:] if _num(c)]
            total = next((c for c in numeric if "total" in c.lower()), None)
            spec = {"date_column": cols[0] if cols else None,
                    "series_columns": [c for c in numeric if c != total],
                    "total_column": total, "title": v["title"],
                    "inferred": True}   # provenance: deckpreview.js skips inferred specs
        tk = folder / "takeaways.md"
        meta = views.read_run_meta(v)
        return {"rows": rows, "spec": spec, "meta": meta,
                "data_max_at_run": meta.get("data_max_at_run") if meta else None,
                "takeaways": tk.read_text(encoding="utf-8") if tk.exists() else ""}

    @app.get("/api/views/{vid}/diff")
    def api_diff(vid: str):
        v = views.view_by_id(vid)
        if not v:
            raise HTTPException(404, "no such view")
        return views.run_diff(v)

    @app.get("/api/views/{vid}/history")
    def api_history(vid: str):
        v = views.view_by_id(vid)
        if not v:
            raise HTTPException(404, "no such view")
        return views.read_history(v)

    @app.get("/api/views/{vid}/deck")
    def api_deck(vid: str):
        v = views.view_by_id(vid)
        if not v:
            raise HTTPException(404, "no such view")
        deck = config.get_root() / v["folder"] / "deck.pptx"
        if not deck.exists():
            raise HTTPException(404, "no deck")
        return FileResponse(deck, filename=f"{vid}.pptx")

    @app.post("/api/pipeline/run")
    def api_pipeline(body: dict | None = Body(None)):
        mode = (body or {}).get("mode", "check")
        if mode == "check":
            return pipeline.check()
        if mode == "data":
            return pipeline.data_refresh()
        if mode == "full":
            job = pipeline.full_refresh_job((body or {}).get("views") or None)
            return {"job_id": job["id"]}
        raise HTTPException(400, "mode must be check|data|full")

    @app.post("/api/views/run")
    def api_run_batch(body: dict | None = Body(None)):
        ids = (body or {}).get("views") or []
        if not ids:
            raise HTTPException(400, "no views given")
        job = pipeline.run_views_job(ids)
        return {"job_id": job["id"]}

    @app.get("/api/jobs/{jid}")
    def api_job(jid: str):
        j = jobs.get_job(jid)
        if not j:
            raise HTTPException(404, "no such job")
        return j

    # Static page mounted LAST so explicit /api routes win. check_dir=False so
    # construction never fails when web/ is absent (temp repo copy, or before Task 9).
    app.mount("/", StaticFiles(directory=str(config.web_dir()), html=True, check_dir=False), name="web")
    return app


# Module-level instance for the launcher (run_dashboard.py imports this).
app = create_app()

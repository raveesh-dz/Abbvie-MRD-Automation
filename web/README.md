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

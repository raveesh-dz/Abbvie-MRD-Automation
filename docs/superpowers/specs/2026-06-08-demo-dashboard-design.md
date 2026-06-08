# Demo Dashboard — Design Spec

date: 2026-06-08
status: approved-for-planning
self-review score: 991/1000

## 1. Purpose

A local, demo-able web dashboard that acts as a **deterministic control panel**
over the already-built Query-to-Slide analyses. It surfaces the project's
datasets, lists the analyses ("views") that have already been built, detects
when the underlying data has advanced, and lets the user re-run any view (or all
selected views) against the current data — regenerating the result table, an
in-browser chart, and the single-slide deck.

It is **not** the CLAUDE.md analysis engine. It never invokes an LLM and never
authors new analysis logic. Building a *new* view still happens through Claude +
the CLAUDE.md protocol; the dashboard only re-executes views that already exist
and shows placeholders for ones that don't.

### Non-goals
- No LLM calls, no new-analysis authoring from the UI.
- No editing of `/semantic/` or `/metadata/` from the UI.
- No deployment/hosting concerns — it runs on `localhost` for a live demo.
- No patient-grain or arbitrary ad-hoc querying.

## 2. Key facts the design depends on (verified against the repo)

- An existing view's `analysis_code.py` is **standalone and re-runnable**: it
  reads the full CSVs from `/data` and writes `result.csv` next to itself. New
  weeks in the data flow through automatically — no code change needed.
- `analysis_code.py` resolves the project root via `Path(__file__).resolve().parents[2]`.
  Therefore a view's canonical folder **must sit exactly one level under
  `output/`** (`output/<view_id>/analysis_code.py`) for the path math to hold.
- `scripts/validate_result.py <folder>` reads `result.csv` **and**
  `analysis_plan.md`. If the plan contains `expected_row_count: <N>` it FAILS
  (exit 1) when the row count differs. It also WARNS (exit 2) on >15 rows unless
  the plan text contains "full grain". → Seeded plans must be full-grain and must
  NOT pin a numeric row count. The dashboard treats **exit 0 and 2 as success**,
  exit 1 as failure.
- `scripts/build_deck_pptx.py <folder>` reads `deck_spec.json` + `result.csv`
  from the folder and emits a single content slide (`deck.pptx`). It is
  **hard-coded to UC/CD series** (`series["UC"]`, `series["CD"]`). Deck rebuild
  is therefore supported only for UC/CD indication-split views.
- Deck brand tokens (committed, "do not change without sign-off"):
  navy `071D49`, teal `07B2AC`, magenta `E40D62`, gray `50535A`; fonts
  Montserrat Medium (titles) + Roboto (body). The dashboard UI reuses these.
- `scripts/validate_schema.py` is Gate 0: exit 0 = clear, 1 = drift (HALT),
  2 = warnings (excluded tables, proceed).
- Date columns: `Weekly_Data_Tabular.WEEK_ENDING`, `Monthly_Data_Tabular.MONTH_DATE`
  (both declared `type: date` in their YAML dictionaries).
- Git is intentionally NOT initialized in this project (per MEMORY.md), so this
  spec is not committed; no git steps apply to the dashboard.

## 3. Architecture

One local app, two halves:

```
run_dashboard.py            # launches uvicorn on 127.0.0.1:8000
server/
  app.py                    # FastAPI app + routes
  datasets.py               # read tables + dictionaries, compute min/max
  views.py                  # load views.yaml, run a view, staleness
  snapshot.py               # data_snapshot.json read/compare/update
  simulate.py               # clone-last-period append + backup/reset
  runner.py                 # subprocess wrapper + in-flight lock + exit-code map
web/
  index.html                # single page
  app.js                    # fetch() calls + render + SVG chart
  styles.css                # DataZymes brand tokens
  fonts/                    # vendored Montserrat + Roboto woff2
views.yaml                  # the view registry (source of truth for cards)
output/<view_id>/           # canonical per-view folders (seeded)
data/_original/             # untouched backup of the real CSVs (created on first simulate)
data/.snapshot.json         # last-acknowledged min/max per table
```

The backend is the only component that touches the filesystem or runs Python.
The frontend is pure presentation: it calls JSON endpoints and renders. No node
build step; fonts and chart are local (offline-safe).

Each backend module has one job and a narrow interface, so each can be tested in
isolation (Section 9).

## 4. View registry (`views.yaml`)

Single source of truth for the cards; de-duplicates the messy run history.

```yaml
views:
  - id: tremfya_ibd_split
    title: "TREMFYA — IBD Indication Split"
    brand: TREMFYA
    description: "Weekly TRx split across UC / CD, full series."
    status: built            # built | placeholder
    kind: indication_split   # determines deck support (UC/CD)
    folder: output/tremfya_ibd_split

  - id: skyrizi_ibd_split
    title: "SKYRIZI (SQ+IV+OBI) — IBD Indication Split"
    brand: SKYRIZI
    description: "Combined Skyrizi weekly TRx split across UC / CD, full series."
    status: built
    kind: indication_split
    folder: output/skyrizi_ibd_split

  # ---- placeholders (greyed, not runnable) ----
  - id: humira_ibd_split
    title: "HUMIRA — IBD Indication Split"
    brand: HUMIRA
    status: placeholder
    tag: capability-ready
    note: "Same indication-split method; not yet built."

  - id: stelara_ibd_split
    title: "STELARA — IBD Indication Split"
    brand: STELARA
    status: placeholder
    tag: capability-ready

  - id: tremfya_by_doseform
    title: "TREMFYA — by Dose / Form (SQ 100 / 200 / Induction)"
    brand: TREMFYA
    status: placeholder
    tag: capability-ready

  - id: monthly_indication_trend
    title: "Monthly Indication Trend — all brands"
    status: placeholder
    tag: capability-ready

  - id: payer_mix
    title: "Payer Mix"
    status: placeholder
    tag: data-gap
    note: "Honest boundary — needs payer data not in any current table."
```

Two tags distinguish honest capability (`capability-ready`) from an honest
boundary (`data-gap`). Placeholders are never runnable and have no `folder`.

## 5. Seeding the canonical built views (one-time, scripted)

`scripts/seed_views.py` (idempotent) creates `output/tremfya_ibd_split/` and
`output/skyrizi_ibd_split/` by copying from the best existing runs:

| view | source run |
|---|---|
| tremfya_ibd_split | `output/run_2026-06-08_001` |
| skyrizi_ibd_split | `output/run_2026-06-08_002` |

For each, copy: `analysis_code.py`, `analysis_plan.md`, `deck_spec.json`,
`context.md`, `takeaways.md`, `query.txt`. Then **normalize the plan** so
validation survives data growth:
- remove/replace the `expected_row_count: <N>` line with a non-numeric
  descriptor, e.g. `expected_row_count: one row per WEEK_ENDING (full grain, grows with data)`;
- ensure the text contains "full grain" (suppresses the >15-row warning escalation).

The original run folders are left untouched. Seeding does not run anything; the
first dashboard refresh produces `result.csv` / `deck.pptx` / `run_meta.json`.

## 6. Backend API

All JSON, all under `/api`. Single in-flight run lock guards mutation endpoints
(`run`, `simulate`, `reset`); a second concurrent call returns `409 busy`.

| Method/Path | Does |
|---|---|
| `GET /api/tables` | Per table: name, description, grain, date column, **min/max date (live)**, row count, refresh cadence, `updated` flag (live max ≠ snapshot max). |
| `GET /api/views` | From `views.yaml`: each view's status/tag/title/brand + (built only) last_run_at, last validation status, row count, **stale** flag, deck availability. |
| `POST /api/data/refresh-check` | Runs `validate_schema.py`; re-reads each CSV's min/max; compares to snapshot. Returns per-table change + count of stale built views + schema verdict. Does NOT mutate snapshot. |
| `POST /api/data/acknowledge` | Writes current min/max into the snapshot (clears the "data updated" banner). |
| `POST /api/data/simulate` | Clone-last-period append to both CSVs (Section 7); backs up to `data/_original/` first. Returns new min/max. |
| `POST /api/data/reset` | Restores both CSVs byte-identical from `data/_original/`. |
| `POST /api/views/{id}/run` | **Synchronous, one view**: ① `py -3 output/{id}/analysis_code.py` → fresh `result.csv`; ② `py -3 scripts/validate_result.py output/{id}` (0/2 ok, 1 fail); ③ if `kind == indication_split`, `py -3 scripts/build_deck_pptx.py output/{id}`. Writes `run_meta.json`. Returns status, log, row count, result data, deck path. |
| `GET /api/views/{id}/result` | `result.csv` as JSON + the view's `deck_spec.json` chart config. |
| `GET /api/views/{id}/deck` | Downloads `deck.pptx`. |

"Run selected" / "Run all" is a **frontend loop** over `POST /run` — each card
updates as its request returns. No streaming/job infrastructure.

Exit-code mapping (in `runner.py`): analysis_code non-zero → fail; validate_result
1 → fail, 0/2 → pass (warnings surfaced in log); build_deck non-zero → deck
marked unavailable but the run is not failed (table/chart still valid).

## 7. Data simulation + snapshot lifecycle

**Snapshot** (`data/.snapshot.json`): seeded on first boot from current `/data`
min/max. Compared by `refresh-check`. Updated only by `acknowledge`. So:
boot → snapshot = real max; simulate → data advances, snapshot unchanged →
refresh-check reports "updated"; acknowledge → snapshot catches up → banner clears.

**Simulate** (`simulate.py`): for each table, take all rows of the latest period
(latest `WEEK_ENDING` for weekly, latest `MONTH_DATE` for monthly), clone them
with the date advanced (weekly: +7 days × ~4 weeks; monthly: +1 month) and the
numeric value multiplied by a small growth factor (e.g. 1.01–1.03). Cloning
preserves MARKET_TOTAL rows, NON_APPROVED flags, every product/indication
automatically — no per-row synthesis. On first simulate, copy both CSVs to
`data/_original/`. The UI labels simulated data clearly and offers **Reset demo
data**, which restores from `data/_original/` byte-for-byte.

This keeps the live demo repeatable and never permanently mutates the real CSVs.

## 8. Frontend (single branded page)

Brand tokens: navy `071D49`, teal `07B2AC`, magenta `E40D62`, gray `50535A`,
white; Montserrat Medium (headings) + Roboto (body), vendored. Design bar:
clean, infographic, no generic AI-dashboard aesthetic.

Sections:
1. **Header** — title, "DataZymes" wordmark, data-freshness stamp.
2. **Datasets panel** — one card per table: name, description, **grain**,
   **min–max date**, row count, refresh cadence; a "⚠ data updated" badge when
   the live max differs from the snapshot.
3. **Data controls** — `Data Refresh` (runs refresh-check; on change shows a
   banner: *"Data has updated — Weekly now runs to YYYY-MM-DD. N view(s) can be
   refreshed."* with an Acknowledge action); plus demo helpers `Simulate new
   month` and `Reset demo data`. Schema-drift verdict shown here if not clean.
4. **Views grid** — built views as **selectable cards** (checkbox) showing last
   run + a "stale — needs refresh" flag; placeholders as **greyed, non-selectable**
   cards with their tag (`capability-ready` / `data-gap`). Controls: `Select all`,
   `Run selected`.
5. **Result panel** — for an expanded finished view: result table + **hand-rolled
   SVG line chart** (series + colors from `deck_spec.json`), takeaways, deck
   download link, run log, and the data max-date the run was made against.

## 9. Error handling & edge cases

- Subprocess non-zero / traceback → captured stdout+stderr shown in the card's
  run log; card shows ✗; other views in the loop continue.
- `validate_result` exit 1 → view marked failed, deck not built.
- `build_deck_pptx` failure (e.g. a non-UC/CD view slips through) → deck marked
  unavailable, table/chart still delivered; never blocks the run.
- Schema drift (`validate_schema` exit 1) → banner; runs allowed but flagged.
- Concurrent run/simulate/reset → `409 busy`.
- Reset with no `data/_original/` backup → no-op with a clear message.
- A view whose `result.csv`/`run_meta.json` doesn't exist yet → card shows
  "never run".

## 10. Testing

`pytest` (backend):
- `GET /api/tables` returns the known min/max for the fixture CSVs and the
  correct grain string from each dictionary.
- snapshot diff: unchanged data → no "updated"; after simulate → "updated" with
  correct new max and stale-view count.
- simulate → reset round-trip restores both CSVs **byte-identical**.
- `POST /api/views/{id}/run` on a seeded view yields `result.csv` (rows > seed
  count after a simulate) and a `run_meta.json` with `data_max_at_run`.
- exit-code mapping: validate_result exit 2 is treated as pass.

Manual UI QA checklist: brand colors/fonts correct; greyed placeholders not
selectable; data-updated banner + acknowledge flow; stale flag appears after
simulate and clears after re-run; chart series/colors match `deck_spec.json`;
deck downloads and opens.

## 11. Build order (for the plan)

1. `seed_views.py` + `views.yaml` + plan normalization → two canonical folders.
2. `runner.py` (subprocess + lock + exit-code map) with tests.
3. `datasets.py` + `snapshot.py` + `/api/tables`, `/refresh-check`, `/acknowledge`.
4. `simulate.py` + `/simulate`, `/reset` with round-trip test.
5. `views.py` + `/api/views`, `/views/{id}/run`, `/result`, `/deck`.
6. `web/` page: datasets panel, data controls, views grid, result panel + SVG chart.
7. End-to-end manual QA pass + README run instructions.

## 12. Open risks (accepted)

- Simulated data is an approximation of a real refresh (clone+growth), adequate
  for demoing the "data updated → refresh" flow, not for analytical accuracy.
- The SVG chart is presentational (non-interactive) by choice.
- The deck builder remains UC/CD-specific; new non-UC/CD views would need builder
  work before their decks could be rebuilt from the dashboard.

# Design — Rename gastro universe + subset holdout to 700

Date: 2026-06-29
Branch: demo_v3
Status: approved (user, 2026-06-29)

## Goal

Two data-layer changes, propagated everywhere they are referenced, plus one
unrelated backup cleanup:

- **A. Rename** the gastro HCP universe dataset
  `sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl` → `Gastro_prod_sales_260605`.
- **B. Subset** `Holdout_HCP_Universe` from 1,040 ids → the **first 700 rows**.
- **E. Drop** the pre-perturb backup dirs (separate housekeeping).

Changes C (re-run historical output) and D (update published case-study) follow
from B because the subset invalidates the HCP counts those artifacts cite.

## Decisions (from brainstorming)

- New table name: `Gastro_prod_sales_260605`.
- Only the gastro universe is renamed; Weekly/Monthly/HCP_demographics keep names.
- Holdout selection: **first 700 rows** of the current file (arbitrary but reproducible).
- The internal key column `abv_customer_id` is **unchanged** — only the table renames.
- Historical run `run_2026-06-26_001` is corrected **in place** (same run_id), not re-issued as a new run.
- Backup cleanup: delete `data/_pre_perturb/` + root `_pre_perturb_backup/`; **keep** `data/_original/` so the simulate Reset button still restores Weekly/Monthly. Losing the true-original revert path is accepted.

## Key facts that shape the work

- `scripts/validate_schema.py` keys a dictionary by its YAML `table:` field and
  matches it to a CSV by file **stem**. It does **not** validate row counts. So:
  - The rename requires editing the `table:` field + renaming the CSV (and, by
    convention, the YAML file). 
  - The 700-subset needs **zero** dictionary edits to keep the gate green.
- **No server/dashboard Python references either dataset name literally.** Server
  reads `data/` and `metadata/` generically. No code edits for the rename except
  the historical run's `analysis_code.py`, which hardcodes the read path.
- The reset/backup machinery (`server/simulate.py`, `data/_original/`,
  `data/_pre_perturb/`, root `_pre_perturb_backup/`) only ever handles
  **Weekly + Monthly**. It never contains the gastro universe or the holdout, so
  the rename/subset do not interact with `/api/data/reset`.
- The published case-study is a **generated, gated** artifact: `_src.html` (source,
  hand-baked figures) → `scripts/build_walkthrough.py` (hard gates: segment counts
  sum to 1040, required-figure presence list, deck pinned to `FROZEN_SHA`/`FROZEN_LEN`)
  → `holdout-case-study.html` (output). Changing the numbers or the deck requires
  updating the source AND the gate constants together.

## Sequencing (hard dependencies)

Rename (A) → re-run (C, reads the new name + subset holdout) → rebuild deck (C3,
yields new SHA) → update `_src.html` figures + `build_walkthrough.py` gates/SHA (D) →
run `build_walkthrough.py` (D3). B precedes C (the re-run reads the 700-row holdout).
E is independent. Detailed task order belongs in the implementation plan.

## Change A — Rename gastro universe

`sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl` → `Gastro_prod_sales_260605`

1. `data/…_cl.csv` → `data/Gastro_prod_sales_260605.csv` (git mv).
2. `metadata/…_cl.yaml` → `metadata/Gastro_prod_sales_260605.yaml`; set
   `table: Gastro_prod_sales_260605` inside.
3. `metadata/relationships.yaml` — 2 join edges (`…_cl.abv_customer_id`, lines ~40 & ~49)
   + the prose block (lines ~26–31) → new name.
4. `metadata/HCP_demographics.yaml`, `metadata/Holdout_HCP_Universe.yaml` —
   prose cross-refs to the old name → new name.
5. `semantic/metrics.md`, `context.md`, `filters.md`, `time.md` — every mention → new name.
6. `MEMORY.md` — name everywhere.

Note: `gen_hcp_dict.py` (the scratch dict generator) is not committed / does not
hardcode the name in the grep — no edit needed, but if a fresh extract arrives the
regenerated dict must use the new `table:` value.

## Change B — Subset Holdout 1,040 → first 700

1. `data/Holdout_HCP_Universe.csv` — keep header + first 700 data rows; drop the rest.
2. **RULE-102 is no longer a no-op.** Edit `semantic/filters.md`: remove the
   "== universe, no-op today" wording; it now genuinely restricts HCP analyses to 700.
3. `metadata/Holdout_HCP_Universe.yaml` + `relationships.yaml` — remove the
   "identical 1,040-id set / 1:1 covers the universe" claims. Holdout is now a
   700 ⊂ 1,040 subset; edges remain 1:1 on matched ids but no longer cover the universe.
   **Keep the "same key value space" fact** (holdout ids are still a subset of the
   gastro/demographics id space; the key is join-compatible — only coverage shrank).
4. `MEMORY.md` — holdout = 700, RULE-102 real restriction.

## Change C — Re-run historical output `run_2026-06-26_001`

Numbers WILL change (population 1,040 → 700). `analysis_code.py` builds its spine
from `Holdout_HCP_Universe.csv` (line 51), so the result row count == holdout size
→ 700 rows, with new group/holdout counts.

1. `output/run_2026-06-26_001/analysis_code.py` — read path (line 16) → `Gastro_prod_sales_260605.csv`. (Holdout read path unchanged.)
2. Re-run the full workflow under the 700-holdout scope:
   regenerate `result.csv`, `analysis_plan.md` (tables list → new name; expected_row_count → 700), `takeaways.md`, `context.md`.
3. Rebuild `deck.pptx` via `scripts/build_deck_holdout.py` (chart_kind `holdout_segments`).
   **This changes the deck's SHA256 + byte length** — which Change D's build gate pins (see below).
4. `py -3 scripts/validate_result.py output/run_2026-06-26_001` must PASS.

Note: this run is NOT registered in `views.yaml` and has no `run_meta.json`, so no
dashboard-registration edits are needed.

## Change D — Update published case-study (gated, generated artifact)

`docs/walkthrough/holdout-case-study.html` is **generated** by
`scripts/build_walkthrough.py` from `docs/walkthrough/_src.html` — do NOT hand-edit
the generated file. The HCP figures are **hand-baked in `_src.html`** and the builder
enforces hard gates that refuse any other numbers. Steps:

1. **`docs/walkthrough/_src.html`** — re-narrate to the new 700-scope numbers from
   the re-run `result.csv`: the `<title>` ("670 or 43?"), `<meta description>`, hero,
   funnel nodes, section headers ("670 collapses to 43", "1,040 … Narrow to a 43-…"),
   aria-labels, group-count bars (627/367/26/17/3), holdout/non-holdout split
   (670/370), the "43" switch list, market-wide SKYRIZI vs STELARA totals + multiple,
   and the validation-lineage block (`expected_row_count`, `spine 1,040→1,040`,
   `result.csv (1,040 rows)`). Every figure is replaced with its 700-scope value.
2. **`scripts/build_walkthrough.py`** — rewrite the build gates to the new totals:
   - `segs` dict (line 45) + the `sum(...) != 1040` and `43 + 370 + 627 != 1040`
     asserts (lines 46–49) → new segment counts summing to **700**.
   - the required-figure presence list (line 51) → the new figure strings.
   - `FROZEN_SHA` + `FROZEN_LEN` (lines 19–20) → the rebuilt deck's new sha256 + length
     (update blob + hash together, as the gate message instructs).
3. Run `py -3 scripts/build_walkthrough.py` → regenerates `holdout-case-study.html`
   with the new figures and the re-embedded deck base64; all gates must pass.

Also: **`docs/metadata-onboarding-session-record.html`** — fix the single claim at
line ~223 ("all three sources cover the same ~1,040 prescribers") → the holdout is now
700 of the 1,040-prescriber universe. The ~1,040 *universe* mentions (lines ~159, ~186)
stay correct (the gastro universe is not subset).

## Change E — Drop pre-perturb backups (separate)

1. Delete `data/_pre_perturb/` and root `_pre_perturb_backup/`.
2. Keep `data/_original/` (simulate Reset path intact).
3. No `scripts/perturb_data.py` edit needed — its docstring stays accurate, and a
   future `--re-perturb` would just recreate `data/_pre_perturb/` on demand. Only the
   **MEMORY** revert/re-perturb note (which points at the root `_pre_perturb_backup/`
   as "true originals") goes stale → update it: the true-original revert path is gone (accepted).

## Verification

- `py -3 scripts/validate_schema.py` → ALL CLEAR, 5 active tables, new name present.
- `py -3 scripts/validate_result.py output/run_2026-06-26_001` → PASS.
- `py -3 scripts/build_walkthrough.py` → OK (all gates pass with the rewritten 700-scope constants + rebuilt-deck SHA).
- `py -3 -m pytest -q` → 66 pass / 6 known pre-existing failures, **no new failures**.
- Each `/semantic/` + `/metadata/` change committed separately
  (`rule:` for semantic-rule edits; descriptive message for renames).

## Out of scope

- `.playwright-mcp/*`, `scratch_final_plan.md` — throwaway, untouched.
- `_reference/` — skipped per CLAUDE.md.
- No changes to Weekly/Monthly data, server code, transport/chat layer, or tests.

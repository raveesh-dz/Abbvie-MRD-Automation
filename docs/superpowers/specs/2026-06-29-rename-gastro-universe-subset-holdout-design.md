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
4. `MEMORY.md` — holdout = 700, RULE-102 real restriction.

## Change C — Re-run historical output `run_2026-06-26_001`

Numbers WILL change (population 1,040 → 700).

1. `output/run_2026-06-26_001/analysis_code.py` — read path → `Gastro_prod_sales_260605.csv`.
2. Re-run the full workflow under the 700-holdout scope:
   regenerate `result.csv`, `analysis_plan.md` (expected_row_count), `takeaways.md`, `context.md`.
3. Rebuild `deck.pptx` via `scripts/build_deck_holdout.py` (chart_kind `holdout_segments`).
4. `py -3 scripts/validate_result.py output/run_2026-06-26_001` must PASS.

## Change D — Update published case-study

`docs/walkthrough/holdout-case-study.html` (+ `_src.html`) — refresh every HCP
figure (the 1,040 / 670 / 43 / market-wide counts) from the new 700-scope `result.csv`.

## Change E — Drop pre-perturb backups (separate)

1. Delete `data/_pre_perturb/` and root `_pre_perturb_backup/`.
2. Keep `data/_original/` (simulate Reset path intact).
3. Update `scripts/perturb_data.py` docstring (the `_pre_perturb` backup line) and
   the MEMORY revert note — the true-original revert path is gone (accepted).

## Verification

- `py -3 scripts/validate_schema.py` → ALL CLEAR, 5 active tables, new name present.
- `py -3 scripts/validate_result.py output/run_2026-06-26_001` → PASS.
- `py -3 -m pytest -q` → 66 pass / 6 known pre-existing failures, **no new failures**.
- Each `/semantic/` + `/metadata/` change committed separately
  (`rule:` for semantic-rule edits; descriptive message for renames).

## Out of scope

- `.playwright-mcp/*`, `scratch_final_plan.md` — throwaway, untouched.
- `_reference/` — skipped per CLAUDE.md.
- No changes to Weekly/Monthly data, server code, transport/chat layer, or tests.

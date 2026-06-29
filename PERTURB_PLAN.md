# Data Perturbation + Full Re-run — Plan

**Goal:** Randomly perturb every TRx value in both datasets by ±7%, then regenerate all 8 output runs (data, result tables, insights, decks) so the numbers AND the narratives change — without breaking the schema gate, the active analyses, or producing negative TRx.

---

## Decisions locked (from you)
1. **Magnitude:** each value × a random factor uniform in **[0.93, 1.07]** (±7%, per cell, independent).
2. **Aggregates:** recompute rollups where feasible so totals stay consistent; where the hierarchy is undeclared, leave it (accept inconsistency) and flag.
3. **Scope:** all 8 output folders.
4. **Decks:** rebuild all.
5. **Non-negative:** TRx may never go negative. (See zero-handling note below.)

---

## 1. Perturbation spec
- **Columns touched:** `Weekly_Data_Tabular.TRX_ADJUSTED` and `Monthly_Data_Tabular.TRX_VOLUME` only. Dates, PRODUCT, INDICATION, ROW_TYPE, flags, METRIC, MARKET — all untouched.
- **Factor:** `v_new = v_old * U(0.93, 1.07)`, drawn independently per cell.
- **Determinism:** fixed RNG seed (default `20260610`) → fully reproducible and auditable. Seed recorded in script + MEMORY.
- **Non-negative guarantee:** factor is always positive and `v_old ≥ 0`, so `v_new ≥ 0` automatically; a defensive `max(v_new, 0)` is applied anyway.
- **Zero handling:** values that are exactly `0.0` today (e.g. OLUMIANT, SILIQ, SOTYKTU in some weeks) **stay 0.0**. Multiplicative perturbation can't lift a 0 without inventing dispensing that never happened. So "always > 0" holds for all *real* volume; genuine zeros remain zero. **Flag if you want zeros forced to a small positive — that would fabricate data, not recommended.**

## 2. Data-layer changes — what's preserved vs not

### Weekly — rollups RECOMPUTED (totals stay consistent) ✅
Verified structure (week 2026-05-08, will re-verify every week in-script):
- `MARKET_TOTAL` (1 row/week, "SI Market + Oral", flag N) **= Σ all flag-N PRODUCT rows**.
- `Total Non-Approved Volume` (flag-N PRODUCT row) **= Σ all flag-Y PRODUCT rows**.
- Biosimilar TOTAL lines (`STELARA BIOSIMILARS TOTAL SQ`, `ACTEMRA BIOSIMILARS SQ TOTAL`) and `ADALIMUMAB` have **no component rows present in the weekly file** → treated as leaves.

Procedure per week:
1. Perturb every PRODUCT row EXCEPT `Total Non-Approved Volume` and the `MARKET_TOTAL` row.
2. Recompute `Total Non-Approved Volume` = Σ(perturbed flag-Y rows).
3. Recompute `MARKET_TOTAL` = Σ(perturbed flag-N PRODUCT rows, incl. recomputed Total Non-Approved Volume).
4. **Guard:** before recomputing, assert the identity already holds on the original data (tolerance 0.5%). If a week fails the assert, that week is perturbed leaf-only and logged — no silently-wrong total.

### Monthly — rollups NOT recomputed (declared infeasible) ⚠️
Probed: `MARKET_TOTAL` per indication ≠ Σ PRODUCT/N rows (UC: 213,029 vs 316,021). The monthly file mixes brand `(Total)` lines (`SIMPONI (Total)`, `Stelara (Total)`…), dose-level leaves (RINVOQ 15/30/45MG…), biosimilar TOTALs, `Total PsA`, and `Total Non-Approved Volume` in one `PRODUCT` set, with per-indication `MARKET_TOTAL` rows that sum a curated subset — **none of which is declared anywhere** (RULE-003 only maps weekly→monthly brands, not the monthly internal tree). Reverse-engineering it risks silently-wrong totals.
- **Approach:** perturb **all** monthly numeric rows independently (leaves + rollups).
- **Consequence:** monthly internal identities (MARKET_TOTAL, brand `(Total)`, `Total PsA`, biosimilar TOTALs, `Total Non-Approved Volume`) will NOT equal the sum of their children after perturbation.
- **Why this is acceptable:** all 8 current analyses read monthly ONLY at PRODUCT grain for the UC:CD ratio (RULE-004), filtered to a named product + {UC, CD}, `ROW_TYPE=PRODUCT`. None read any monthly rollup row. So **no active output breaks.** Only *future* market-share/total queries (pending rules MEMORY #1–2) would be affected — they're undefined today anyway.
- Documented loudly in MEMORY + a note in the perturb script output.

## 3. Backups & reversibility
- `data/_original/` (true pre-refresh source) — **never touched.**
- Before writing: copy current CSVs → **`data/_pre_perturb/`** (new).
- Each run's current `result.csv` → snapshot to `result_prev.csv` in that folder before overwrite (matches the existing dashboard convention; named views already have it).
- Seed + `data/_pre_perturb/` ⇒ the whole operation is reversible and reproducible.

## 4. Re-run cascade (per output folder)
8 folders: `run_2026-06-04_002/_003`, `run_2026-06-08_001/_002`, `run_2026-06-10_001/_002`, `skyrizi_ibd_split`, `tremfya_ibd_split`.

Per folder:
1. `py -3 analysis_code.py` → regenerate `result.csv` (reads perturbed `/data/`).
2. `py -3 scripts/validate_result.py <folder>` → must PASS.
3. **Regenerate insights:** rewrite `context.md` (headline, freshness) and `takeaways.md` (2–4 takeaways) from the NEW `result.csv`. This is where "insights change" — done by the engine per the CLAUDE.md Step-6 templates, every claim traced to a new number.
4. **Rebuild deck** (folders with a `deck_spec.json` — 7 of 8; `run_2026-06-10_001` has none, build_deck was false → skip):
   - `chart_kind == "wow_compare"` → `py -3 scripts/build_deck_wow.py <folder>` (only `run_2026-06-10_002`).
   - else (line/series spec) → `py -3 scripts/build_deck_pptx.py <folder>` (other 6).
   - Spec-driven titles/deks recompute from `result.csv` at build time → auto-update. Any literal-fallback spec gets its `statement_title`/`dek`/`blocks` refreshed so chart and prose agree.
   - Structural QA per deck: chart series trace to `result.csv`, no mojibake, integrity sanitizer + round-trip PASS. Visual render skipped (no LibreOffice).
5. Update `run_meta.json` (last_run_at, data_max_at_run, validation_status, row_count, deck_available).
6. Named views (`skyrizi_ibd_split`, `tremfya_ibd_split`): roll `result.csv`→`result_prev.csv` and append `run_history.json` per their convention.

## 5. Post-run housekeeping
- `py -3 scripts/validate_schema.py` after perturb → expect ALL CLEAR (floats stay floats, headers unchanged).
- Update `MEMORY.md`: data perturbed (seed, date, ±7%), weekly rollups recomputed, monthly identities NOT preserved, all prior hardcoded result numbers superseded, new per-run figures recorded.
- `views.yaml` descriptions: refresh any embedded figures/date ranges if present.
- Leave git to you (no auto-commit; CLAUDE.md commit rule is scoped to semantic/metadata, which this doesn't touch).

## 6. New artifact
- `scripts/perturb_data.py` — `--seed`, `--low 0.93`, `--high 1.07`; backs up to `_pre_perturb/`, perturbs, recomputes weekly rollups with the guard, prints an audit report (rows changed, identity checks, min value to confirm none ≤ 0 among real volume). Re-runnable/reversible.

---

## What breaks / what's safe (explicit)
| Area | Verdict |
|---|---|
| Schema gate | ✅ safe (no header/dtype change) |
| `validate_result.py` on all 8 runs | ✅ safe (row/null checks; recompute clean) |
| 8 active analyses (PRODUCT-grain UC/CD) | ✅ safe |
| Weekly MARKET_TOTAL / Total Non-Approved identities | ✅ preserved (recomputed) |
| Monthly MARKET_TOTAL / (Total) / Total PsA / biosimilar TOTALs | ⚠️ NOT preserved (undeclared hierarchy) — no active output uses them |
| Negative TRx | ✅ impossible by construction |
| Existing exact-zero values | stay 0.0 (not fabricated) |
| Insight text / literal deck titles | regenerated by engine (not automatic) — handled in cascade |
| MEMORY hardcoded numbers | superseded → updated |
| Reversibility | ✅ `_pre_perturb/` + seed |

## Order of operations
1. Write `scripts/perturb_data.py`.
2. Back up → perturb → recompute weekly rollups → audit report.
3. `validate_schema.py` (gate).
4. For each of 8 folders: rerun code → validate → regen insights → rebuild deck → QA → update run_meta.
5. Update MEMORY + views.yaml.
6. Report: per-run before/after headline, deck status, what changed.

## Self-review notes
- **Biggest risk = monthly hierarchy.** Mitigated by NOT faking a recompute; the asymmetry (weekly consistent, monthly not) is deliberate and documented, and provably harmless to current outputs because they never read monthly rollup rows.
- **Weekly recompute guarded** by a pre-existing-identity assert per week → won't emit a wrong total if some week's structure differs from the 2026-05-08 sample.
- **Determinism** via seed so a re-run reproduces byte-identical data; analyses are already standalone so re-runs are clean.
- **"insights change" is manual narrative work** on 8 folders (context + takeaways + some deck titles) — the slow part, but it's the actual deliverable, not a side effect.
- **Open question for you:** force exact zeros to a small positive (fabricates volume) or leave them at 0.0? Recommend leave.

# Analysis Plan — run_2026-06-26_001
query: "For each doctor, have they shifted their new prescribing for Crohn's Disease from STELARA over to SKYRIZI? NBRx only, CD indication, most recent 13 weeks. Per HCP compute STELARA-to-SKYRIZI NBRx ratio (threshold 0.5) and classify Holdout vs Non-Holdout. Keep all computation columns."
base_plan: none
tables:
  - Gastro_prod_sales_260605 (gastro HCP universe, NBRx slices)
  - Holdout_HCP_Universe (scope membership, RULE-102)
joins:
  - Holdout_HCP_Universe.abbott_customer_id → Gastro_prod_sales_260605.abv_customer_id (one-to-one, per relationships.yaml) — used ONLY to restrict to the in-scope HCP universe (RULE-102). No-op today (id sets identical). No demographics join (enrichment off, user choice).
filters_applied:
  - data_type == 'NBRx' (RULE-005: NBRx is stored, selected by filter — not computed)
  - indication_code == 'CD'
  - product_brand == 'SKYRIZI'  (SKYRIZI OBI / SC maintenance only — user choice; EXCLUDES SKYRIZI_IV)
  - product_brand == 'STELARA'  (plain STELARA brand only — user choice; EXCLUDES STELARA_IV, USTEKINUMAB, ustekinumab biosimilars)
  - RULE-102: restrict to Holdout_HCP_Universe membership (authoritative scope)
  - RULE-101 not applicable (SKYRIZI/STELARA are brand labels, not class rollups)
metrics:
  - skyrizi_cd_nbrx_13wk = sum(frx1..frx13) for SKYRIZI CD NBRx rows, per HCP (RULE-006 frx positional, RULE-007 cur_13wk = Σfrx1..13)
  - stelara_cd_nbrx_13wk = sum(frx1..frx13) for STELARA CD NBRx rows, per HCP
  - stelara_to_skyrizi_ratio = stelara_cd_nbrx_13wk / skyrizi_cd_nbrx_13wk  (defined only when skyrizi > 0). Emitted as a STRING display column, fully populated: the rounded number (4dp) when skyrizi>0; "undefined_stelara_only" when skyrizi==0 & stelara>0 (no denominator); "undefined_no_cd_nbrx" when both==0 (0/0). String, not numeric, so the undefined-by-design rows carry no ambiguous numeric nulls.
time_window: cur_13wk = frx1..frx13. frx1 = week ending 2026-06-05 (anchor, RULE-401), frx13 = week ending 2026-03-13. Most recent 13 complete weeks. Latest week is complete, not provisional (RULE-401).
output_grain: full grain — one row per HCP (abbott_customer_id) across the full holdout universe (1,040 HCPs), including doctors with no CD NBRx at all. 1,040 rows is intended (not a slide-size violation).
classification (RULE-010, new this run):
  - no_cd_nbrx        : SKY==0 AND STEL==0            -> Holdout
  - stelara_only      : STEL>0  AND SKY==0            -> Holdout
  - both_lean_stelara : SKY>0 AND STEL>0 AND ratio>=0.5 -> Holdout
  - both_lean_skyrizi : SKY>0 AND STEL>0 AND ratio<0.5  -> Non-Holdout
  - skyrizi_only      : STEL==0 AND SKY>0             -> Non-Holdout
  Holdout = has NOT moved to SKYRIZI (conversion target). Non-Holdout = SKYRIZI wins new prescribing (retention).
assumptions:
  - 13-week window = cur_13wk (RULE-401 documented default for this table). (user confirmed)
  - SKYRIZI scope = SKYRIZI label only, SKYRIZI_IV excluded. (user confirmed)
  - STELARA scope = STELARA label only, STELARA_IV + ustekinumab molecule/biosimilars excluded. (user confirmed)
  - Universe = full 1,040-HCP holdout universe incl. zero-CD doctors; one row each. (user confirmed)
  - "No CD NBRx" boundary = 13wk sum exactly == 0. (default applied)
  - ratio threshold boundary: exactly 0.5 -> Holdout (>= 0.5). (user spec)
  - Output = computation columns only, no targeting/geo enrichment. (user confirmed)
analysis_type: drill_down (segmentation / classification snapshot)
expected_row_count: 1040

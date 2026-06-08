# Analysis Plan — run_2026-06-04_002
query: "I want weekly tremfya TRx split by indications for Gastrointestinal market aka IBD market"
base_plan: none
tables: Weekly_Data_Tabular, Monthly_Data_Tabular
joins:
  - Weekly_Data_Tabular.PRODUCT + month(WEEK_ENDING) → Monthly_Data_Tabular.PRODUCT + MONTH_DATE (many-to-one, allocation edge, per relationships.yaml)

## Scope
- The weekly "SI Market + Oral" panel is IBD-only (RULE-301), so the full weekly TREMFYA total is IBD volume and is split across the IBD indications: **UC + CD**.
- Per RULE-004, the full weekly total is renormalised across {UC, CD}, so UC + CD = TREMFYA_TRx_total every week that has IBD volume.

## Method (RULE-004, revised 2026-06-04 — renormalise within reported set)
1. RULE-003 crosswalk: weekly TREMFYA → monthly TREMFYA SQ 100MG + 200MG + INDUCTION.
2. Monthly UC and CD TRx → renormalised shares within {UC, CD} (sum to 1.0 per month).
3. Each week assigned to its WEEK_ENDING calendar month; weeks past 2026-04-01 carry forward the April 2026 mix.
4. Weekly total × renormalised UC/CD share → UC and CD columns. They sum back to the weekly total.

metrics:
  - RULE-003 (crosswalk): weekly TREMFYA → monthly SQ dose rows
  - RULE-004 (revised): weekly total × renormalised monthly UC / CD share
time_window: 2024-05-03 to 2026-05-08 (full series, 106 weeks). Anchor = 2026-05-08.
output_grain: one row per week; columns UC, CD, TREMFYA_TRx_total — full grain (trend)
assumptions:
  - IBD / GI market = {UC, CD} — the only gastrointestinal indications present (user request)
  - The ENTIRE weekly total is attributed to UC + CD (renormalise-within-set, RULE-004). This is correct because the weekly panel is IBD-only (RULE-301, user confirmed), so the full weekly total is genuinely IBD volume. (user confirmed the renormalise method with a worked example)
  - Allocated values are ESTIMATES (monthly ratio applied to weekly totals), not measured weekly IBD counts
analysis_type: trend
expected_row_count: 106

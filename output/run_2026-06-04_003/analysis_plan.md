# Analysis Plan — run_2026-06-04_003
query: "I want weekly tremfya TRx split by indication fo IBD market"
base_plan: none
tables: Weekly_Data_Tabular, Monthly_Data_Tabular
joins:
  - Weekly_Data_Tabular.PRODUCT + month(WEEK_ENDING) → Monthly_Data_Tabular.PRODUCT + MONTH_DATE (many-to-one, allocation edge, per relationships.yaml)

## Scope
- The weekly "SI Market + Oral" panel is IBD-only (RULE-301), so the full weekly TREMFYA total is IBD volume and is split across the IBD indications: **UC + CD**.
- Per RULE-004, the full weekly total is renormalised across {UC, CD}, so UC + CD = TREMFYA_TRx_total every week that has IBD volume.

## Method (RULE-004 — renormalise within reported set)
1. RULE-003 crosswalk: weekly TREMFYA → monthly TREMFYA SQ 100MG + 200MG + INDUCTION (SQ only).
2. Monthly UC and CD TRx → renormalised shares within {UC, CD} (sum to 1.0 per month).
3. Each week assigned to its WEEK_ENDING calendar month; weeks past 2026-04-01 carry forward the April 2026 mix.
4. Weekly total × renormalised UC/CD share → UC and CD columns. They sum back to the weekly total.

filters_applied: none (semantic/filters.md empty); ROW_TYPE = PRODUCT rows only in both tables
metrics:
  - RULE-003 (crosswalk): weekly TREMFYA → monthly SQ dose rows
  - RULE-004: weekly total × renormalised monthly UC / CD share
time_window: 2024-05-03 to 2026-07-03 (full available weekly series, 114 weeks). Anchor = 2026-07-03.
output_grain: one row per week; columns UC, CD, TREMFYA_TRx_total — full grain (trend)
assumptions:
  - IBD / GI market = {UC, CD} — the only gastrointestinal indications present (RULE-301)
  - The full weekly total is attributed to UC + CD because the weekly panel is IBD-only (RULE-301)
  - Allocated values are ESTIMATES (monthly UC:CD ratio applied to weekly totals), not measured weekly IBD counts
analysis_type: trend
expected_row_count: 114

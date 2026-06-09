# Analysis Plan — run_2026-06-08_002
query: "skyrizi TRx split by indication for gastrointestinal market aka IBD market"
base_plan: run_2026-06-04_003 (Tremfya IBD split — same method, brand swapped to SKYRIZI)
tables: Weekly_Data_Tabular, Monthly_Data_Tabular
joins:
  - Weekly_Data_Tabular.PRODUCT + month(WEEK_ENDING) → Monthly_Data_Tabular.PRODUCT + MONTH_DATE (many-to-one, allocation edge only, per relationships.yaml)
filters_applied:
  - ROW_TYPE = PRODUCT on both tables (never MARKET_TOTAL) — per RULE-003/RULE-004
  - (no standing filters defined in semantic/filters.md)
metrics:
  - RULE-003: "Skyrizi" taken as the COMBINED entity — weekly SKYRIZI + SKYRIZI OBI lines summed; monthly crosswalk = SKYRIZI SQ + SKYRIZI IV + SKYRIZI OBI rolled up for the indication mix
  - RULE-004: indication allocation, renormalise-within-reported-set — full combined weekly total split across {UC, CD}
context:
  - RULE-301: weekly panel is IBD-only, so the full weekly Skyrizi total is genuinely IBD volume (UC+CD), not an overstatement
time_window: 2024-05-03 → 2026-05-08 (full available weekly range, 106 weeks). No window stated; no documented default exists (MEMORY pending #4) so full range used, matching prior runs. Anchor/latest week = 2026-05-08.
output_grain: one row per WEEK_ENDING, columns UC, CD, and SKYRIZI_TRx_total (reconciliation). FULL GRAIN (trend) — 106 weekly rows by design, not top-N.
assumptions:
  - "Skyrizi" = SKYRIZI + SKYRIZI OBI combined (user confirmed 2026-06-08, after surfacing that OBI is ~99.9% of Skyrizi's IBD volume; initial ask was OBI-excluded but reversed once magnitude was shown)
  - IBD market = {UC, CD} only; full combined weekly total distributed across them (user confirmed)
  - Full weekly date range, no window filter (user confirmed)
  - Weeks past 2026-04-01 carry forward April-2026 mix; weeks before Skyrizi has UC/CD monthly volume show 0 (default applied, per RULE-004)
analysis_type: trend
expected_row_count: full grain — one row per WEEK_ENDING (grows with data)

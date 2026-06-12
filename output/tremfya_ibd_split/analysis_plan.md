# Analysis Plan — run_2026-06-08_001
query: "weekly tremfya trx split by indication for gastrointestinal market aka IBD market"
base_plan: none (standalone; same method as run_2026-06-04_003)
tables: Weekly_Data_Tabular, Monthly_Data_Tabular
joins:
  - Weekly_Data_Tabular.PRODUCT + month(WEEK_ENDING) → Monthly_Data_Tabular.PRODUCT + MONTH_DATE (many-to-one, per relationships.yaml — allocation edge ONLY; borrows the unitless monthly indication mix, never compares TRX_ADJUSTED to TRX_VOLUME)
filters_applied:
  - ROW_TYPE = PRODUCT on both tables (exclude MARKET_TOTAL / Total Non-Approved rollups — dictionary traps)
  - Weekly: PRODUCT = TREMFYA only
  - Monthly: PRODUCT in TREMFYA SQ {100MG, 200MG, INDUCTION} (RULE-003 crosswalk, SQ only; IV excluded — weekly TREMFYA line is SQ)
  - Monthly: INDICATION in {UC, CD} (the IBD reported set)
metrics:
  - RULE-003 — Weekly→Monthly brand crosswalk (roll TREMFYA SQ dose rows up to brand)
  - RULE-004 — Indication allocation, renormalise-within-reported-set (shares sum to 1.0; full weekly total distributed across UC/CD)
time_window: full available weekly panel, 2024-05-03 → 2026-07-03 (anchor = latest week 2026-07-03). No window stated; weekly time default is still undefined (MEMORY pending #4), so full history is reported rather than truncating to an unconfirmed default.
output_grain: one row per WEEK_ENDING, columns UC, CD, TREMFYA_TRx_total
assumptions:
  - Weekly panel is IBD-only, so the entire weekly TREMFYA total is genuinely IBD volume and is split across {UC, CD} only (RULE-301, user confirmed)
  - Renormalise-within-reported-set allocation: UC + CD reconcile to the weekly total (RULE-004, user confirmed)
  - Weeks after the last monthly month (2026-04-01) carry forward the April 2026 UC:CD mix (RULE-004, default applied, not user-confirmed)
analysis_type: trend
expected_row_count: full grain — one row per WEEK_ENDING (grows with data)

# Analysis Plan — run_2026-06-10_001
query: "I need Monthly Trx Humira split by Indication for the latest 6 months"
base_plan: none
tables: Monthly_Data_Tabular
joins:
  - none (single-table analysis; no edge needed)
filters_applied:
  - PRODUCT = "HUMIRA (Including Citrate Free)" (the only Humira label in the table; adalimumab biosimilars are separate products and excluded)
  - ROW_TYPE = PRODUCT (never MARKET_TOTAL — dictionary known-issue: double counting)
  - INDICATION != "Total PsA" (rollup of PsA (Derm) + PsA (Rheum); excluding it avoids double counting, per the RULE-004 convention)
  - MONTH_DATE in latest 6 data months: 2025-12-01 .. 2026-05-01
metrics: TRX_VOLUME (adjusted monthly TRx, as-is from source; no derived metrics)
time_window: 2025-12-01 to 2026-05-01 (latest 6 months present in Monthly_Data_Tabular; anchor = max(MONTH_DATE) = 2026-05-01)
output_grain: one row per month, one column per indication (10 indications: AS, CD, GCA, HS, Ps, PsA (Derm), PsA (Rheum), RA / JIA, UC, UVEITIS)
assumptions:
  - "latest 6 months" = the 6 most recent months in the data (2025-12 .. 2026-05) (default applied, not user-confirmed)
  - Humira = brand only, "HUMIRA (Including Citrate Free)"; biosimilars excluded (default applied, not user-confirmed)
  - Total PsA rollup excluded; PsA shown as Derm + Rheum separately (default applied, not user-confirmed)
  - GCA kept although NON_APPROVED_FLAG = Y for Humira there (volume is tiny, ~113/month); flagged in caveats (default applied, not user-confirmed)
  - NO row-total column: indication markets overlap, volumes are not additive across indications (dictionary known-issue)
analysis_type: trend
expected_row_count: 6

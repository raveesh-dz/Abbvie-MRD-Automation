# Analysis Plan — run_2026-06-04_001
query: "How is PRODUCT_A share trending recently by specialty?"
base_plan: none
tables: rx_transactions, hcp_master
joins:
  - rx_transactions → hcp_master on hcp_id (inner, per relationships.yaml)
filters_applied: RULE-102 (drop 2 provisional weeks)
metrics: market share per RULE-002 (basket = PRODUCT_A + COMPETITOR_X)
time_window: R13W per RULE-202 default; anchor 2026-05-02 per RULE-201; 2026-01-31 to 2026-05-02
output_grain: one row per week per specialty
assumptions:
  - "recently" resolved to R13W (default applied, not user-confirmed)
analysis_type: trend
expected_row_count: 26

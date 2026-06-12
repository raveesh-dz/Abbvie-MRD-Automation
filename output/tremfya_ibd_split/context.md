# Context - tremfya_ibd_split
headline: Tremfya's IBD mix is a tight race - CD 4,468 TRx (54.3%) vs UC 3,761 (45.7%) in the latest week (2026-08-28), with the weekly lead alternating rather than settled.
methodology: Weekly Tremfya TRx (IBD-only panel, RULE-301) split across {UC, CD} using the national monthly UC:CD mix renormalised within the set (RULE-004); weekly Tremfya line matched 1:1 to monthly (RULE-003). Full weekly series, one row per WEEK_ENDING.
filters_applied: PRODUCT rows only (MARKET_TOTAL / Non-Approved excluded). No standing filters.
time_period: 2024-05-03 -> 2026-08-28 (122 weeks, full available panel).
data_freshness: latest weekly WEEK_ENDING = 2026-08-28; weeks past the latest monthly mix carry it forward.
caveats: DEMO DATA - weeks after 2026-05-08 are simulated periods, and all values (weekly and monthly) carry a deliberate ±50% random perturbation (seed 42). Indication splits are model estimates (national mix applied to an IBD-only panel), not a claims census. Restore data/_pre_perturb and data/_original for production numbers.

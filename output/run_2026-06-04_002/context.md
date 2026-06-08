# Context — run_2026-06-04_002
headline: With TREMFYA's full weekly total attributed to IBD and split by the monthly UC:CD ratio, Crohn's now leads ulcerative colitis (CD ~3,905 vs UC ~3,121 on 2026-05-08), having overtaken UC during 2025.
methodology: The weekly "SI Market + Oral" panel is IBD-only (RULE-301), so TREMFYA's weekly total is its IBD TRx. Each week's total (TRX_ADJUSTED, SQ doses per RULE-003) is split into UC and CD using the national monthly UC:CD ratio (RULE-004), renormalised within {UC, CD} so the two columns sum to the full weekly total.
filters_applied: ROW_TYPE = PRODUCT rows only; reported indications = UC + CD; the monthly ratio uses TREMFYA SQ dose rows rolled up per RULE-003.
time_period: 2024-05-03 to 2026-05-08 (full available weekly series, 106 weeks). Anchor = 2026-05-08.
data_freshness: Latest week_ending = 2026-05-08. No provisional weeks excluded. May 2026 weeks reuse the carried-forward April 2026 UC:CD ratio.
caveats:
  - The weekly "SI Market + Oral" panel is IBD-only (RULE-301), so the full weekly total IS IBD volume. Attributing all of it to UC + CD is correct, not an overstatement; TREMFYA_TRx_total = the weekly IBD TRx and UC + CD reconcile to it.
  - The UC:CD ratio comes from the national Monthly table (the only source of the indication split); the weekly LEVEL is the panel's own IBD TRx. So the level is measured IBD volume; the UC-vs-CD division is an estimate from the monthly ratio.
  - May 2026 weeks reuse the April 2026 UC:CD ratio (carry-forward).

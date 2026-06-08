# Business Context & Known Patterns
<!-- Used to EXPLAIN results in takeaways, never to alter numbers. -->

## RULE-301: Weekly panel is IBD-only
- applies_to: Weekly_Data_Tabular
- category: context
- definition: The weekly "SI Market + Oral" panel covers the IBD / gastrointestinal market only. A product's weekly TRx here is its IBD usage (UC + CD), even for products that are also used in dermatology or rheumatology nationally. Therefore a weekly total, when split by indication via RULE-004, should be distributed across the IBD indications {UC, CD} only — the full weekly total is genuinely IBD, so attributing all of it to UC/CD is correct, not an overstatement.
- formula: n/a
- caveats: This does NOT apply to the Monthly table, which is national and spans all 11 indications. The monthly mix is used only to derive the UC:CD ratio applied to the weekly IBD total.
- provenance: auto-saved | 2026-06-04 | R | run_id=run_2026-06-04_002

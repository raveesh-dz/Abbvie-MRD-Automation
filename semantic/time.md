# Time Intelligence Rules
<!-- Date logic is the #1 source of silent analytics errors. These rules are
     consumed during query parsing. -->

## RULE-401: frx* weekly anchor, date map, and default window
- applies_to: sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl (frx1 .. frx399, cur_/pre_*wk)
- category: time
- definition: >
    The frx* series has no date column — dates are POSITIONAL and anchored to the
    file's YYMMDD stamp:
      - frx1  = most recent week = week ending 2026-06-05 (Friday).
      - frxN  = week ending 2026-06-05 - (N-1) weeks.
      - frx106 = 2024-05-31, frx399 = 2018-10-19 (oldest).
    DEFAULT analysis window when a query for this table states no time frame:
    the latest 13 weeks (cur_13wk = sum(frx1..frx13), ending 2026-06-05). Record this
    as an assumption in the analysis plan. For period-over-period, the default
    comparison is cur_13wk vs pre_13wk (RULE-007).
- formula: "week_ending(frxN) = date(2026-06-05) - (N-1)*7 days"
- caveats: >
    The anchor is extract-specific: a future re-extract re-anchors frx1 to that
    file's stamp. The latest week (frx1, w/e 2026-06-05) is COMPLETE, not provisional
    (user-confirmed 2026-06-26) — no latest-week exclusion or incompleteness caveat
    applies. Weekly Friday convention matches the Weekly_Data_Tabular table.
- provenance: auto-saved | 2026-06-26 | R | run_id=discussion

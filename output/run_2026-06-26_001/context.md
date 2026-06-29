# Context — run_2026-06-26_001
headline: 456 of 700 gastro HCPs (65%) are SKYRIZI Holdouts for Crohn's new prescribing — but 426 of those simply wrote no CD NBRx in the last 13 weeks; only 30 active prescribers are still defaulting to STELARA.
methodology: For each HCP in the 700-HCP holdout universe we summed SKYRIZI and STELARA Crohn's-Disease NBRx over the most recent 13 weeks (cur_13wk = frx1..frx13, week ending 2026-06-05 back to 2026-03-13). We divided STELARA NBRx by SKYRIZI NBRx; a ratio ≥ 0.5 (STELARA at least half of SKYRIZI) or any HCP with zero SKYRIZI is a Holdout (not yet moved to SKYRIZI); SKYRIZI-only or ratio < 0.5 is a Non-Holdout (SKYRIZI wins new prescribing). NBRx values are stored and selected by filter, never computed (RULE-005); all sums/ratios run in pandas.
filters_applied: data_type = NBRx; indication_code = CD (Crohn's); product_brand exactly SKYRIZI (OBI/SC maintenance, excludes SKYRIZI_IV) and exactly STELARA (excludes STELARA_IV, plain ustekinumab, and ustekinumab biosimilars); restricted to the 700-HCP holdout universe (RULE-102).
time_period: most recent 13 weeks — week ending 2026-06-05 (frx1) through week ending 2026-03-13 (frx13).
data_freshness: latest week (frx1, w/e 2026-06-05) is complete, not provisional (RULE-401).
caveats: >
  - Ratio is undefined when an HCP has zero SKYRIZI NBRx (denominator 0); those HCPs are
    classified directly by the zero-SKYRIZI rule and the ratio column shows
    "undefined_stelara_only" (STELARA but no SKYRIZI) or "undefined_no_cd_nbrx" (neither).
  - "Holdout" mixes two very different populations: 426 silent HCPs with NO CD NBRx at all
    (no recent new Crohn's starts to convert) and 30 active prescribers still writing STELARA.
    Conversion effort should separate these — the 30 active STELARA-leaners are the true switch
    targets; the 426 silent HCPs are an activation / opportunity-sizing question, not a switch.
  - Brand scope is the SKYRIZI and STELARA brand labels only. A doctor moving STELARA new
    starts to a ustekinumab biosimilar (not SKYRIZI) would here read as reduced STELARA, not
    as a SKYRIZI shift — biosimilar diversion is out of scope by the chosen brand definition.
  - Classification is on NBRx (new starts) only; it deliberately ignores the existing TRx book.

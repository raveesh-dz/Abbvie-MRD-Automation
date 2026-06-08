# Metric Definitions
<!-- How every number is calculated. One rule per metric. -->

## RULE-003: Weekly→Monthly brand crosswalk
- applies_to: Weekly_Data_Tabular.PRODUCT, Monthly_Data_Tabular.PRODUCT
- category: metric
- definition: >
    Weekly carries a brand as a single (often form-specific) line; Monthly splits
    the same brand by dose/form. To borrow Monthly's indication mix (RULE-004) the
    Monthly rows must be rolled up to the Weekly brand label, matching FORM and
    never folding IV into an SQ line. Brands whose labels match case-insensitively
    map 1:1 (e.g. Weekly "ACTEMRA SQ" → Monthly "Actemra SQ"). The non-trivial maps:
      - RINVOQ                       → RINVOQ 15MG + RINVOQ 30MG + RINVOQ 45MG
      - OMVOH SQ                     → OMVOH SQ (100MG + 100MG) + OMVOH SQ (200MG + 100MG)
      - TREMFYA                      → TREMFYA SQ 100MG + TREMFYA SQ 200MG + TREMFYA SQ INDUCTION
      - SKYRIZI                      → SKYRIZI SQ + SKYRIZI IV
      - SKYRIZI OBI                  → SKYRIZI OBI
      - SIMPONI SC                   → Simponi SQ
      - ACTEMRA BIOSIMILARS SQ TOTAL → AVTOZMA SQ + TYENNE SQ
- formula: >
    monthly_brand = monthly[monthly.PRODUCT.isin(CROSSWALK[weekly_brand])]
                       .groupby(['INDICATION','MONTH_DATE'])['TRX_VOLUME'].sum()
- caveats: >
    Monthly "RINVOQ 180ML" is excluded (RINVOQ is oral; the label is a source
    error). TREMFYA and SKYRIZI weekly lines are SQ/IV only — IV is included for
    SKYRIZI (no separate weekly IV line) but TREMFYA is SQ-only by the weekly
    label. Only ROW_TYPE = PRODUCT rows participate; never MARKET_TOTAL.
- provenance: auto-saved | 2026-06-04 | R | run_id=discussion

## RULE-004: Indication allocation of weekly volume
- applies_to: Weekly_Data_Tabular.TRX_ADJUSTED, Monthly_Data_Tabular.TRX_VOLUME
- category: metric
- definition: >
    The Weekly table carries a brand's total weekly TRx but no indication
    breakdown; the Monthly table has the breakdown. To split the WHOLE weekly
    total across a chosen set of indications, borrow the brand's Monthly
    indication mix (a unitless ratio) for the matching calendar month,
    RENORMALISE it across the reported indications so the shares sum to 1.0, and
    apply it to the full weekly total. The reported indications therefore sum
    back to the weekly total — the total is fully distributed, not partially.
    Steps:
      1. Map the Weekly brand to its Monthly rows via RULE-003.
      2. Pick the REPORTED indication set (what the analysis splits into). If it
         contains PsA, use PsA (Derm) + PsA (Rheum) and EXCLUDE the Total PsA
         rollup so no indication is double-counted. PRODUCT rows only.
      3. For drug D, month M, reported indication i:
           share[i, M] = TRX_VOLUME[D, i, M] / Σ_(j in reported set) TRX_VOLUME[D, j, M]
         Shares are renormalised over the reported set, so they sum to 1.0.
      4. Assign each Weekly row to month M = calendar month of WEEK_ENDING.
      5. weekly_ind_trx[i, week] = TRX_ADJUSTED[D, week] × share[i, M].
    Worked example: weekly TREMFYA = 100 and the monthly UC:CD ratio is 40:60
    -> UC = 40, CD = 60 (sum = 100, the full weekly total).
- formula: >
    monthly_trx = monthly[PRODUCT in crosswalk & INDICATION in reported_set]
                    .groupby(['MONTH_DATE','INDICATION'])['TRX_VOLUME'].sum().unstack()
    shares = monthly_trx.div(monthly_trx.sum(axis=1), axis=0)   # renormalise to 1.0
    weeks['month'] = weeks.WEEK_ENDING.dt.to_period('M').dt.to_timestamp()
    weeks[i] = weeks.TREMFYA_TRx_total * shares.loc[week_month, i]
- caveats: >
    The ENTIRE weekly total is attributed to the reported indications. If the
    reported set is a SUBSET of the brand's real indications (e.g. IBD = UC + CD
    only), this attributes the brand's whole weekly volume to that subset, which
    overstates it unless the weekly panel is genuinely confined to that set.
    Choose the reported set to match what the weekly total actually represents,
    and state this in context.md. Weeks before the brand has any monthly volume
    in the reported set cannot be split and show 0. Weeks past the last Monthly
    month (2026-04-01) carry forward the latest available month's mix. Allocated
    indication volumes are ESTIMATES, not measured weekly indication counts.
- provenance: auto-saved | 2026-06-04 | R | run_id=discussion | revised 2026-06-04 (renormalise within reported set; superseded the earlier true-share denominator)

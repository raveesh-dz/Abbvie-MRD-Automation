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

<!-- ===== Gastro HCP universe table (sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl) ===== -->

## RULE-005: TRx and NBRx are stored measures selected by data_type (no arithmetic)
- applies_to: sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl (frx*, data_type, product_brand, indication_code, abv_customer_id)
- category: metric
- definition: >
    In the gastro HCP universe table TRx (Total Rx) and NBRx (New-to-Brand Rx) are
    NOT computed — they are stored as the frx* weekly series, and which one a row
    carries is given by its data_type column ('TRx' or 'NBRx'). To get a brand's
    NBRx (or TRx) in an indication, FILTER the rows and READ the series; never
    derive one from the other.
      brand X, indication Y, measure M (TRx|NBRx):
        rows where product_brand = X AND indication_code = Y AND data_type = M
    The canonical way to build an HCP-level multi-brand/measure view is to take each
    (product_brand, indication_code, data_type) slice and align it on
    abv_customer_id — the join is 1:1 (abv_customer_id is unique within a slice,
    verified, no fan-out). This mirrors the source SQL, which LEFT JOINs each
    filtered slice onto an HCP base on abbott_customer_id (= abv_customer_id).
- formula: >
    slice = df[(df.product_brand==X) & (df.indication_code==Y) & (df.data_type==M)]
    # weekly series = slice[['frx1'..'frx399']]; per-HCP view = slice keyed on abv_customer_id
- caveats: >
    Apply RULE-101 (exclude class rollups) when X is meant to be an individual
    brand. SKYRIZI = OBI presentation only (RULE-303). The frx series meaning is
    governed by data_type — never mix a TRx row's series with an NBRx row's.
- provenance: auto-saved | 2026-06-26 | R | run_id=discussion

## RULE-006: frx* is a positional weekly value series
- applies_to: sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl (frx1 .. frx399)
- category: metric
- definition: >
    frx1..frx399 are 399 consecutive WEEKLY values for the row. There is no date
    column; dates are positional. frx1 is the MOST RECENT week (week ending
    2026-06-05, a Friday, taken from the YYMMDD stamp in the file name); each higher
    index is exactly one week earlier, so frx399 = week ending 2018-10-19. The value
    is TRx or NBRx per the row's data_type (RULE-005). Date anchoring and the default
    analysis window live in time.md (RULE-401).
- formula: "week_ending(frxN) = date(2026-06-05) - (N-1) weeks"
- caveats: >
    On a future re-extract the anchor moves to that file's YYMMDD stamp and the
    column count may grow; frx1 is always the latest week of that extract.
- provenance: auto-saved | 2026-06-26 | R | run_id=discussion

## RULE-007: Rolling-window sums and growth
- applies_to: sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl (cur_/pre_{4,13,26,52}wk, frx*)
- category: metric
- definition: >
    cur_Nwk and pre_Nwk are pre-computed contiguous trailing-week sums of the frx*
    series (verified against frx to ~1e-8):
      cur_Nwk = sum(frx1 .. frxN)            -- most recent N weeks
      pre_Nwk = sum(frx(N+1) .. frx(2N))     -- the N weeks immediately before
    for N in {4, 13, 26, 52}. Use these columns directly for period volumes.
    Period-over-period growth for window N:
      growth_abs[N] = cur_Nwk - pre_Nwk
      growth_pct[N] = (cur_Nwk - pre_Nwk) / pre_Nwk   (undefined/!NA when pre_Nwk = 0)
- formula: "growth_pct_13wk = (cur_13wk - pre_13wk) / pre_13wk"
- caveats: >
    Growth % is undefined where pre_Nwk = 0 (new/zero-baseline HCPs) — report as NA,
    not 0 or inf. Windows are non-overlapping (cur vs pre). Sum cur_/pre_ over the
    HCP set you want; never sum across class rollups + their brands (RULE-101).
- provenance: auto-saved | 2026-06-26 | R | run_id=discussion

## RULE-008: Decile groupings (bio and hum)
- applies_to: sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl (bio_decile, bio_decile_group, hum_decile, hum_decile_group)
- category: metric
- definition: >
    bio_decile and hum_decile are integer deciles 0-10 (10 = highest-volume decile;
    0 = no measured volume). The pre-banded *_decile_group columns map them as
    (verified by crosstab): LOW = 0-2, MEDIUM = 3-6, HIGH = 7-10. bio_decile ranks
    biologic IBD prescribing; hum_decile ranks Humira prescribing.
- formula: "group = LOW if decile<=2 else MEDIUM if decile<=6 else HIGH"
- caveats: "Decile 0 (no volume) falls in LOW. Use the supplied *_decile_group columns rather than re-banding."
- provenance: auto-saved | 2026-06-26 | R | run_id=discussion

## RULE-009: HCP_demographics dedup to one row per HCP
- applies_to: HCP_demographics (abbott_customer_id, zip_code, Territory_name, Region_name, District_name, state)
- category: metric
- definition: >
    HCP_demographics is delivered with up to 3 rows per HCP (multiple practice
    locations) plus some all-null-geo rows, so it is not safe to join as-is. Reduce it
    to ONE row per HCP before any join:
      1. Drop rows where ALL geo fields {zip_code, Territory_name, Region_name,
         District_name, state} are null.
      2. Among the remaining rows for each abbott_customer_id, keep the row with the
         most non-null geo fields (highest completeness).
      3. Tie-break by original file order (keep the FIRST such row).
    Result is deterministic: 1,035 HCPs with geography (5 HCPs have no geo at all and
    are dropped here → null on a left join from the universe).
- formula: >
    geo = ['zip_code','Territory_name','Region_name','District_name','state']
    d = demo.copy(); d['_c'] = d[geo].notna().sum(axis=1); d['_o'] = range(len(d))
    d = d[d['_c'] > 0].sort_values(['abbott_customer_id','_c','_o'],
                                   ascending=[True, False, True])
    demo_1pp = d.drop_duplicates('abbott_customer_id', keep='first')
- caveats: >
    Always apply before using any HCP_demographics relationship edge, or the join fans
    out. Completeness tie-breaks are resolved by file order, so the choice between two
    equally-complete practice locations is arbitrary-but-stable. Pairs with RULE-305
    (geography authority).
- provenance: auto-saved | 2026-06-26 | R | run_id=discussion

## RULE-010: SKYRIZI Holdout classification (Crohn's new prescribing, NBRx)
- applies_to: sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl (SKYRIZI vs STELARA CD NBRx), per HCP
- category: metric
- definition: >
    Classifies each HCP by whether they have shifted their NEW Crohn's-Disease prescribing
    from STELARA to SKYRIZI. Uses NBRx only (new brand prescriptions), indication_code = CD,
    over the most recent 13 weeks (cur_13wk = frx1..frx13, RULE-007). Per HCP take SKYRIZI
    CD NBRx and STELARA CD NBRx, then:
      - ratio = STELARA_NBRx / SKYRIZI_NBRx (defined only when SKYRIZI > 0).
      - Holdout (NOT moved to SKYRIZI; conversion target):
          * no_cd_nbrx        — SKYRIZI == 0 AND STELARA == 0 (no recent CD new starts)
          * stelara_only      — STELARA > 0 AND SKYRIZI == 0
          * both_lean_stelara — both > 0 AND ratio >= 0.5
      - Non-Holdout (SKYRIZI wins new prescribing; retention):
          * skyrizi_only      — STELARA == 0 AND SKYRIZI > 0
          * both_lean_skyrizi — both > 0 AND ratio < 0.5
    Brand scope by default = the SKYRIZI and STELARA brand labels EXACTLY (SKYRIZI excludes
    SKYRIZI_IV; STELARA excludes STELARA_IV, plain USTEKINUMAB, and ustekinumab biosimilars).
    Confirmed by user 2026-06-26.
- formula: >
    sky = Σ frx1..13 where product_brand=='SKYRIZI', indication_code=='CD', data_type=='NBRx'
    stel = Σ frx1..13 where product_brand=='STELARA', indication_code=='CD', data_type=='NBRx'
    ratio = stel/sky if sky>0 else undefined
    holdout = (sky==0) or (sky>0 and stel>0 and ratio>=0.5)
- caveats: >
    Ratio undefined when SKYRIZI==0 (denominator 0) — those HCPs are classified by the
    zero-SKYRIZI branch, and the emitted ratio column is a STRING showing the number for
    defined rows or "undefined_stelara_only"/"undefined_no_cd_nbrx" otherwise. The Holdout
    bucket mixes silent HCPs (no_cd_nbrx — no new CD starts at all) with active STELARA
    prescribers; for targeting, separate them (active leaners = true switch list). NBRx-only
    by design — ignores the existing TRx book. Threshold 0.5 and brand scope are user choices,
    not source-defined. Run universe = Holdout_HCP_Universe (RULE-102).
- provenance: auto-saved | 2026-06-26 | R | run_id=run_2026-06-26_001

# Standing Filters & Exclusions
<!-- Applied UNCONDITIONALLY at the top of every generated script. -->

## RULE-101: Exclude product_brand class rollups from brand-level sums
- applies_to: Gastro_prod_sales_260605.product_brand
- category: filter
- definition: >
    product_brand mixes individual brands/biosimilars/presentations with CLASS
    ROLLUP rows that are pre-aggregated sums of their constituent brands. The rollup
    set is: {SI_ORAL, TNF, JAK, IL_23, IL_23_IL_12, A4B7, S1P}. SI_ORAL is the market
    grand total; the others are therapeutic-class totals. When summing or ranking
    INDIVIDUAL brands, EXCLUDE these rollups, or volumes double-count. They remain
    usable on their own as a class/market total — just never add them to the brands
    they contain.
- formula: >
    CLASS_ROLLUPS = {"SI_ORAL","TNF","JAK","IL_23","IL_23_IL_12","A4B7","S1P"}
    brands = df[~df.product_brand.isin(CLASS_ROLLUPS)]   # for brand-level work
- caveats: >
    Verified: JAK, IL_23, IL_23_IL_12, A4B7, S1P rollups equal the sum of their
    constituent brands (ratio 1.000 on cur_13wk TRx); TNF likewise (its constituents
    include the many adalimumab biosimilar code variants). No second (molecule-level)
    rollup layer exists — there is no plain 'ADALIMUMAB' row; 'USTEKINUMAB' is a
    constituent brand of IL_23_IL_12, not a separate rollup. If a future extract adds
    a new class code, extend this set.
- provenance: auto-saved | 2026-06-26 | R | run_id=discussion

## RULE-102: Restrict HCP analyses to the analyzable (holdout) universe
- applies_to: Holdout_HCP_Universe.abbott_customer_id, Gastro_prod_sales_260605.abv_customer_id
- category: filter
- definition: >
    Holdout_HCP_Universe is the authoritative set of in-scope HCPs for the gastro
    holdout analysis. HCP-level analyses on the gastro universe should be RESTRICTED to
    HCPs whose abv_customer_id is present in this list. It is a scope membership, NOT a
    treatment/control split.
- formula: >
    gastro = gastro[gastro.abv_customer_id.isin(set(holdout.abbott_customer_id))]
- caveats: >
    The Holdout id set is a strict SUBSET of the gastro universe (700 of 1,040 HCPs),
    so this filter MATERIALLY restricts HCP analyses — it is no longer a no-op. Apply
    it unconditionally on any gastro HCP analysis. Do not confuse "holdout" here with
    an experimental control arm; it is the analyzable scope.
- provenance: auto-saved | 2026-06-26 | R | run_id=discussion

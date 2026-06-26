# Business Context & Known Patterns
<!-- Used to EXPLAIN results in takeaways, never to alter numbers. -->

## RULE-301: Weekly panel is IBD-only
- applies_to: Weekly_Data_Tabular
- category: context
- definition: The weekly "SI Market + Oral" panel covers the IBD / gastrointestinal market only. A product's weekly TRx here is its IBD usage (UC + CD), even for products that are also used in dermatology or rheumatology nationally. Therefore a weekly total, when split by indication via RULE-004, should be distributed across the IBD indications {UC, CD} only — the full weekly total is genuinely IBD, so attributing all of it to UC/CD is correct, not an overstatement.
- formula: n/a
- caveats: This does NOT apply to the Monthly table, which is national and spans all 11 indications. The monthly mix is used only to derive the UC:CD ratio applied to the weekly IBD total.
- provenance: auto-saved | 2026-06-04 | R | run_id=run_2026-06-04_002

<!-- ===== Gastro HCP universe table (sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl) ===== -->

## RULE-302: Gastro HCP behavioural segments
- applies_to: sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl.gastro_segments
- category: context
- definition: >
    gastro_segments classifies each HCP into a behavioural adoption segment used for
    targeting and messaging:
      - Influencers     — high-volume, opinion-leading gastro prescribers (largest group).
      - Pragmatists     — evidence-driven adopters who follow established protocols.
      - Fast Followers  — adopt newer therapies soon after early evidence.
      - Traditionalists — conservative prescribers, slower to switch.
      - Unsegmented     — not assigned a segment (small residual).
    Use to EXPLAIN differences in volume/growth or product mix across HCP groups;
    never to alter computed numbers.
- formula: n/a
- caveats: "Segment definitions are AbbVie commercial constructs; 'Unsegmented' is a tiny residual."
- provenance: auto-saved | 2026-06-26 | R | run_id=discussion

## RULE-303: Product presentation semantics and biosimilar landscape
- applies_to: sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl.product_brand
- category: context
- definition: >
    product_brand encodes presentation and the IBD biosimilar landscape:
      - SKYRIZI (plain) = SKYRIZI OBI (on-body injector / SC maintenance), the dominant
        IBD presentation; SKYRIZI_IV = IV induction. Total Skyrizi = SKYRIZI + SKYRIZI_IV.
      - Suffixes: _IV = intravenous, _SQ = subcutaneous, _CDV = citrate-free variant.
      - Many adalimumab biosimilars are present (HYRIMOZ, AMJEVITA, CYLTEZO, HADLIMA,
        YUSIMRY, YUFLYMA, SIMLANDI, ABRILADA, HULIO, IDACIO, plus code aliases ADAZ,
        ADBM, AATY, AACF, RYVK, FKJP, BWWD) alongside ustekinumab biosimilars (WEZLANA,
        PYZCHIVA, STEQEYMA, YESINTEK, SELARSDI, IMULDOSA, STARJEMZA, OTULFI) — relevant
        for biosimilar-erosion narratives against HUMIRA and STELARA.
      - The SAME entity appears under inconsistent delimiters (e.g. 'ENTYVIO SQ' vs
        'ENTYVIO_SQ'; 'ADALIMUMAB RYVK' vs 'ADALIMUMAB_RYVK' vs 'ADALIMUMAB-RYVK').
        Normalise (collapse spaces/underscores/hyphens) before grouping by brand.
- formula: n/a
- caveats: >
    Class rollups are handled separately by RULE-101. Whether plain ENTYVIO / STELARA
    represent an 'all-presentations' total vs a specific presentation is UNRESOLVED —
    verify against the relevant class rollup before treating either as a brand total.
- provenance: auto-saved | 2026-06-26 | R | run_id=discussion

## RULE-304: HCP targeting and engagement flags
- applies_to: sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl (rinvoq_hits, skyrizi_hits, gastro_hits, phy_univ_flag, true_1view_flag, pdrp_flag, ai*_cp_flag)
- category: context
- definition: >
    - rinvoq_hits / skyrizi_hits / gastro_hits = Y when the HCP is a promotional/
      engagement target ('hit') for that brand/franchise; use to segment reached vs
      not-reached HCPs.
    - phy_univ_flag / true_1view_flag = Y for HCPs in the in-scope physician universe /
      consolidated customer view (they coincide in this extract).
    - pdrp_flag = Y marks PDRP (Prescriber Data Restriction Program) opt-out HCPs; per
      user (2026-06-26) NO suppression is applied — documented only.
    - ai*_cp_flag = call-plan inclusion flags; the numeric-code meanings (ai4/ai5/ai6/
      ai45/ai10) are UNCONFIRMED and SET ASIDE per user (2026-06-26). ai456_cp_flag is
      constant N (dead). Do not build rules or takeaways on the ai* flags until defined.
- formula: n/a
- caveats: "ai* flag semantics are a known open item to revisit with the user."
- provenance: auto-saved | 2026-06-26 | R | run_id=discussion

## RULE-305: HCP geography authority and sales-geo hierarchy
- applies_to: HCP_demographics (zip_code, state, Territory_name, District_name, Region_name); sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl (zip_code, state)
- category: context
- definition: >
    HCP_demographics is the PRIMARY (first) source for HCP geography. When the same HCP
    has different zip_code/state in HCP_demographics vs the gastro universe table,
    HCP_demographics WINS; the universe's zip/state is a fallback only (used when the
    HCP is among the 5 with no demographics geo). HCP_demographics also uniquely
    supplies the AbbVie sales-geography hierarchy, a strict containment:
      Region (5: Central, Great Lakes, Northeast, Southeast, West)
        > District (~31)
          > Territory (~101, lowest tier).
    Use these tiers to roll up / segment HCP volumes geographically.
- formula: n/a
- caveats: >
    Apply RULE-009 (dedupe demographics to one row/HCP) before reading geography. The
    state column is occasionally null even when Territory/District/Region are present;
    Territory_name and District_name carry the state as a 'City,ST' suffix, so derive
    state from there when null.
- provenance: auto-saved | 2026-06-26 | R | run_id=discussion

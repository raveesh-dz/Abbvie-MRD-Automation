# Context — run_2026-06-08_002
headline: Skyrizi's IBD volume is overwhelmingly Crohn's (CD 76.9% / UC 23.1% in the week ending 2026-05-08), but UC has grown from ~4% to ~23% of the mix since its 2024 launch.
methodology: The weekly "SI Market + Oral" panel is IBD-only (RULE-301), so Skyrizi's full weekly TRx is IBD volume. "Skyrizi" is taken as the combined entity — the weekly SKYRIZI line plus the SKYRIZI OBI (on-body injector) line summed — because OBI is ~99.9% of Skyrizi's IBD volume (user-confirmed 2026-06-08). The combined weekly total is split across UC and CD using the national monthly indication mix for SKYRIZI SQ + IV + OBI (RULE-003 crosswalk), renormalised within {UC, CD} so the two sum back to the weekly total (RULE-004).
filters_applied: PRODUCT rows only (ROW_TYPE = PRODUCT); indication set restricted to UC and CD; weekly products SKYRIZI + SKYRIZI OBI; monthly crosswalk rows SKYRIZI SQ + SKYRIZI IV + SKYRIZI OBI.
time_period: 2024-05-03 → 2026-05-08 (106 weeks, full available weekly range; no window was requested and no default is defined).
data_freshness: latest week_ending = 2026-05-08. Weeks after 2026-04-01 carry forward the April-2026 monthly mix (the monthly extract ends 2026-04-01). Provisional-week treatment is unconfirmed (MEMORY pending #3); tails look stable.
caveats: >
  Indication-level volumes are ESTIMATES — the weekly panel has no native indication breakdown, so UC/CD are derived by applying the national monthly mix to the weekly total (RULE-004). They are not measured weekly indication counts.
  "Skyrizi" here = SKYRIZI + SKYRIZI OBI combined; the plain SKYRIZI line alone is only ~11 TRx/week (the on-body injector is essentially the whole IBD business).
  The combined-entity mix (UC 3,622 / CD 12,035 latest) differs slightly from a per-line-then-summed estimate (UC ~3,309 / CD ~12,347) because the small SQ/IV line carries a different UC/CD mix; both methods agree CD is ~77–79%.

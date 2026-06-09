# PROJECT MEMORY — Query-to-Slide

> Running state of the build so a new session resumes without starting blank.
> Read this first, alongside CLAUDE.md. Update it whenever setup state changes.
> Last updated: 2026-06-09 (user: R / rounaksuranshe@gmail.com)

---

## Environment / gotchas
- **Python:** `python` is a broken Windows Store alias. Use **`py -3`** (Python 3.12.10 on this box — earlier MEMORY note said 3.14, stale, fixed 2026-06-09). Installed: pandas 2.3.3, pyarrow 24, pyyaml, snowflake-connector-python 4.6, typer 0.26, rich.
- **Node:** v25.8.1 / npm 11. `pptxgenjs` is installed LOCALLY in `apex-deck-builder/node_modules` (not global) — node resolves it from there, no NODE_PATH needed.
- **LibreOffice:** NOT installed → the deck-builder's visual QA render (pptx→images) can't run on this machine. Verify decks via `deck_config.json` vs `result.csv` instead.
- **Git:** initialised, remote = `github.com/raveesh-dz/Abbvie-MRD-Automation` (origin/main). Earlier MEMORY note said "not initialised" — stale, fixed 2026-06-09. Make a new commit per change to `/semantic/` or `/metadata/`; never `--amend` published commits.
- Schema gate: `py -3 scripts/validate_schema.py` (or `mrd validate`) -> currently **ALL CLEAR**, four tables active.
- Snowflake (added 2026-06-09): account `SGWXVBR-HNA51236`, role `DZ_DEVELOPERS`, warehouse `COMPUTE_WH`, db `SNDBX_DB`, schema `ADHOC`. Auth = `externalbrowser` SSO (dev). Write access confirmed (CREATE TABLE + PUT + COPY INTO all work in SNDBX_DB.ADHOC). Creds in `.env` (gitignored), template at `.env.example`. `keyring` NOT installed -> SSO popup per process; install `snowflake-connector-python[secure-local-storage]` to cache the ID token if popups get annoying.

## Data layer (new — package `mrd_engine`, branch `feature/data-layer`)
- **Package:** `src/mrd_engine/` installed editable via `pyproject.toml` (`py -3 -m pip install -e .`). Entrypoint `mrd` (Typer); use `py -3 -m mrd_engine.cli ...` (the `mrd.exe` shim is in `%APPDATA%/Roaming/Python/Scripts` which isn't on PATH).
- **Connectors:** abstraction at `src/mrd_engine/connectors/{base,csv_local,snowflake}.py`. Each declares config in `connectors/<name>.yaml` (`snowflake_dz.yaml`, `csv_local.yaml`). Auth env-var refs only. Connectors land data as parquet in `data/_cache/<table>.parquet` and return a `Manifest` (table, source, fetched_at, row_count, column_hash, cache_path).
- **Onboarding flow (`mrd onboard <connector> <object>`):** fetch -> profile (`profiles/<table>.json`) -> propose metadata (default backend `claude_cli`, falls back to `heuristic` on failure; `anthropic_api` stub for later) -> writes `metadata/<table>.yaml.proposed`. User runs `mrd review <table>` (interactive) or `mrd review <table> --auto` to promote to `.yaml`.
- **Claude CLI backend:** spawns `claude -p --output-format text` headless via stdin pipe (Windows cmd-arg escaping landmines — DO NOT pass the prompt as a CLI arg; pipe over stdin). Resolved via `shutil.which("claude")` + `shell=True` on Windows so `.cmd` shims work. Validated 2026-06-09 — produces real domain-aware metadata (e.g. NDC zero-padding caveats, biosimilar rollup risk).
- **Join recommender v2 (`mrd joins recommend`):** name match (exact / substring) + Jaccard value overlap + cardinality (1:1, 1:N, N:1, N:M). Optional LLM rationales (`--no-rationales` to skip). Writes ranked candidates to `profiles/join_candidates.json`. `--accept-all` appends every candidate to `metadata/relationships.yaml`; `mrd joins accept <ids>` accepts specific ones from the JSON.
- **Loader:** `mrd_engine.loader.load(table)` resolves via metadata `source.cache_path` -> fall back to `data/<table>.csv` -> `.parquet`. Source-agnostic surface for the engine.
- **Run manifest:** `mrd_engine.runs.manifest.write_manifest(run_dir, [Manifest...])` -> writes `source_manifest.json` per run (connector, fetched_at, row_count, column_hash). Reproducibility surface.
- **Extended schema gate (`scripts/validate_schema.py`):** handles both legacy CSV path (existing Weekly/Monthly YAMLs without `source` block) AND new source-block path (cache_path + column_hash drift check). `--include-remote` adds a Snowflake handshake + remote `DESCRIBE TABLE` diff. Exit codes unchanged.
- **Snowflake target onboarded:** `SNDBX_DB.ADHOC.ADHOC_FINAL_TABLE` (736,763 rows, 222 cols — patient-claim Rx data: DZ_PAT_ID, CLAIM_ID, NDC_CD, DIAG_CD_1..8, SRVC_DT, YEAR_MONTH). Cached at `data/_cache/ADHOC_FINAL_TABLE.parquet`. Metadata `metadata/ADHOC_FINAL_TABLE.yaml` (heuristic-proposed, auto-accepted; replace description/grain when convenient).
- **Synthetic NDC->brand crosswalk:** `data/ndc_brand_crosswalk.csv`, 60 NDCs (top by claim count) randomly mapped to real IQVIA brands. Onboarded via `csv_local`. Covers 18.4% of claim rows. **Crosswalk is fake** — assignments are arbitrary; replace with FDA NDC directory or licensed source before any production use.
- **End-to-end smoke test:** `scripts/onboarding/engine_smoketest.py` loads ADHOC + crosswalk + Weekly via `mrd_engine.loader.load()`, bridges (claims -> NDC -> brand), writes `output/run_<date>_smoke/result.csv` + `source_manifest.json`. Passes.
- **Files added/modified this session:**
  - `pyproject.toml`, `src/mrd_engine/**` (connectors, metadata, onboarding, runs, loader, cli, envloader)
  - `connectors/csv_local.yaml`, existing `snowflake_dz.yaml`
  - `metadata/ADHOC_FINAL_TABLE.yaml`, `metadata/ndc_brand_crosswalk.yaml`, `metadata/relationships.yaml` (6 new auto-discovered edges appended — some spurious like ROW_TYPE/NON_APPROVED_FLAG, cull later)
  - `scripts/validate_schema.py` (extended), `scripts/onboarding/engine_smoketest.py`

## Open items (data layer)
1. Prune spurious auto-discovered edges in `relationships.yaml` (ROW_TYPE, NON_APPROVED_FLAG — categorical flags, not real joins).
2. Replace synthetic NDC crosswalk with FDA NDC directory (or a licensed source) before production.
3. Add a source-block enrichment for the existing `Weekly_Data_Tabular.yaml` and `Monthly_Data_Tabular.yaml` so they too participate in cache/drift checks (currently legacy CSV path — works but no column-hash drift detection).
4. Optional: install `snowflake-connector-python[secure-local-storage]` + `keyring` to cache SSO id token (one popup vs many).
5. Anthropic API backend in `proposer.py` is a stub — wire when an `ANTHROPIC_API_KEY` is available, for non-interactive/CI metadata gen.
6. dbt-core foundation layer (Phase 5) deferred per user — current scope was data layer up to feeding existing engine, no foundation marts.

## Pipeline output → slides (apex-deck-builder)
- The deck stage is OPT-IN (CLAUDE.md Step 8). Default stop = the 6-file output contract (Step 7). After delivering, ASK "Do you want me to build a slide deck?" and build ONLY on an explicit yes. Never auto-build.
- SKILL.md was rewritten (2026-06-04) to a design-led python-pptx methodology (reference-matched, Lucide icons, integrity sanitizer, self-review). Reference deck: `apex-deck-builder/examples/Deck revamp refrence.pdf` (DataZymes/Otsuka house style — blue section strip, statement title, italic dek, custom diagrams, numbered blocks, TL;DR bar, ▶ DataZymes footer).
- **CURRENT builder: `py -3 scripts/build_deck_pptx.py output/<run_id>`** (python-pptx). Reads `result.csv` + `deck_spec.json` (date_column/title/subtitle/series_columns/total_column), renders a SINGLE content slide (native UC/CD line chart, numbered insights, TL;DR) — the lead/divider slide was REMOVED 2026-06-08 per user (not required). Runs integer-EMU sanitizer + round-trip validation. Tuned to the IBD UC/CD shape.
- Toolchain gaps on this machine: **LibreOffice not installed** → visual self-review render can't run (do structural QA instead). **cairosvg not installed** → Lucide icons substituted with native numbered markers. Montserrat/Roboto likely absent locally (font names still embedded; render substitutes).
- LEGACY path (superseded): `scripts/handoff_deck.py` → `apex-deck-builder/scripts/build_config.js` + `apex_deck.js` (pptxgenjs). Still works for a quick chart-only deck.

## Data (two independent IQVIA e-laad extracts — different grains)
- `data/Weekly_Data_Tabular.csv` — product × week, `TRX_ADJUSTED`. Market = "SI Market + Oral". Range 2024-05-03 → 2026-05-08. No indication breakdown. **SCOPE: this panel is IBD / GI ONLY (user-confirmed 2026-06-04, RULE-301).** A product's weekly volume = its IBD (UC+CD) usage; split weekly totals only across {UC, CD}, never across a product's non-IBD indications. (The Monthly table is national / all 11 indications; it only supplies the UC:CD ratio.)
- `data/Monthly_Data_Tabular.csv` — indication × product × month, `TRX_VOLUME`. 11 indications. Range 2020-05-01 → 2026-04-01.

## Metadata — DONE
- `metadata/Weekly_Data_Tabular.yaml` — written, passes gate.
- `metadata/Monthly_Data_Tabular.yaml` — written, passes gate.
- `metadata/relationships.yaml` — one allocation edge declared (see RULE-004). No other join is valid: tables differ in grain, metric, and product granularity; PRODUCT is NOT a clean row-join key outside the RULE-003 crosswalk.

## Semantic rules — what exists
Only the indication-allocation rule is defined. Everything else was stripped (was `rx_transactions` placeholder junk).
- **RULE-003 (metrics.md)** — Weekly→Monthly brand crosswalk. Match same FORM, sum dose splits, never fold IV into SQ. Non-trivial maps: RINVOQ=15+30+45MG (exclude bad "180ML"); OMVOH SQ=both SQ dose rows; TREMFYA=SQ 100+200+INDUCTION (SQ only); SKYRIZI=SQ+IV (OBI separate); SIMPONI SC→Simponi SQ; ACTEMRA BIOSIMILARS SQ TOTAL=AVTOZMA SQ+TYENNE SQ. ~26 brands match exactly 1:1.
- **RULE-004 (metrics.md)** — Indication allocation. **REVISED 2026-06-04 (renormalise-within-reported-set).** Split the FULL weekly total across the *reported* indication set: monthly mix for those indications renormalised to sum to 1.0, applied to the weekly total → reported indications sum back to the weekly total. (Superseded the earlier "true share of full mix" approach, which left the total only partially split.) Confirmed by user with example: weekly 100, UC:CD = 40:60 → UC 40, CD 60.
  - KEY CONSEQUENCE: if the reported set is a SUBSET (e.g. IBD = UC+CD only), the ENTIRE weekly total is attributed to that subset — overstates it. So IBD-only and on-label runs give DIFFERENT UC/CD (different denominators). Flag in context.md.
  - Denominator = the reported indication set (renormalised). If PsA included, use PsA (Derm)+PsA (Rheum), EXCLUDE Total PsA. PRODUCT rows only.
  - Week→month by calendar month of `WEEK_ENDING`; weeks past 2026-04 carry forward April 2026 mix. Weeks before the set has any monthly volume show 0. Estimates, not census.
- `_rule_log.csv` — RULE-003, RULE-004 (auto-saved, reviewed=yes).

## Runs completed
- run_2026-06-04_001 — DELETED 2026-06-04. Was an on-label (Ps/PsA/UC/CD) split; invalid once the weekly panel was confirmed IBD-only (no psoriasis volume in an IBD panel). Superseded by run_002.

- **run_2026-06-04_002** — "weekly tremfya TRx split by indications for IBD market". The CURRENT valid deliverable. IBD = {UC, CD}; weekly panel is IBD-only (RULE-301) so the full weekly total splits across UC/CD via the national monthly UC:CD ratio (RULE-004 renormalise-within-set). Clean function-based commented code. UC+CD = weekly total; UC ~3,121 / CD ~3,905 on 2026-05-08 (CD overtook UC during 2025). PASS, 106 weeks, columns reconcile to total. Standalone (base_plan: none). DECK built: `deck.pptx` (divider + UC/CD/IBD chart slide + latest-vs-4wk table) via `scripts/handoff_deck.py` + `deck_spec.json`.
- **run_2026-06-04_003** — fresh timestamped re-run of the same IBD query (user wanted a new run, not a reuse of run_002). Identical method/result (UC ~3,121 / CD ~3,905 on 2026-05-08). PASS, 106 weeks. DECK built via the NEW python-pptx builder (`scripts/build_deck_pptx.py`) in the DataZymes reference style: divider + content slide (UC/CD line chart, numbered insights, "Crohn's overtook UC ~Oct 2025", TL;DR). Sanitizer + round-trip validation PASS; visual render not done (no LibreOffice).
- **run_2026-06-08_001** — same weekly TREMFYA IBD UC/CD split, new standalone run (fresh session, full boot sequence re-run; schema gate ALL CLEAR). Identical established method (RULE-003 + RULE-004 renormalise-within-set, RULE-301 IBD-only). Result identical: UC 3,121 / CD 3,905 / total 7,026 on 2026-05-08; durable CD>UC crossover from 2025-10-03. PASS, 106 weeks, 0 nulls, UC+CD reconciles to total (diff ~9e-13). 6-file contract delivered. DECK built (python-pptx `scripts/build_deck_pptx.py`, deck_spec.json same shape as run_003): 2 slides (divider + UC/CD line-chart content slide, statement title "Crohn's Has Overtaken Ulcerative Colitis in Tremfya's IBD Mix", numbered insights, crossover ~Oct 2025). Structural QA PASS — chart series trace to result.csv (UC last 3120.92 / CD last 3905.16), integrity 0 issues, round-trip OK. Visual render not run (no LibreOffice); cairosvg absent so Lucide icons = native markers.
- **run_2026-06-08_002** — "skyrizi TRx split by indication for IBD market". KEY FINDING: the plain weekly `SKYRIZI` line is only ~11 TRx/wk; **`SKYRIZI OBI` (on-body injector, the IBD maintenance presentation) is ~99.9% of Skyrizi's IBD volume (~15,645/wk).** User first said exclude OBI, then (after the magnitude was surfaced) confirmed **SKYRIZI + OBI combined**. Method: both weekly lines summed; monthly mix = SKYRIZI SQ+IV+OBI renormalised within {UC,CD} (RULE-004), RULE-301 IBD-only. Result: CD dominates 100% of weeks (no crossover); latest 2026-05-08 total 15,656 → UC 3,622 (23.1%) / CD 12,035 (76.9%). UC share grew ~3.5%→23% since its 2024 UC launch; total ~4.3× over 106 wks. PASS, 0 nulls, reconciles to total. 6-file contract delivered. DECK built (python-pptx): divider + content slide (UC/CD line chart, statement title "Crohn's Dominates Skyrizi's IBD Mix — but Ulcerative Colitis Is Climbing", 3 numbered insights, TL;DR). Structural QA PASS — chart series trace to result.csv (UC 3621.58 / CD 12034.60), no mojibake, integrity sanitizer + round-trip OK. Visual render not run (no LibreOffice).
  - NOTE for future Skyrizi/OBI work: a brand's "OBI" weekly line can be the dominant volume — always check OBI magnitude before excluding it. (Combined-entity mix UC 3,622/CD 12,035 differs slightly from per-line-then-summed UC ~3,309/CD ~12,347; both agree CD ~77–79%.)
  - BUILDER CHANGE (`scripts/build_deck_pptx.py`): now SPEC-DRIVEN — narrative pulled from deck_spec.json (`eyebrow`, `section_strip`, `statement_title`, `dek_template`, `chart_caption`, `blocks` [num/head/body_template], `tldr`); templates `.format()` over a computed ctx (first_total, latest_total, ramp, first_month, cross_month, latest_uc/cd, latest_label, first_uc_pct, latest_uc_pct, latest_cd_pct). Tremfya literals kept as fallback DEFAULTS so the old specs (run_003, run_0608_001) render identically (verified). ALSO fixed: spec + result.csv now read with `encoding="utf-8"` (Windows cp1252 default was mojibaking `·`/`—`). Use these spec fields for any non-Tremfya brand so the deck doesn't inherit the false "crossover/overtaken" story.

## STILL PENDING (user will add later — do NOT invent these)
Foundational rules still undefined; engine should ask before assuming:
1. **Market share denominator** — MARKET_TOTAL row vs sum of PRODUCT rows? Within-indication for Monthly?
2. **MARKET_TOTAL / Total Non-Approved Volume** — default double-count handling (dictionaries flag both as traps).
3. **Provisional periods** — does source treat latest week(s)/month as incomplete? (tails look stable; unconfirmed.)
4. **Time defaults** — no window stated → Weekly = ? , Monthly = ?
5. **Context patterns** for takeaways — biosimilar erosion (HUMIRA/STELARA), Q4 deductible spike, IV→SQ shift. `context.md` is empty.
6. **TRx definition rule** — note: NO NRx in this data; values are adjusted/projected volumes, not script counts.

## Cleanup status — rx_transactions (the old dummy table)
- Live config (`metadata/`, `semantic/`): **clean**, no references.
- The old `examples/` demo was **archived to `_reference/examples/`** (not deleted — git isn't set up).
- CLAUDE.md now instructs the engine to **SKIP `/_reference/`** entirely (read/validate/analyze/cite none of it).
- `PLAN.md` / `USER_GUIDE.md` still mention `rx_transactions` as illustrative doc text — left as-is (not config; user did not ask to scrub docs).

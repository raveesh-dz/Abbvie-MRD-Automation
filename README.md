# Query-to-Slide Analytics Engine

*Plain-English questions → validated AbbVie immunology TRx analytics + branded decks. Powered by Claude Code.*

`Python 3.14` · `pandas 3.0` · `python-pptx` · `IQVIA e-laad` · `Claude Code`

---

## What this is

An analyst asks a business question in plain English. The engine parses it, generates pandas code, validates the result, and writes a six-file audit-trail run folder. On explicit request, it also builds a DataZymes-branded slide deck.

- **Orchestrator:** Claude Code, governed by `CLAUDE.md` (protocol) and `MEMORY.md` (state).
- **Domain:** AbbVie immunology TRx — Tremfya, Skyrizi, Humira, Stelara, biosimilars across IBD / Derm / Rheum.
- **Data source:** IQVIA e-laad extracts (weekly IBD panel + monthly national across 11 indications).
- **Output:** auditable run folder per query, optionally a python-pptx deck.

## Why it exists

Brand teams spend hours hand-cutting IQVIA exports and rebuilding decks. This engine collapses that to minutes while keeping every number auditable.

- One query → one run folder. Plan, code, result, validation, and takeaways all on disk.
- Hard rules prevent hallucinated joins, fabricated metrics, and silent assumptions.
- Decks match a fixed brand reference, not an LLM's idea of "professional."

## Key design principles

- **Claude never does arithmetic.** All numbers come from generated pandas, executed.
- **Joins only via declared edges in `metadata/relationships.yaml`.** Never guessed.
- **Tables without a dictionary do not exist.** Schema gate runs at session boot.
- **Every assumption is surfaced and confirmed** before code runs.
- **Deck stage is opt-in.** The default stop is the six-file output contract. Claude asks before building slides.
- **Patient-grain output is refused.** Outputs aggregate above patient level, always.

## Quickstart

```bash
# 1. Verify environment
py -3 --version          # 3.14+
py -3 -m pip list | grep -E "pandas|pyyaml|pptx"

# 2. Run the schema gate (must be ALL CLEAR before any analysis)
py -3 scripts/validate_schema.py

# 3. Open a Claude Code session in this repo and ask a question, e.g.
#    "weekly tremfya TRx split by indication for IBD market"

# 4. Output lands in output/run_<YYYY-MM-DD>_<NNN>/
#    (6 files: query, plan, code, result, context, takeaways)
```

## Example run

See [`output/run_2026-06-08_002/`](output/run_2026-06-08_002/) — *Skyrizi (SQ + IV + OBI) IBD weekly TRx split by UC vs CD, 106 weeks*.

Files delivered:

```
query.txt           One-line user query.
analysis_plan.md    Tables, joins, filters, rules, assumptions, expected row count.
analysis_code.py    Standalone pandas. Reads /data/, writes result.csv.
result.csv          Validated output table (106 weekly rows).
context.md          Methodology, time window, caveats.
takeaways.md        2–4 numbered, traceable insights.
deck_spec.json      Deck narrative spec (opt-in).
deck.pptx           Final branded deck (opt-in).
```

Headline finding: Crohn's dominates ~77% of Skyrizi's IBD mix; UC growing since 2024 launch.

## Architecture

```
User query
   │
   ▼
Claude Code session   ──► reads CLAUDE.md (rules) + MEMORY.md (state)
   │
   ▼
Boot:  validate_schema.py  +  /metadata  +  /semantic
   │
   ▼
Parse ─► Feasibility check ─► Plan ─► Code ─► Validate ─► Takeaways
   │
   ▼
output/run_<id>/    (6-file contract)
   │
   ▼
[opt-in, on user yes]   deck_spec.json  ─►  build_deck_pptx.py  ─►  deck.pptx
```

## Repository structure

```
.
├── CLAUDE.md                 Engine protocol — workflow, hard rules, templates.
├── MEMORY.md                 Running project state — env, runs log, pending items.
├── README.md                 This file.
├── data/                     IQVIA CSVs.
│   ├── Weekly_Data_Tabular.csv
│   └── Monthly_Data_Tabular.csv
├── metadata/                 YAML dictionaries + relationships graph.
│   ├── Weekly_Data_Tabular.yaml
│   ├── Monthly_Data_Tabular.yaml
│   ├── relationships.yaml    The ONLY source of truth for joins.
│   └── _TEMPLATE.yaml
├── semantic/                 Business rules (one rule per semantic concept).
│   ├── metrics.md            RULE-003 crosswalk, RULE-004 allocation.
│   ├── filters.md            (no rules defined yet)
│   ├── context.md            RULE-301 IBD-only panel.
│   ├── time.md               (no rules defined yet)
│   └── _rule_log.csv         Rule provenance + review status.
├── scripts/                  Validation gates + deck builder.
│   ├── validate_schema.py    Boot gate. CSV ↔ dictionary parity.
│   ├── validate_result.py    Post-run check. Row count, nulls, dupes.
│   ├── build_deck_pptx.py    python-pptx, spec-driven, brand tokens.
│   └── handoff_deck.py       Legacy pptxgenjs path (superseded).
├── output/                   One folder per query: run_<date>_<NNN>/.
├── apex-deck-builder/        Deck design skill + reference deck.
│   ├── SKILL.md              Design methodology.
│   ├── examples/             DataZymes/Otsuka reference deck (source-of-truth).
│   ├── scripts/              Legacy pptxgenjs builders.
│   └── assets/               Lucide icons etc.
└── docs/                     Mockups + supplementary docs.
```

## Data model

Two independent IQVIA extracts. **Different grain, different metric, different product granularity.** They do not row-join.

| Table | Grain | Metric | Coverage | Date range |
|---|---|---|---|---|
| `Weekly_Data_Tabular` | product × week | `TRX_ADJUSTED` | IBD only (SI Market + Oral) | 2024-05-03 → 2026-05-08 |
| `Monthly_Data_Tabular` | indication × product × month | `TRX_VOLUME` | 11 indications, national | 2020-05-01 → 2026-04-01 |

**The only declared join** is an *allocation edge* (many-to-one): weekly brand × month-of-week-ending → monthly brand × month, used to borrow the unitless indication mix from the monthly side and apply it to the weekly total. `TRX_ADJUSTED` and `TRX_VOLUME` are never compared or summed directly.

See [`metadata/relationships.yaml`](metadata/relationships.yaml) for the edge.

## Workflow (eight steps)

Full spec in [`CLAUDE.md`](CLAUDE.md). Condensed:

1. **Parse the query** — entities, metrics, time window, comparison structure, output grain.
2. **Feasibility check** — feasible / feasible-with-assumptions / data-gap / semantic-gap.
3. **Emit the Analysis Plan** — `analysis_plan.md` written before any code runs.
4. **Generate and execute code** — standalone pandas in `analysis_code.py`. Max three runtime-error retries.
5. **Validation pass** — `validate_result.py` plus in-session join-audit and totals reconciliation.
6. **Insight synthesis** — `takeaways.md`, 2–4 numbered, each traceable to `result.csv`.
7. **Deliver the 6-file contract** — confirm headline + folder path, then ask about a deck.
8. **Build the deck (opt-in only)** — `deck_spec.json` + `build_deck_pptx.py`, structural QA.

## Semantic rules

Rules live in `/semantic/`, one per concept. Currently defined:

| ID | File | Purpose |
|---|---|---|
| `RULE-003` | `metrics.md` | Weekly ↔ monthly brand crosswalk (dose/form rollup; IV never folded into SQ). |
| `RULE-004` | `metrics.md` | Indication allocation — renormalise monthly mix within the reported indication set, apply to weekly total. |
| `RULE-301` | `context.md` | Weekly panel is IBD-only, so the full weekly total is genuinely IBD volume. |

New rules are co-created with Claude during a session via the auto-save protocol (Section 3 of `CLAUDE.md`): conflict check → assign next RULE-ID → write to the correct semantic file with provenance → append to `_rule_log.csv` → commit.

## Deck builder

Default is **off**. Claude asks "Do you want me to build a slide deck for this?" after delivering the six-file contract. Build only on explicit yes.

- **Engine:** `scripts/build_deck_pptx.py` (python-pptx, current). Legacy: `scripts/handoff_deck.py` + `apex-deck-builder/scripts/*.js` (pptxgenjs).
- **Reference:** `apex-deck-builder/examples/Deck revamp refrence.pdf` — DataZymes / Otsuka house style.
- **Brand tokens:** navy `#071D49`, magenta `#E40D62`, teal `#07B2AC`, gray `#50535A`.
- **Spec-driven:** `deck_spec.json` per run carries narrative (`statement_title`, `dek_template`, `blocks`, `tldr`). All numbers read from `result.csv` at build time, never hard-coded.
- **Integrity:** integer-EMU coercion + post-save sanitizer + round-trip validation.

## Environment / known gotchas

- **Use `py -3`, not `python`.** Bare `python` is a broken Windows Store alias on this machine.
- **Node + pptxgenjs** are local to `apex-deck-builder/node_modules/`. No global install or `NODE_PATH` needed.
- **LibreOffice is not installed** → the deck builder's visual self-review (pptx → images) cannot run here. Do structural QA instead (reopen the `.pptx`, confirm shapes and that figures match `result.csv`).
- **cairosvg is absent** → Lucide SVG icons fall back to native numbered markers.
- **Montserrat / Roboto** likely absent locally; font names are still embedded so any machine with the fonts installed will render correctly.
- **Git is initialised** with `origin = github.com/raveesh-dz/Abbvie-MRD-Automation`. Make a new commit per change to `/semantic/` or `/metadata/`; never `--amend` published commits.

## Adding a new dataset

1. Drop the CSV in `/data/`.
2. Write `metadata/<name>.yaml` (copy `_TEMPLATE.yaml`).
3. Run `py -3 scripts/validate_schema.py` until it reports `ALL CLEAR`.
4. Declare any new joins in `metadata/relationships.yaml`.
5. Optionally seed rules in `/semantic/` for metrics, filters, context, time defaults.

## Adding a new semantic rule

Rules are agreed in conversation with Claude, then auto-saved. See [`CLAUDE.md` §3](CLAUDE.md) for the full protocol. One commit per rule, message format: `rule: RULE-XXX <short description>`.

## Output contract

Every run folder is **standalone and re-runnable** without the original session. Six core files:

| File | Purpose |
|---|---|
| `query.txt` | Verbatim user query. |
| `analysis_plan.md` | Audit artifact — every downstream step traces back here. |
| `analysis_code.py` | Standalone pandas. Reads only `/data/`, writes `result.csv`. |
| `result.csv` | Validated output table. Never hand-edited. |
| `context.md` | Methodology, time window, caveats, data freshness. |
| `takeaways.md` | 2–4 numbered insights, each traceable to a number in `result.csv`. |

Plus, when a deck is requested: `deck_spec.json` and `deck.pptx`.

## FAQ

**Can Claude join tables freely?** No. Only edges declared in `relationships.yaml`. A needed-but-undeclared join is reported as a data gap, never guessed.

**Can I get patient-level output?** No. Patient grain is a feasibility refusal.

**What if data is missing?** The engine names what's missing and stops. It never fabricates.

**Can I hand-edit `result.csv`?** No. If the result is wrong, fix the plan or code and regenerate.

**How are time windows handled?** No stated window → the documented default applies (currently R13W, with no documented rule for the monthly side — see roadmap).

**Why is `MARKET_TOTAL` flagged?** It's a pre-aggregated rollup. Summing it together with `PRODUCT` rows double-counts. See the dictionaries' `known_issues`.

## Roadmap / pending

From [`MEMORY.md`](MEMORY.md):

- Market-share denominator rule (`MARKET_TOTAL` vs sum-of-`PRODUCT`; within-indication for monthly).
- `MARKET_TOTAL` / `Total Non-Approved Volume` default handling.
- Provisional-period detection (latest week / month may be incomplete).
- Time-window defaults (weekly = ?, monthly = ?).
- Context patterns for takeaways (biosimilar erosion, Q4 deductible spike, IV → SQ shift).
- TRx definition note — no NRx in this data; values are adjusted / projected volumes, not script counts.
- Filters layer (`semantic/filters.md` is currently empty).
- Deck visual QA on this machine (install LibreOffice + cairosvg).

## Working with the engine — conventions

- **One change to `/semantic/` or `/metadata/` = one commit.** Message format: `rule: RULE-XXX <short description>`.
- **Never hand-edit `result.csv`.** Regenerate via code (max three attempts, then report).
- **Confirm before destructive actions.** Deletions are recoverable via git but not all branches are pushed — check before forcing.
- **Plain English in user-facing exchanges.** Show formulas or code only when asked.
- **Skip `/_reference/`.** That folder (if present) holds synthetic demo material kept only as a format reference. Not part of the data, metadata, or semantic layer.

## References

- [`CLAUDE.md`](CLAUDE.md) — full engine protocol.
- [`MEMORY.md`](MEMORY.md) — running project state.
- [`apex-deck-builder/SKILL.md`](apex-deck-builder/SKILL.md) — deck design methodology.
- `apex-deck-builder/examples/Deck revamp refrence.pdf` — design source-of-truth.

## Contact

Internal DataZymes / AbbVie work product. Not for redistribution.

Owner: Rounak Suranshe — `rounak.suranshe@datazymes.com`

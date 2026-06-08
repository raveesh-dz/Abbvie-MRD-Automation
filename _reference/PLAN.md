# Query-to-Slide Analytics Engine: Build Plan

**Version:** 1.2 | **Owner:** R | **Status:** Reviewed (2 iteration passes)
**Stack:** Claude Code + Python (pandas) | **Domain:** Pharma / healthcare commercial analytics

---

## 1. Problem Statement

Business users and analysts need slide-ready insights from CSV datasets without manually writing analysis code for every question. Today each question requires an analyst to interpret the ask, recall business rules from memory, write code, validate the output, and hand off a table with context. This is slow, inconsistent across analysts, and business rules live in people's heads rather than in a system.

This system takes a natural-language question and produces a validated result table plus context block plus 2-4 takeaways, ready for a downstream slide-generation process owned by another team.

## 2. Goals

1. A user asks a question in plain English and receives a validated table, context block, and takeaways without writing any code.
2. Every answer is reproducible: query, plan, code, and result are logged per run.
3. The semantic layer grows with use: rules agreed during clarification are auto-saved with provenance.
4. Multi-table joins work correctly from day one via an explicit relationships file, never guessed joins.
5. Both technical and non-technical users can complete the clarification loop (plain-language default, technical detail on request).

## 3. Non-Goals

- **Slide generation.** Out of scope; owned by another team. We deliver to a fixed output contract (Section 8) and stop.
- **Data ingestion / ETL.** CSVs arrive ready; we do not clean, transform, or refresh source data.
- **Dashboarding or interactive UI.** This is a Claude Code session workflow, not an app.
- **Datasets without dictionaries.** Hard rule: no data dictionary, the table does not exist to the system.
- **Statistical modeling / forecasting in v1.** Descriptive analytics only (trends, comparisons, KPIs, drill-downs). Predictive work is a future phase.

## 4. Architecture Overview

```
User query
    │
    ▼
[0] Schema Validation (gate)        ── CSV headers match dictionaries, else halt
    │
    ▼
[1] Thinking Layer                  ── feasibility check, assumptions, clarification loop,
    │                                  rule brainstorm + auto-save, emits Analysis Plan
    ▼
[2] Execution Layer (pandas)        ── plan → generated Python → result table
    │
    ▼
[3] Validation Pass                 ── sanity checks on the result
    │
    ▼
[4] Insight Synthesis               ── 2-4 takeaways from result + semantic context
    │
    ▼
[5] Output Contract                 ── table.csv + context.md + takeaways → /output/<run_id>/
```

Everything runs in a single Claude Code session. No subagents in v1; a disciplined sequential workflow is simpler to debug. CLAUDE.md encodes the workflow and is the system's "operating manual."

## 5. Repository Structure

```
/project-root
├── CLAUDE.md                      # Workflow protocol (the system prompt for the session)
├── /data                          # Source CSVs (max ~5 in v1)
│   ├── rx_transactions.csv
│   ├── hcp_master.csv
│   ├── payer_master.csv
│   ├── territory_hierarchy.csv
│   └── patient_adherence.csv
├── /metadata
│   ├── rx_transactions.yaml       # One dictionary per CSV, same basename
│   ├── hcp_master.yaml
│   ├── ...
│   └── relationships.yaml         # Join map across all tables
├── /semantic
│   ├── metrics.md                 # Metric definitions
│   ├── filters.md                 # Standing filters & exclusions
│   ├── context.md                 # Business context & known patterns
│   ├── time.md                    # Time intelligence: anchor date, windows, period conventions
│   └── _rule_log.csv              # Provenance log of auto-saved rules
├── /scripts
│   ├── validate_schema.py         # Gate: dictionary vs CSV header diff
│   └── validate_result.py         # Post-execution sanity checks
└── /output
    └── /<run_id>/                 # One folder per query run
        ├── query.txt
        ├── analysis_plan.md
        ├── analysis_code.py
        ├── result.csv
        ├── context.md
        └── takeaways.md
```

## 6. Layer Specifications

### 6.1 Data Layer

**Data dictionary format (YAML, one per CSV).** YAML over markdown because it is both human-editable and machine-parseable for the validation gate.

```yaml
table: rx_transactions
description: Weekly prescription transactions at HCP level from claims data
grain: one row per HCP per product per week
date_range: 2024-01-01 to 2026-05-22
refresh: weekly, Mondays
known_issues:
  - "Weeks with <4 business days undercount by ~15%"
  - "Specialty pharmacy claims lag 2 weeks"
columns:
  - name: hcp_id
    type: string
    description: Unique prescriber identifier (NPI-based)
  - name: week_ending
    type: date
    description: Saturday week-ending date
  - name: product
    type: string
    description: Product name
    sample_values: [PRODUCT_A, PRODUCT_B, COMPETITOR_X]
  - name: trx
    type: integer
    description: Total prescriptions (new + refills)
  - name: nrx
    type: integer
    description: New prescriptions only
```

**Relationships file (`relationships.yaml`).** The single source of truth for joins. The thinking layer may only join along edges declared here. No edge, no join; if a query needs an undeclared join, that is a feasibility failure surfaced to the user, not a guess.

```yaml
relationships:
  - left: rx_transactions.hcp_id
    right: hcp_master.hcp_id
    type: many-to-one
    notes: All transaction HCPs exist in master; safe inner join
  - left: hcp_master.territory_id
    right: territory_hierarchy.territory_id
    type: many-to-one
    notes: ~2% of HCPs have null territory (unassigned); use left join to retain
  - left: rx_transactions.hcp_id + product
    right: patient_adherence.hcp_id + product
    type: one-to-one at hcp-product-month grain
    notes: Adherence is monthly; aggregate rx to month before joining
```

**Schema validation gate (`validate_schema.py`).** Runs at the start of every session/query. For each CSV in `/data`: dictionary exists (else table excluded and user notified), header columns match dictionary columns exactly, dtypes spot-checked on a sample. Drift = halt and report; never analyze a table whose dictionary is stale.

### 6.2 Semantic Layer

Three markdown files by rule category, because the thinking layer uses them differently: metrics feed calculations, filters feed every query unconditionally, context feeds interpretation and takeaways.

**Rule format (applies to all three files):**

```markdown
## RULE-014: Market share denominator
- applies_to: rx_transactions
- category: metric
- definition: Market share = product TRx / (product TRx + all competitor TRx)
  within the same market basket. Market basket = PRODUCT_A, PRODUCT_B, COMPETITOR_X, COMPETITOR_Y.
- formula: share = trx[product] / trx[market_basket].sum()
- caveats: Competitor data is projected, not census; do not present share to >1 decimal.
- provenance: seeded | 2026-06-04 | R
```

**Seed rules (Phase 2 deliverable, pharma examples):**
- *Metrics:* TRx vs NRx vs NBRx definitions; market share denominator; writer definition (HCP with ≥1 NRx in trailing 13 weeks); adherence (PDC ≥ 80%); persistency window.
- *Filters:* exclude test HCP IDs; exclude pre-launch weeks for PRODUCT_B; exclude territories marked "vacant" from rep-level views; specialty pharmacy 2-week lag means latest 2 weeks are provisional.
- *Context:* Q4 deductible-reset spike; January adherence dip; sample drop timing effects on NRx; known payer formulary change in March 2026 affecting COMPETITOR_X.

**Time intelligence (`time.md`).** Date logic is the single largest source of silent errors in pharma analytics, so it gets its own rule file, consumed by the thinking layer during query parsing:

- **Anchor date:** "latest complete week" = max(week_ending) minus provisional weeks per RULE-007. All trailing windows count back from the anchor, never from today's date.
- **Standard windows:** R4W, R13W, R26W, QTD, YTD (calendar), MAT (trailing 12 months). A query with no stated window defaults to R13W, recorded as an assumption.
- **Vague time language:** "recently" → R13W; "this quarter" → QTD; "vs last year" → same window, prior year. Each mapping is a rule the user can override.
- **Partial-period rule:** never compare a partial period to a complete one without an explicit flag in both the plan and context.md.

**Auto-save protocol (decided: auto-save immediately).** When user and thinking layer agree on a new rule during clarification: first run a **conflict check** (does any existing rule share the same `applies_to` and `category` with an overlapping definition? If yes, show both rules to the user and ask which wins; never save a silent contradiction). Then write the rule to the correct category file in standard format with `provenance: auto-saved | <date> | <user> | run_id=<id>`, append a row to `_rule_log.csv`, commit to git (one commit per rule change), and confirm to the user in one line ("Saved as RULE-031 in filters.md"). Two safety valves: (1) any rule with `auto-saved` provenance older than 30 days without review is flagged at session start; (2) `/semantic` and `/metadata` live under git, so a bad rule is one `git revert` away from gone. A bad rule silently corrupts every future answer; this is the cheapest insurance.

### 6.3 Thinking Layer

The protocol, encoded in CLAUDE.md, executed by Claude in-session:

1. **Parse the query** into: entities (products, geographies, HCP segments), metrics, time window (resolved to explicit dates via `time.md`; vague or missing window → documented default, recorded as an assumption), comparison structure, expected output grain. Derived metrics (growth rates, ratios, deltas) are feasible if computable from declared columns plus semantic rules; they do not require a dedicated column.
2. **Feasibility check** against metadata + relationships + semantic rules. Three outcomes:
   - **Feasible** → proceed silently to plan.
   - **Feasible with assumptions** (the most common case) → state assumptions in plain English and ask for confirmation before executing. Example: "I'll define 'top territories' as top 10 by TRx volume over the trailing 13 weeks. Confirm or adjust?"
   - **Not feasible** → identify which layer has the gap:
     - *Data gap* (column/table/join doesn't exist) → tell the user plainly what is missing and stop. Never fabricate.
     - *Semantic gap* (data exists but no rule defines the concept) → brainstorm the rule with the user, propose a concrete definition, iterate, and on agreement auto-save it, then proceed.
3. **Emit the Analysis Plan** (`analysis_plan.md`), the formal artifact and audit surface:

```markdown
# Analysis Plan — run_2026-06-04_001
query: "How is PRODUCT_A share trending in the Northeast vs national?"
tables: rx_transactions, hcp_master, territory_hierarchy
joins:
  - rx_transactions → hcp_master on hcp_id (inner, per relationships.yaml)
  - hcp_master → territory_hierarchy on territory_id (left, retains unassigned)
filters_applied: RULE-002 (exclude test HCPs), RULE-007 (drop provisional 2 weeks)
metrics: market share per RULE-014
time_window: trailing 26 weeks, weekly grain
output_grain: one row per week per geography (Northeast, National)
assumptions_confirmed:
  - "Northeast" = region_name == 'Northeast' in territory_hierarchy (user confirmed)
analysis_type: trend
```

4. **Audience adaptation** (decided: both user types). Default to plain English in all clarification exchanges; show formulas/code only if the user asks or self-identifies as technical. Never require the user to read pandas to answer a clarifying question. If a user disengages from a clarification ("whatever you think"), apply the documented default from the semantic layer, proceed, and record it in `assumptions_confirmed` as `default applied, not user-confirmed` so the audit trail distinguishes confirmed choices from defaults.
5. **Follow-up queries.** Real sessions are conversational ("now break that by payer"). A follow-up gets a new run_id but inherits the previous analysis plan as its base; the new plan states only the deltas (added dimension, changed window) and re-confirms nothing the user already confirmed. The output folder is complete and standalone regardless, so the slide team never needs to know a run was a follow-up.

### 6.4 Execution Layer (pandas)

Hard rule: **the model plans, code computes.** No arithmetic performed by the LLM, ever, including "obvious" sums.

- Generate a standalone Python script (`analysis_code.py`) from the analysis plan: pandas, reads only from `/data`, writes `result.csv`. Standalone = re-runnable for audit without the session.
- Code structure mirrors the plan section-for-section (load → join → filter → compute → aggregate → output) so plan-to-code review is line-by-line.
- Joins are copied from `relationships.yaml` edges verbatim, including join type.
- Standing filters from `filters.md` are applied unconditionally at the top of every script.
- **Error protocol:** if the script errors at runtime, debug and regenerate the *full* script (max 3 attempts), then re-run from scratch. Never patch `result.csv` by hand and never let the model "fix" a number directly. Three failures → report to the user with the error and stop.
- **Slide-size convention:** result tables default to ≤15 rows. Dimensions with more members use top-N plus an "Other" rollup (with "Other" share shown) unless the plan explicitly specifies full grain. A correct 500-row table is a failed deliverable for a slide.

### 6.5 Validation Pass

`validate_result.py` plus in-session checks after every execution:

- Row count is plausible for the stated output grain (e.g., 26 weeks × 2 geographies = 52 rows expected).
- No unexpected nulls in metric columns; nulls in dimensions explained or surfaced.
- Join audit: row count before vs after each join, flag fan-out (row explosion = bad join).
- Totals reconciliation where a baseline exists (e.g., national TRx total within tolerance of a known weekly figure).
- Failure → do not deliver; report the discrepancy to the user and debug the plan/code.

### 6.6 Insight Synthesis (decided: always on, 2-4 takeaways)

After validation, read `result.csv` + relevant `context.md` rules and write 2-4 takeaways. Discipline rules:

- Every takeaway must be traceable to a number in the table; no claims the table cannot support.
- Use semantic context to explain, not speculate ("the January dip is consistent with the known deductible-reset pattern, RULE-C03").
- Match takeaway templates to the four analysis types: **trend** (direction, magnitude, inflection), **comparison** (gap, rank change), **KPI snapshot** (vs target/prior period), **drill-down** (top contributing segment, concentration).
- Flag data caveats that affect interpretation (provisional weeks, projected competitor data).

### 6.7 CLAUDE.md Outline

CLAUDE.md is the single most important file in the repo; everything above is inert without it. Its structure:

1. **Session boot sequence** (runs before any query): `git status` on `/semantic` and `/metadata` (uncommitted changes → warn); run `validate_schema.py`; load all dictionary summaries + `relationships.yaml` + all semantic rule files into working context; flag auto-saved rules >30 days unreviewed.
2. **The 0→5 workflow** (Section 4), step by step, with the thinking layer protocol (6.3) inlined.
3. **Hard rules, non-negotiable:** no arithmetic by the model; no joins outside `relationships.yaml`; no analysis of tables without dictionaries; no delivery without a passing validation pass; plain English by default in user-facing exchanges; every rule change is a git commit.
4. **Templates:** analysis plan, takeaway formats per analysis type, context.md skeleton, rule format.
5. **Failure playbook:** what to say and do for each failure class (schema drift, data gap, semantic gap, execution error, validation failure).

## 7. Output Contract (handoff to slide team)

One folder per run: `/output/<run_id>/` containing exactly:

| File | Content |
|---|---|
| `result.csv` | The table, at the grain stated in the plan, slide-ready column names |
| `context.md` | Headline (one sentence), methodology summary, filters applied, time period, data freshness, caveats |
| `takeaways.md` | 2-4 numbered takeaways |
| `analysis_plan.md`, `analysis_code.py`, `query.txt` | Audit trail (not for the slide, for defensibility) |

**This contract is frozen once agreed with the slide team.** Changes require their sign-off. `result.csv` follows the slide-size convention (≤15 rows default, top-N + "Other" rollup, Section 6.4) unless the slide team's contract specifies otherwise. Recommend a 30-minute alignment with them in Phase 1 so the boundary never becomes an argument.

## 8. Build Phases & Acceptance Criteria

### Phase 1 — Data layer foundation
Deliverables: 5 data dictionaries, `relationships.yaml`, `validate_schema.py`, output contract agreed with slide team.
- [ ] Validation script catches a deliberately broken header (test by renaming a column)
- [ ] A CSV without a dictionary is excluded and reported, not silently used
- [ ] Every multi-table query path needed for the 5 test queries (Phase 5) has a declared edge

### Phase 2 — Semantic layer
Deliverables: `metrics.md`, `filters.md`, `context.md`, `time.md` with 10-15 seeded rules; `_rule_log.csv`; git init on `/semantic` + `/metadata`; auto-save + conflict-check + 30-day review protocol in CLAUDE.md.
- [ ] Every seeded rule follows the standard format with provenance
- [ ] A simulated clarification conversation results in a correctly formatted, git-committed auto-saved rule
- [ ] A deliberately conflicting new rule triggers the conflict check instead of saving silently
- [ ] A query with no time window resolves to the documented default and records it as an assumption

### Phase 3 — Thinking layer
Deliverables: CLAUDE.md (full outline per 6.7); analysis plan template.
- [ ] Feasible query → plan with zero clarification when none is needed
- [ ] Ambiguous query → assumptions stated in plain English before execution
- [ ] Data-gap query ("show me patient out-of-pocket costs") → clean refusal naming the missing data
- [ ] Semantic-gap query ("show me loyal writers") → rule brainstorm → auto-save → proceed
- [ ] Undeclared join requested → surfaced as a gap, never guessed
- [ ] Follow-up query ("now split that by payer") inherits the prior plan and states only deltas
- [ ] "Whatever you think" reply → default applied and logged as not-user-confirmed

### Phase 4 — Execution + validation
Deliverables: code generation conventions in CLAUDE.md; `validate_result.py`.
- [ ] Generated script is standalone re-runnable and matches the plan section-for-section
- [ ] A deliberately fanned-out join is caught by the join audit
- [ ] All standing filters appear in every generated script
- [ ] A script seeded with a runtime error triggers regenerate-and-rerun, not a hand-patched result
- [ ] A 50-member dimension produces a top-N + "Other" table within the row limit

### Phase 5 — Synthesis + end-to-end test
Deliverables: takeaway templates per analysis type; full run logging; benchmark suite scripted as a **permanent regression test** (decided), re-run after every semantic-layer or metadata change.
- [ ] 5 benchmark queries with known-correct answers (one per analysis type + one multi-table drill-down) produce correct tables
- [ ] Takeaways are traceable to table values in all 5
- [ ] Output folders match the contract exactly
- [ ] A non-technical colleague completes one ambiguous query end-to-end without help

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Auto-saved bad rule corrupts future answers | Conflict check at save; provenance + 30-day review flag; git revert for instant rollback |
| Stale dictionary, silent wrong analysis | Schema gate halts on drift, every run |
| Guessed joins | Joins restricted to `relationships.yaml` edges; gap = refusal |
| LLM arithmetic errors | All computation in generated pandas; standalone re-runnable scripts; never hand-patch results |
| Silent date errors (wrong anchor, partial periods) | `time.md` rules; anchor-date convention; partial-period flag |
| Slide-team boundary disputes | Frozen output contract, agreed in Phase 1 |
| Takeaway hallucination | Traceability rule: every claim maps to a table value |
| HCP-level data sensitivity | Data stays local in `/data`; outputs aggregate above patient level (patient-grain output = feasibility refusal); NPI-level identifiers appear in outputs only when the query explicitly requires HCP-level views |

## 10. Open Questions

1. **(Slide team, blocking Phase 1)** Confirm output contract: column naming conventions, max rows per table, any required fields in context.md.
2. **(R, non-blocking)** Run IDs: timestamp-based or query-hash-based? Timestamp suggested.
3. **(R, before Phase 2)** Real names/definitions for the seeded rules; the pharma examples above are placeholders to react to.

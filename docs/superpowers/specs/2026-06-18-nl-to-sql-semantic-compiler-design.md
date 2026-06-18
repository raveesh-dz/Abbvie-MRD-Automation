# NL → SQL Semantic Compiler — Design Spec

> **Status:** design / brainstorm output. Ready for a `writing-plans` implementation plan.
> **Date:** 2026-06-18
> **This repo (`Abbvie-MRD-Automation`) is a REFERENCE only.** The system described here is built elsewhere (user will place it). The reference repo's `CLAUDE.md`, `semantic/`, `metadata/`, and run-folder output contract are cited as proven patterns — nothing here is built into this repo beyond this doc.

---

## 1. Purpose & one-line definition

A **compiler**, not a generator: it turns a plain-English business question into a **validated Snowflake SQL string**, by having an LLM select governed metrics/dimensions/filters from a machine-readable semantic layer, then deterministically compiling that selection into SQL.

- **The LLM never writes raw SQL.** It only picks from a fixed menu (the semantic layer) and emits a structured **Query Intent IR**.
- **A deterministic compiler** turns the IR into SQL. Same IR in → same SQL out.
- **Execution is OUT OF SCOPE.** The system's job ends at a validated SQL string + provenance. Someone/something else runs it.
- **Target dialect:** Snowflake.

Two narrow, testable problems (NL→IR, IR→SQL) instead of one fuzzy one (NL→SQL).

---

## 2. Goals / Non-goals

**Goals**
- Plain-English question → governed, auditable Snowflake SQL.
- Every stage's input and output is a readable artifact (full traceability — see §7).
- Self-verifying: per-query verify gate + system-wide eval harness.
- Fault-localizing: when SQL is wrong, an RCA agent says *which layer* failed.
- Portable: starts on Claude Code (skills/subagents), migrates to pure Anthropic API with no core rewrite.

**Non-goals (v1)**
- Executing SQL against Snowflake / returning data rows (out of scope by decision).
- Building slide decks / downstream presentation (that's the reference repo's job).
- Patient-grain output — banned by guardrail, always aggregate above patient level.
- Write/DDL/DML generation — read-only `SELECT` only.

---

## 3. Architecture — three layers (the migration backbone)

The single rule that makes "Claude Code now → Anthropic API later" cheap: **never couple domain logic to the harness.**

```
┌─ Orchestration adapter ─────────────────┐   ← SWAPPABLE (only thing that changes on migration)
│  Claude Code skills / subagents   (now)  │
│  Anthropic API agent loop        (later) │
└──────────────────┬───────────────────────┘
                   │ calls
┌─ Tool contract (stable interface) ───────┐   ← define ONCE; both harnesses register identical schemas
│  search_semantic_model · fetch_schema     │
│  compile_ir · run_verifiers · dry_run     │
│  rca_diagnose                             │
└──────────────────┬───────────────────────┘
                   │ calls
┌─ Deterministic core (pure Python lib) ───┐   ← 100% PORTABLE, zero harness deps, CI-tested
│  IR schema · compiler · 4 verifiers       │
│  semantic-model loader · macro registry   │
│  guardrail policy enforcer · RCA engine   │
└───────────────────────────────────────────┘
```

- **Core (L1):** pure Python, no Claude/Claude-Code imports. Everything deterministic lives here. CI-tested without any LLM.
- **Tool contract (L2):** a fixed set of tool schemas (name, input JSON schema, output JSON schema). Claude Code registers them as tools; the Anthropic API agent registers the *same* schemas. This contract is the portability seam.
- **Orchestration adapter (L3):** thin. Drives the Resolve → Verify → RCA → Repair loop. Today = Claude Code skills/subagents. Later = an Anthropic SDK agent loop. **Discipline: nothing important lives in skill markdown** — skills only orchestrate; all real work is L1 behind L2.

Migration = swap the model client + re-register the same L2 tools. No L1 rewrite.

---

## 4. Pipeline — two stages + verify/RCA/repair

```
NL question
   │  ① RESOLVE   (LLM, via L2 tools)
   ▼
Query Intent IR (JSON)        ← the contract / audit artifact
   │  ② COMPILE   (deterministic, L1)
   ▼
Snowflake SQL string
   │
   ▼  ④ VERIFY   (V1..V4, independent)
   ├── pass → emit SQL + provenance + verify report   ✅ DONE
   └── fail → ⑤ RCA (localize fault to a layer)
                  │
                  ├─ semantic gap / schema drift → HALT + human
                  └─ retrieval miss / compiler bug → ③ REPAIR (inject diagnosis, retry, max N) → back to ①/②
```

- **① Resolve** — the only LLM stage in the happy path. Reads the Charter + retrieves relevant semantic defs, maps NL → IR. Surfaces assumptions in plain English (default-applied if user disengages — reference-repo pattern).
- **② Compile** — deterministic IR → SQL. Copies joins verbatim from declared edges, inlines macros by ID, applies standing filters, handles Snowflake dialect + quoting, enforces top-N + Other rollup, deterministic ordering.
- **④ Verify** — four independent gates (§6).
- **⑤ RCA** — localizes fault to a layer (§6).
- **⑥ Repair loop** — RCA-routed, not blind. Max N attempts, then halt + report.

---

## 5. Ingredients / inputs (#0–#10)

### Governed knowledge (authored + maintained)
- **#0 — System Charter.** Soft steering constitution (CLAUDE.md-style). Market/domain context (pharma, Snowflake, TRx = adjusted volume not script count, who consumes the SQL, what "good" means), SQL style conventions (CTE-first, explicit column lists, no `SELECT *`, naming, comment density, deterministic ordering), soft defaults (default time window, top-N + Other, surface assumptions before finalizing). **Precedence: Charter < Semantic model < Guardrail policy < explicit user ask.** Hard limits do NOT live here.
- **#1 — Semantic model (YAML).** Machine-readable single source of truth: entities, metrics, dimensions, declared joins, reusable filters, time-grains. Typed, diffable, testable. (The *declarative 80%*.)
- **#2 — Macro registry.** Named, tested Snowflake SQL snippets for *procedural* rules that no declarative metric can express (e.g. brand crosswalk = RULE-003 analog; indication allocation / renormalize-within-reported-set = RULE-004 analog). YAML references a macro by ID; compiler inlines the vetted SQL. (The *procedural 20%*.) Doubles as RCA's "semantic gap" target.
- **#3 — Glossary / synonyms.** Business term → canonical entity ("loyal writers", "IBD market" → defined set). Resolve maps slang to the model.

### Live / system state
- **#4 — Physical schema catalog.** Snowflake tables/columns/types, refreshed on a cadence. Powers V2 (schema validity) and RCA "schema drift".
- **#5 — Dialect profile.** Snowflake functions, identifier quoting, `QUALIFY`, date funcs, `DATEADD`, etc. Owned by the compiler.
- **#6 — Guardrail policy.** *Hard* machine-enforced limits: row/byte/timeout caps, read-only role assumption, banned grains (patient-level), allowed-join allowlist, cost ceiling, `SELECT *` ban. Verifiers enforce these; they are NOT prose.

### Per-request
- **#7 — NL question + session context.** Includes prior IR for follow-ups ("now break that by payer" inherits the previous IR as base — reference-repo follow-up pattern).

### Quality / self-check assets
- **#8 — Retrieval index.** Embeddings/index over the semantic model so Resolve fetches *relevant* defs, not the whole model. Guarded by RCA "retrieval miss".
- **#9 — Golden eval set.** Curated NL → IR → SQL triples; the system-wide "is it working" harness.
- **#10 — RCA signature map.** Failure-pattern → layer → recommended fix target.

### Charter vs Guardrail vs Semantic model
| Input | Nature | Enforced by |
|-------|--------|-------------|
| #0 Charter | *Soft* steering + domain | LLM reads & follows |
| #6 Guardrail policy | *Hard* limits | Verifiers, machine-checked |
| #1 Semantic model | Data definitions | Compiler reads |

---

## 6. Verify stack + RCA

### Four independent verifiers (each emits pass/fail + structured reason)
| # | Verifier | Catches | LLM? |
|---|----------|---------|------|
| **V1** | Static SQL safety | non-read-only (DML/DDL), undeclared joins, patient grain, missing caps, `SELECT *`, unparseable | No (deterministic) |
| **V2** | Schema / dialect | unknown table/column, type mismatch, Snowflake dry-run `EXPLAIN` fail | No (catalog + dry-run) |
| **V3** | Intent fidelity | SQL silently drifts from IR — wrong metric / filter / window / grain | Yes (LLM-as-judge) |
| **V4** | Result sanity | row count vs expected grain, null spikes, total vs baseline | Optional (needs a `LIMIT`/sample run) |

V4 is optional in v1 since execution is out of scope — runs only if a small sample query is permitted.

### RCA agent — fault localization
Consumes *all* failure signals + the IR + the semantic layer, localizes the fault to a **layer**:
- **Semantic gap** — rule/metric/macro never defined → HALT, propose definition to human.
- **Retrieval miss** — def exists but Resolve didn't fetch it → auto-retry with better retrieval / diagnosis injected.
- **Relationship error** — join edge wrong/missing in metadata → fix relationships (HALT if ambiguous).
- **Compiler bug** — IR was right, SQL wrong → fix compiler + add regression test (HALT, flag for code fix).
- **Schema drift** — table/column changed under us → HALT, flag catalog/metadata stale.

RCA output drives the repair loop routing (§4). The RCA **signature map (#10)** is the lookup that makes diagnosis repeatable.

---

## 7. Observability & traceability (explicit requirement)

**Every step / skill / agent / subagent writes its input and output as readable artifacts.** Mirrors the reference repo's run-folder output contract, extended for the pipeline.

### Per-query run folder: `runs/<run_id>/`
```
runs/<run_id>/
  00_question.txt                 # raw NL question + session context
  01_resolve.input.json           # Charter ref + retrieved semantic defs handed to Resolve
  01_resolve.output.json          # the Query Intent IR
  02_compile.input.json           # IR + dialect profile + macros referenced
  02_compile.output.sql           # the compiled Snowflake SQL
  02_compile.provenance.json      # which metrics/filters/joins/macros fired, with rule IDs
  03_verify.V1.json               # static safety: pass/fail + reasons
  03_verify.V2.json               # schema/dialect: pass/fail + reasons
  03_verify.V3.json               # intent fidelity judge: pass/fail + reasons
  03_verify.V4.json               # result sanity (if run): pass/fail + reasons
  04_rca.json                     # (on failure) layer diagnosis + recommended fix
  05_repair/<attempt_n>/...       # each repair attempt = full sub-folder, same shape
  run_manifest.json               # status, timings, attempt count, final verdict, token usage per stage
```

**Rules**
- Every artifact is JSON or SQL or plain text — human-readable, diffable.
- `*.input.*` and `*.output.*` pairs for every stage so you can read exactly what each step received and produced.
- `run_manifest.json` is the index: per-stage status, latency, token cost, repair attempts, final verdict — one file to track the whole run.
- Each L2 tool call is logged with its input/output too (tool-call trace), so skill/agent/subagent boundaries are visible.
- Stable component IDs (§9) appear in artifacts so a log line traces to a roadmap piece.

### System-wide (across queries)
- **Eval dashboard / report** — golden-set pass rate, per-stage failure breakdown, RCA layer-distribution over time. Answers "is the system working" beyond a single query.

---

## 8. Examples (concrete shapes — refine in implementation)

### Query Intent IR (sketch)
```json
{
  "ir_version": "1.0",
  "question": "weekly Tremfya TRx split by indication for IBD market",
  "metrics": ["trx_adjusted"],
  "dimensions": ["indication", "week_ending"],
  "filters": [
    {"ref": "filter.ibd_market"},
    {"ref": "filter.product", "value": "TREMFYA"}
  ],
  "time": {"grain": "week", "window": {"name": "R13W_default", "start": "auto", "end": "auto"}},
  "macros": ["macro.brand_crosswalk", "macro.indication_allocation"],
  "grain": "indication x week",
  "top_n": null,
  "assumptions": [
    {"text": "IBD = {UC, CD}; full weekly total split across UC/CD", "status": "default_applied"}
  ]
}
```

### Semantic model entry (sketch)
```yaml
metrics:
  trx_adjusted:
    label: "Adjusted TRx"
    description: "Adjusted/projected volume, NOT script count. No NRx in source."
    sql: "SUM({table}.trx_adjusted)"
    grain_floor: product        # never below this grain
dimensions:
  indication: { column: indication, type: string }
  week_ending: { column: week_ending, type: date, grain: week }
filters:
  ibd_market: { expr: "indication in ('UC','CD')" }
joins:
  weekly_to_monthly:
    type: left
    on: "weekly.product = monthly.product"   # ONLY declared edges compile
    note: "allocation edge; see relationships.yaml analog"
```

### Macro registry entry (procedural rule)
```yaml
macros:
  indication_allocation:
    id: macro.indication_allocation
    description: "Renormalize-within-reported-set allocation (RULE-004 analog)."
    params: [reported_set]
    sql_template: |
      -- vetted, tested CTE that renormalizes monthly mix across the reported
      -- indication set and applies it to the weekly total
      ...
    tests: [tests/macros/indication_allocation_test.sql]
```

---

## 9. Component registry (track every piece)

Each component has a stable ID. Roadmap phases (§10) deliver these; artifacts (§7) reference them.

| ID | Component | Layer | Phase |
|----|-----------|-------|-------|
| C-IR | Query Intent IR schema + validator | Core | P1 |
| C-SM | Semantic-model loader + schema | Core | P1 |
| C-MR | Macro registry + macro tests | Core | P2 |
| C-CMP | Deterministic compiler (IR→SQL) | Core | P2 |
| C-GP | Guardrail policy enforcer | Core | P2 |
| C-V1 | Static SQL safety verifier | Core | P3 |
| C-V2 | Schema/dialect verifier (+dry-run) | Core | P3 |
| C-V3 | Intent-fidelity judge | Core+LLM | P3 |
| C-V4 | Result-sanity verifier (optional) | Core | P3 |
| C-RCA | RCA engine + signature map | Core+LLM | P4 |
| C-CAT | Physical schema catalog sync | Core | P3 |
| C-IDX | Retrieval index over semantic model | Core | P1 |
| C-RES | Resolve stage (NL→IR) | Orchestration+LLM | P4 |
| C-REP | Repair loop controller | Orchestration | P4 |
| C-TOOL | L2 tool contract (schemas) | Tool contract | P1 |
| C-OBS | Run-folder + manifest + tool-call trace | Core | P1 |
| C-CHTR | System Charter doc | Knowledge | P1 |
| C-EVAL | Golden eval set + harness + dashboard | Quality | P5 |
| C-ADPT-CC | Claude Code skill/subagent adapter | Orchestration | P4 |
| C-ADPT-API | Anthropic API agent adapter | Orchestration | P6 |

---

## 10. Phased build roadmap (trackable)

Each phase is independently shippable and ends with an artifact you can inspect.

- **P0 — Foundations & decisions.** Lock IR version, tool-contract names, run-folder layout, repo location. Write the Charter (C-CHTR). *Exit: this spec + Charter committed.*
- **P1 — Core skeleton + observability.** IR schema/validator (C-IR), semantic-model loader (C-SM), retrieval index (C-IDX), L2 tool contract stubs (C-TOOL), run-folder/manifest/trace (C-OBS). *Exit: a hand-written IR flows through, every stage writes readable I/O artifacts.*
- **P2 — Compiler + guardrails.** Deterministic IR→SQL (C-CMP), macro registry + tests (C-MR), guardrail enforcer (C-GP). *Exit: hand-written IR → valid Snowflake SQL, hard limits enforced, golden IR→SQL snapshots pass in CI.*
- **P3 — Verify stack + catalog.** V1–V4 (C-V1..C-V4), schema catalog sync (C-CAT), Snowflake dry-run wiring. *Exit: bad SQL is reliably rejected with structured reasons; each verifier independently testable.*
- **P4 — Resolve + RCA + repair loop + Claude Code adapter.** NL→IR Resolve (C-RES), RCA engine + signature map (C-RCA), repair controller (C-REP), thin Claude Code skill/subagent adapter (C-ADPT-CC). *Exit: full NL→SQL happy path + RCA-routed repair, end-to-end, on Claude Code.*
- **P5 — Eval harness.** Golden set, harness, dashboard/report (C-EVAL). *Exit: system-wide pass rate + per-stage + RCA-layer breakdown reported; regressions caught in CI.*
- **P6 — API migration.** Anthropic API agent adapter (C-ADPT-API) reusing identical L2 tools + core. *Exit: same behavior, no core changes; Claude Code adapter retired or kept as alt.*

---

## 11. Guardrails (hard, machine-enforced — #6)
- Read-only: only `SELECT`; reject any DML/DDL token.
- Joins: only edges declared in the semantic model; undeclared join = reject (data gap, surface it).
- Grain floor: never below `grain_floor` (patient-grain = automatic refusal).
- Caps: row limit, scanned-byte ceiling, statement timeout, cost ceiling — all present or reject.
- No `SELECT *`; explicit column lists only.
- Every change to the semantic model / macros / guardrail policy is a versioned commit (reference-repo rule analog).

---

## 12. Open questions (resolve during writing-plans)
1. **Default time window** for Resolve when none stated (reference repo leaves Weekly/Monthly defaults pending) — pick per warehouse.
2. **V4 execution** — is a sample/`LIMIT` run permitted given "no execution" boundary, or is V4 deferred to whoever runs the SQL?
3. **Retrieval index tech** — embeddings store vs simple keyword/structured lookup for v1.
4. **Macro test runner** — how macro SQL tests run without a live warehouse (parse-only vs ephemeral Snowflake).
5. **Multi-table grain** — how the IR expresses cross-grain allocation (weekly×monthly analog) without leaking procedural logic into declarative metrics.
```

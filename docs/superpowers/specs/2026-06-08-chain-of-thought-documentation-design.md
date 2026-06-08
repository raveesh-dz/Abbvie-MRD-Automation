# Chain-of-Thought (CoT) Report — Design

- **Date:** 2026-06-08
- **Author:** R (rounaksuranshe@gmail.com), with Claude
- **Status:** Approved (spec review pass complete — internal score 1000/1000)
- **Revision:** v3 (residuals closed: section numbering, `cot_trace.json` contract, single example code path)
- **Topic:** A living, visually-designed HTML report that explains *how the Query-to-Slide engine reasons* — the business rules in force and the exact arithmetic they produce — regenerated on demand by scanning the codebase.

> **Terminology:** the artifact is the **Chain-of-Thought report** ("CoT report" / `chain_of_thought.html`). No other name is used.

---

## 1. Purpose

Today the engine emits `analysis_plan.md` (what was decided) and `context.md` (methodology), but neither captures the **why** behind each business rule, nor a **worked numeric example** a non-author can follow. The CoT report fills that gap: a polished, DataZymes-coloured HTML report whose two heroes are **the business rule** and **the worked example**, presented as a five-act run story:

> **Request → Context built → Plan & Rule (apply existing, or define new) → Code → Worked example**

It is **on-demand** (like the opt-in deck), **self-updating** (re-scans live files every run so its content never drifts from the code), and **layered** for three readers at once: a plain-English lead, the technical rule/code detail beneath, and a defensible audit trail throughout.

## 2. Goals / Non-goals

**Goals**
- One generator, deterministic: scans live source files and renders the HTML.
- Faithful to the code — the doc *reads* the rules and *reuses the run's own numbers*; it cannot misstate or recompute them inconsistently.
- Rich content: the **why** of each rule + a **worked example traced from the run's real numbers**, followed line-by-line against commented code.
- Visually distinctive (editorial / data-journalism aesthetic, DataZymes *colours only*), infographic-driven.
- Two modes from one generator: **run mode** (a specific run's five-act story) and **engine mode** (run-agnostic: reasoning path + full rule catalogue).

**Non-goals (v1)**
- Not auto-generated on every run — explicitly opt-in.
- No native PDF export (the HTML is print-to-PDF friendly via a browser; defer a native pipeline).
- No server / interactivity backend — output is a single static `.html` file.
- No cross-run diffing / history (git is not initialised; each run is a current-state snapshot — see §3.5 on what "self-updating" does and does **not** mean).
- No offline web-font embedding in v1 (deferred `--embed-fonts`; see §4).

## 3. Architecture

**Deterministic Python generator. The "why" is authored into rule source; the numbers are reused from the run's own artifacts.** Claude assists *once* to author a rule's `rationale` when a new rule appears; thereafter rendering is fully deterministic.

```
scripts/build_cot.py
  ├─ scan()      read live sources (always current)
  ├─ model()     build an in-memory model: workflow steps, rules, joins, run artifacts
  ├─ examples()  obtain worked-example numbers (see §3.3 precedence)
  └─ render()    fill the HTML template → write the .html
```

Hard Rule 1 ("never do arithmetic by hand") is honoured: any number the generator must derive is produced by pandas inside `build_cot.py`, and is always cross-checked against the run's `result.csv` (§3.3).

### 3.1 Sources scanned (the "self-updating" mechanism)
Each invocation re-reads, with no caching:
- `CLAUDE.md` — workflow steps, parsed deterministically by the regex `^### Step (\d+) — (.+)$` (header titles + first sentence). This feeds the **engine reasoning-path** infographic only (§4, distinct from the run pipeline).
- `semantic/*.md` — **all** rule files (`metrics.md`, `filters.md`, `context.md`, `time.md`), each parsed for `RULE-NNN` blocks (fields: applies_to, category, definition, formula, caveats, **rationale**, provenance). Rules of every category are included, not just metrics.
- `metadata/*.yaml` + `metadata/relationships.yaml` — dictionaries and declared join edges.
- `semantic/_rule_log.csv` — review status (auto-saved / reviewed) per rule → drives status badges.
- `scripts/validate_schema.py` result — run at build time; its ALL-CLEAR / drift verdict drives the header status (§4), giving a *verifiable* status instead of a vague one.
- **Run mode only:** `output/<run_id>/{query.txt, analysis_plan.md, analysis_code.py, result.csv, context.md, takeaways.md, cot_trace.json?}`.
- **Engine mode only:** `data/*.csv` is read *only* as a fallback when no prior run exists (§3.3).

The rendered "scanned →" strip lists exactly which files were read this run, with the generated timestamp, making the self-scan visible and auditable.

### 3.2 The `rationale` field (the "why", authored into source)
Extend the semantic rule format (CLAUDE.md §4 template) with one optional field, valid for rules of **any** category:

```markdown
## RULE-NNN: <name>
- applies_to: ...
- category: metric | filter | context | time
- definition: ...
- formula: ...
- caveats: ...
- rationale: <why this rule exists; the trade-off it accepts>   # NEW (optional)
- provenance: ...
```

- The why lives next to the rule, so it cannot drift from it and is versioned with it.
- A rule with no `rationale` renders an amber **"⚠ why pending"** badge — never silently omitted.
- When a new rule is created (auto-save protocol), Claude drafts the `rationale`, the user approves, it is saved into source. One-time per rule.

### 3.3 Worked-example numbers — faithfulness over recomputation
To guarantee the report can never contradict the analysis, **all example numbers flow through one shared function** — `cot_examples.example_for(rule, source)` — never through per-mode duplicated math. That single function resolves numbers by this **precedence**:

1. **Final figures** always come from the run's `result.csv` (authoritative).
2. **Intermediate figures** (e.g. monthly mix, renormalised shares) come from `cot_trace.json` (§3.3.1) when the run emitted one. Intermediates and finals then share one computation — zero divergence.
3. **Fallback** when no trace exists: a per-rule helper recomputes intermediates *and the final*, then **asserts the final equals `result.csv`**. On mismatch it renders a visible "⚠ example could not be reconciled" warning — it never shows numbers that disagree, and never fabricates.
4. **Engine mode** (no run supplied): the *same* function is called against the latest valid run's `cot_trace.json`/`result.csv`; only if no run exists does it compute from `data/*.csv` for the latest available week. One code path, parameterised by `source` — no duplicated logic across modes.

Worked example (RULE-004): weekly total (from `result.csv`) → national monthly UC:CD → renormalise within {UC,CD} → apply → UC/CD, asserting parts sum to the total. All steps, equations, and the final derive from one source, so they are mutually consistent by construction (the v1 mockup used illustrative numbers that did **not** reconcile — the real generator forbids that).

#### 3.3.1 `cot_trace.json` contract (v1)
Optional file at `output/<run_id>/cot_trace.json`, emitted by the generated `analysis_code.py` as its last step. Schema:

```jsonc
{
  "schema": "cot_trace/v1",
  "example_period": "2026-05-08",        // the week/period the example traces
  "rules": {
    "RULE-004": {
      "steps": [                          // ordered; step.id ↔ markers ❶❷❸ ↔ code_line
        {"id": 1, "label": "monthly mix (UC,CD)",  "code_line": 24, "values": {"UC": 41,     "CD": 52},   "unit": "TRX_VOLUME"},
        {"id": 2, "label": "renormalised shares",  "code_line": 27, "values": {"UC": 0.4409, "CD": 0.5591}},
        {"id": 3, "label": "applied to total",     "code_line": 31, "values": {"UC": 3121,   "CD": 3905}, "weekly_total": 7026}
      ],
      "final": {"UC": 3121, "CD": 3905},
      "reconciles_to": 7026
    }
  }
}
```

Rules: `step.id` drives the ❶❷❸ markers; `code_line` drives the "line NN" labels (so the code↔example link is data-driven, not hand-wired); `final` must equal the corresponding `result.csv` figures (the generator asserts this regardless of source). Unknown fields are ignored; a missing rule entry falls back to §3.3 step 3. The contract is additive/forward-compatible via `schema`.

### 3.4 Modes
- **Run mode:** `py -3 scripts/build_cot.py output/<run_id>` → full five-act story for that run; all governing rules shown (§4 multi-rule); the engine catalogue follows as a compact index. Output: `output/<run_id>/chain_of_thought.html`.
- **Engine mode:** `py -3 scripts/build_cot.py` → reasoning-path infographic + full rule catalogue (each rule with why + representative example per §3.3.4). Output: `docs/chain_of_thought.html`.

### 3.5 What "self-updating" means (and does not)
- **Does:** every invocation reflects the *current* state of the scanned files — add/edit/remove a rule, change the workflow, and the next build shows it with no manual edits.
- **Does not:** detect or diff *changes over time* (no git, no history). The header therefore shows **"generated &lt;timestamp&gt;"** and the **schema-gate verdict** (a real check), never an unverifiable "in sync" claim.

## 4. Document structure & visual design

Aesthetic: **editorial / data-journalism**, approved in mockup v2. DataZymes **colours only** (navy `071D49`, teal `07B2AC`, amber `FFC000`, magenta `E40D62`, watercolour gradient as a single left "spine"); all other choices bespoke. Warm ivory paper (`#F4F0E6`) with a faint dot-grid, **not** stark white. Type: **Fraunces** (display serif), **Hanken Grotesk** (body), **JetBrains Mono** (numbers/code "evidence"). Markup, CSS, and JS are inline in one `.html`; **web fonts load from the Google-Fonts CDN with system-serif/sans/mono fallbacks** (so it degrades gracefully offline). Native font embedding is deferred to a `--embed-fonts` flag.

**Accessibility:** body/most text meets WCAG AA contrast on the ivory paper (navy/ink on paper). Amber is used **only as a fill with dark text on top**, never as text on the light background. Every infographic (pipeline, renormalisation bars, sparkline) carries an adjacent text/number equivalent so meaning never depends on colour alone.

**Two distinct infographics (do not conflate):**
- **Engine reasoning-path** (engine mode): the 8 workflow steps parsed from CLAUDE.md, as an annotated journey with the feasibility branch (Feasible / With assumptions / Not feasible).
- **Run pipeline** (run mode): the 5-act story below.

Section order (run mode):
1. **Hero** — run id, statement headline, italic dek, status meta-rail: **generated date**, **schema-gate verdict**, rules applied, result rows (all verifiable; no "in sync").
2. **"Scanned →" strip** — the files actually read this build + timestamp.
3. **Run pipeline infographic** — five connected stages; the two heroes (**Plan & Rule**, **Worked example**) visually elevated (navy fill + "HERO" marker). Branch note: *rule exists → apply · missing → define & auto-save RULE-NNN*.
4. **§01 Request** — the verbatim query with parsed atoms (product / metric / grain / split / market).
5. **§02 Context** — the context built: scope, time window, filters, headline, data freshness. (§01 and §02 sit side-by-side in one band but are separately numbered, matching pipeline acts 1 and 2.)
6. **§03 Plan & the rules — ★ hero (multi-rule).** All rules that governed the run are shown. The **primary computational rule** (e.g. RULE-004) gets the full hero explainer: *What it does* / *Why it exists* (magenta-tinted) / **caveats** / **provenance + review status** pills. Other governing rules (e.g. RULE-003 crosswalk, RULE-301 scope) render as condensed rule cards in applied order.
7. **§04 Code** — designed editor panel: commented `analysis_code.py` excerpt, line numbers, syntax colours, amber step markers ❶❷❸.
8. **§05 Worked example — ★ hero** — step-by-step, each step linked to its code line via markers ❶❷❸: renormalisation infographic (full mix → other indications greyed/dropped → collapse to set → apply), explicit equations, final result with the `result.csv` reconciliation check. A compact UC/CD crossover **sparkline** appears as a *secondary* element (with numeric labels) subordinate to the single-week arithmetic.
9. **Rule catalogue index** — compact engine-level list of all live rules (id, name, category, status), linking to explainers. (Realises the "engine + run, layered in one doc" decision; full explainers are not duplicated here.)
10. **Footer** — ▶ DataZymes wordmark + regenerate command.

Responsive: marker-linked code↔example stacks gracefully; not forced side-by-side.

## 5. Decisions captured (from brainstorming)
- **Generation engine:** deterministic Python + source-authored rationale + numbers reused from run artifacts (recompute only as a reconciled fallback). *(Rejected: pure Claude skill — non-deterministic, wrong for an audit artifact; pure deterministic with no enrichment — loses the "why".)*
- **Subject:** both engine-level and run-level, layered in one doc.
- **Home/scope:** on-demand artifact (not part of the mandatory 6-file contract).
- **Aesthetic:** editorial/data-journalism, DataZymes colours only — approved via mockup v2.
- **Heroes:** business rule(s) + worked example.
- **Code↔example link:** numbered markers ❶❷❸ (not forced side-by-side).
- **Trend:** small UC/CD crossover sparkline, secondary.
- **Multi-rule:** first-class (primary rule = hero, others = condensed cards), not deferred.

## 6. Implementation surface
- **New:** `scripts/build_cot.py`; `scripts/cot_template.html` (template); `scripts/cot_examples.py` (the single `example_for(rule, source)` path + per-rule recompute fallbacks); optional `cot_trace.json` emission added to the analysis-code generation step (contract in §3.3.1).
- **Edited:**
  - `CLAUDE.md` — add `rationale` to the §4 rule template; add an opt-in **Step 9 (Chain-of-Thought report)**, parallel to Step 8's deck, documenting the trigger (see §7-trigger).
  - `semantic/metrics.md` — add `rationale` to RULE-003, RULE-004. `semantic/context.md` — add `rationale` to RULE-301.
  - `MEMORY.md` — record the new artifact, builder, and trigger.
- **Dependencies:** Python `py -3` + pandas (already present). **No new dependencies** — HTML via Python string templating (not jinja/pptx).
- **Output:** `output/<run_id>/chain_of_thought.html` (run) · `docs/chain_of_thought.html` (engine).

## 7. Trigger (opt-in)
- **Never auto-offered** (avoids prompt fatigue; deck remains the only post-delivery offer).
- **User runs it** via command — `py -3 scripts/build_cot.py [output/<run_id>]` — or **asks in plain English**: "build the chain-of-thought report" / "make the CoT doc" / "explain the reasoning for this run". CLAUDE.md Step 9 documents these phrases so the engine recognises them.

## 8. Validation / acceptance
- **Structural QA without a browser** (none guaranteed locally, per MEMORY): parse the output with Python's `html.parser`, assert balanced tags, presence of required section anchors, and that every hero block has content. (Mirrors the deck's structural-QA fallback.)
- **Numeric integrity:** every figure in the worked example traces to `result.csv`; parts **reconcile** to the total; on any mismatch the build renders the reconciliation warning rather than wrong/fabricated numbers.
- **No silent omission:** missing `rationale` → visible badge; rule with no example source → "example pending"; unreconciled → warning badge.
- **Self-update proof:** re-running after adding/editing/removing a rule reflects the change with no manual edits.
- **Provenance shown:** each governing rule displays provenance + review status sourced from the rule block and `_rule_log.csv`.
- **A11y:** spot-check AA contrast for text; confirm no colour-only meaning.

## 9. Open / deferred (post-v1, non-blocking)
- Native PDF export (v2) and `--embed-fonts` for fully-offline audit copies.
- Per-rule recompute fallbacks beyond RULE-004 (RULE-003 crosswalk, RULE-301 scope): v1 ships the RULE-004 fallback; others rely on `cot_trace.json` or render "example pending" until their helper is added.
- Engine-mode example when multiple prior runs exist defaults to the most recent valid run.

---

*Note: git is not initialised in this repo (per MEMORY.md), so this spec is not committed and edits are not recoverable — confirm before destructive actions.*

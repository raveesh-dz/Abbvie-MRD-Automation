ultracode

CONTEXT
This folder holds the design + implementation plans for an NL→SQL Semantic Compiler:
a system that turns a plain-English business question into a validated Snowflake SQL
string. An LLM selects governed metrics/dimensions/filters from a machine-readable
semantic layer (it never writes raw SQL); a deterministic compiler turns that selection
into SQL; verifiers gate it; an RCA engine localizes failures; a repair loop retries.
Three-layer architecture (deterministic core / stable L2 tool contract + model_client
seam / swappable orchestration adapter) so it runs on Claude Code now and the pure
Anthropic API later with no core rewrite.

FILES (read all; they are one dependency chain, build order A→E):
1. 2026-06-18-nl-to-sql-semantic-compiler-design.md   — the design spec (source of truth)
2. 2026-06-18-nl-to-sql-core.md                        — Plan A: P1–P3 deterministic core
3. 2026-06-18-nl-to-sql-p4a-resolve-retrieval.md       — Plan B: P4a Resolve + retrieval
4. 2026-06-18-nl-to-sql-p4b-rca-repair-adapter.md      — Plan C: P4b RCA + repair + Claude Code adapter
5. 2026-06-18-nl-to-sql-p5-eval-harness.md             — Plan D: P5 eval harness
6. 2026-06-18-nl-to-sql-p6-api-migration.md            — Plan E: P6 Anthropic API migration
(Each plan declares Interfaces "Consumes/Produces" — these are the contracts between tasks
and across plans. The package is `nl2sql`. Tests run with `py -3 -m pytest`.)

TASK
Review every document for REDUNDANCIES, INCONSISTENCIES, INEFFICIENCIES, and AREAS OF
IMPROVEMENT, then FIX the issues you find in place. Iterate fix→re-review until quality
clears the bar below. Do not rewrite wholesale — surgical edits that preserve the
established design, TDD structure, and exact file paths.

REVIEW RUBRIC — score each document out of 1000, and an overall /1000. Check:
1. Internal consistency — sections must not contradict each other; the architecture must
   match the task/code descriptions.
2. CROSS-DOCUMENT consistency — every function name, parameter list, return type, and
   pydantic field used in a later plan must EXACTLY match what an earlier plan's
   Interfaces/code defined (e.g. compile_ir, run_verifiers, run_repair, RepairResult,
   VerifyResult, ModelClient, RunFolder, TOOL_SCHEMAS, build_tool_dispatch). A name that
   drifts between plans is a bug — flag and fix.
3. TDD TRACE correctness — for EVERY task, trace each test through the implementation in
   that same task by hand: would the test actually pass on the shown code? Watch for
   wrong assertion values, attribute calls on the wrong type, fixtures that don't match,
   off-by-one in sequence/mock clients, string-match assertions that don't match the code's
   output. This is the highest-value check — prior review passes found real defects here.
4. Spec coverage — every component in the spec's component registry / roadmap must map to a
   task in some plan, OR be explicitly listed as a deliberate, justified follow-on/deferral.
   List any spec requirement with no task. (See KNOWN DEFERRALS below before flagging gaps.)
5. Placeholder scan — no "TBD/TODO/implement later", no "add error handling" hand-waves, no
   "similar to Task N" (code must be repeated, since tasks may be read out of order), no
   referenced type/function that is never defined. Every code step shows complete code.
6. Design-invariant preservation — fixes must NOT: couple core logic to a harness; put hard
   limits in the Charter instead of the guardrail policy; let the LLM emit raw SQL; break
   determinism of the compiler/retrieval/RCA; inline filter values instead of parameterizing;
   allow undeclared joins or patient-grain; or modify any core file from the P6 adapter
   (P6 must be additive only).
7. Observability completeness — every step/skill/agent/subagent must write readable
   input AND output artifacts; flag any stage missing its input.json/output.json pair.
8. Efficiency/redundancy — duplicated definitions, dead imports, unnecessary barriers,
   over-scoped tasks, anything that could be simpler without losing rigor.

KNOWN DEFERRALS — these are DELIBERATE, already-decided scope cuts. Do NOT report them as
defects, gaps, or missing coverage, and do NOT spend cycles re-litigating them. Only flag
them if a plan CONTRADICTS the deferral (e.g. claims to implement it, or a test depends on it):
- V4 (result-sanity verifier) is DEFERRED — it needs query execution, which is out of scope.
  It ships as an interface/stub that always reports "skipped". Activation is a future event.
- LIVE SNOWFLAKE EXECUTION / EXPLAIN dry-run is out of scope. The system emits SQL only.
  V2 validates against a static catalog snapshot, not a live warehouse.
- MACRO SQL INLINING into compiled SQL is a follow-on (it needs declared-join compilation).
  v1 ships the macro registry + lookup and records referenced macro ids in provenance only.
- DECLARED-JOIN COMPILATION is a follow-on; the v1 compiler emits single-base-table SQL.
  (V1 still ENFORCES the allowed-join rule on hand-written/any SQL — that is in scope.)
- EMBEDDINGS-BASED RETRIEVAL is a follow-on; v1 retrieval is deterministic keyword/token
  overlap + glossary synonyms. This is intentional, not a limitation to "fix".
- C-IDX (retrieval index) appears under spec roadmap P1 but is intentionally delivered in
  Plan B (P4a) alongside Resolve, since it only has value once Resolve consumes it.
- The Resolve/RCA "compiler bug → retry vs halt" routing: deterministic-compiler (V1)
  failures route to HALT (need a code fix); V3 intent-drift routes to RETRY. This is a
  deliberate, documented refinement of the spec's wording, not a contradiction.

SCORING + STOP CONDITION
- Maintain an internal score per document and overall, /1000.
- Deduct explicitly per defect (state the points and why).
- Keep iterating fix→re-score. Do NOT present a document as final until it reaches ≥990/1000.
- Adversarially verify your own fixes: after editing, re-trace the affected tests and
  re-check cross-document signatures before claiming a higher score.

SUGGESTED ORCHESTRATION
- One reviewer per document in parallel (find defects, score, propose fixes).
- One dedicated CROSS-DOCUMENT consistency pass over all 6 at once (signatures, types,
  spec-coverage, build order) — this is where single-doc reviewers are blind.
- Adversarially verify each proposed fix (re-trace tests, re-check contracts) before applying.
- Apply fixes in place, then a final convergence pass that re-scores every doc and the whole
  set; loop until all ≥990.

OUTPUT
- Apply all fixes directly to the files.
- Then report: per-document score path (initial → final) with the defects found and how each
  was fixed; the cross-document issues found; any spec gaps; and a final overall score.
- Do not edit a test merely to make it pass — if a test is wrong, fix the test to assert the
  correct behavior; if the code is wrong, fix the code. Never paper over a real defect.

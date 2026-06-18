# NL → SQL — P4b: RCA + Repair Loop + Claude Code Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Localize any failure to a layer (RCA), drive an RCA-routed repair loop instead of blind retry, and wire the whole NL→SQL flow behind the L2 tool contract so a Claude Code skill can run it.

**Architecture:** Three additions on top of core + P4a. A deterministic `SignatureMap` (#10) maps a failure signature (`verifier:check`, `resolve:*`, `compile:*`) to a layer + route (`halt`/`retry`) + recommendation. `diagnose()` (C-RCA) reads the first failure signal and returns a `Diagnosis`. `RepairLoop` (C-REP) orchestrates resolve→compile→verify, and on failure calls `diagnose`: `halt` stops with a human-facing reason; `retry` re-resolves with the recommendation injected, up to `max_attempts`. Each attempt is written to its own `05_repair/attempt_<n>/` subfolder. The Claude Code adapter (C-ADPT-CC) exposes the L2 tools as a dispatch table bound to the loaded governed inputs.

**Tech Stack:** Same as core — Python 3.14 (`py -3`), `pydantic>=2`, `pyyaml`, `pytest`.

**Depends on:** the core library plan and the P4a Resolve plan. Uses `compile_ir`/`CompileError`, `run_verifiers`/`all_passed`, `QueryIntent`, the loaders, `RunFolder`, `resolve`/`ResolveOutcome`, `SemanticIndex`, `ModelClient`/`FakeModelClient`, `TOOL_SCHEMAS`/`tool_names`. Implements **C-RCA, C-REP, C-ADPT-CC** (spec roadmap P4, RCA/repair/adapter half).

**Spec reference:** `docs/superpowers/specs/2026-06-18-nl-to-sql-semantic-compiler-design.md` §4 (RCA + repair routing), §6 (RCA layers), §7 (`04_rca.json`, `05_repair/`).

## Global Constraints

- Run Python with `py -3`.
- RCA is **deterministic** — same failure signals → same diagnosis.
- Repair is **RCA-routed**, never blind: `halt` for semantic gap / relationship error / schema drift / compiler bug; `retry` only for transient misses (retrieval miss, resolve parse error, V3 intent drift). **Deliberate choice vs spec §4:** the spec groups "compiler bug → retry"; a genuine compiler bug needs a code fix, so deterministic-compiler failures (V1) route to `halt` (surface for a fix), while V3 intent-drift — which a re-resolve can actually fix — routes to `retry`. Noted here so it is not read as a contradiction.
- Every attempt writes a full, readable subfolder; the final diagnosis writes `04_rca.json`.
- The adapter changes **no** core logic — it only maps tool names to existing functions.

---

### Task 1: RCA signature map (#10)

**Files:**
- Create: `src/nl2sql/rca/__init__.py`
- Create: `src/nl2sql/rca/signature_map.py`
- Create: `config/rca_signatures.yaml`
- Test: `tests/test_signature_map.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class SigEntry(BaseModel)`: `layer: str`, `route: str` (`"halt"` | `"retry"`), `recommendation: str`
  - `class SignatureMap(BaseModel)`: `signatures: dict[str, SigEntry]`
  - `SignatureMap.load(path: str) -> SignatureMap`
  - `SignatureMap.get(signature: str) -> SigEntry` — exact match, else `"<verifier>:*"` wildcard, else the required `"default"` entry.

- [ ] **Step 1: Write the failing test**

`config/rca_signatures.yaml`:
```yaml
signatures:
  "resolve:retrieval_miss":
    layer: retrieval
    route: retry
    recommendation: "IR named something not retrieved; broaden retrieval and re-resolve."
  "resolve:semantic_gap":
    layer: semantic
    route: halt
    recommendation: "Concept undefined; add a metric/filter/macro rule, then retry."
  "resolve:parse_error":
    layer: resolve
    route: retry
    recommendation: "LLM returned invalid JSON; re-resolve."
  "compile:unknown_ref":
    layer: semantic
    route: halt
    recommendation: "IR referenced an undefined name; add it or fix retrieval."
  "compile:unknown_macro":
    layer: semantic
    route: halt
    recommendation: "Referenced macro not in registry; add the macro."
  "V1:allowed_joins":
    layer: relationship
    route: halt
    recommendation: "Undeclared join; add the edge to relationships or fix the model."
  "V1:grain_not_banned":
    layer: guardrail
    route: halt
    recommendation: "IR requested a banned grain; Resolve must not select it."
  "V1:*":
    layer: compiler
    route: halt
    recommendation: "Compiler emitted unsafe SQL; fix the compiler and add a regression test."
  "V2:tables_exist":
    layer: schema_drift
    route: halt
    recommendation: "Unknown table; refresh the catalog or fix the model mapping."
  "V2:columns_exist":
    layer: schema_drift
    route: halt
    recommendation: "Unknown column; refresh the catalog or fix the model mapping."
  "V3:intent_fidelity":
    layer: compiler
    route: retry
    recommendation: "SQL drifted from the IR; re-resolve and recompile."
  "V3:judge_parse":
    layer: resolve
    route: retry
    recommendation: "Judge returned invalid JSON; re-run the judge."
  "default":
    layer: unknown
    route: halt
    recommendation: "Unrecognized failure; inspect the run folder."
```

`tests/test_signature_map.py`:
```python
from nl2sql.rca.signature_map import SignatureMap

SM = SignatureMap.load("config/rca_signatures.yaml")


def test_exact_match():
    e = SM.get("resolve:retrieval_miss")
    assert e.layer == "retrieval" and e.route == "retry"


def test_wildcard_fallback():
    e = SM.get("V1:read_only")  # no exact entry; V1:* matches
    assert e.layer == "compiler" and e.route == "halt"


def test_default_fallback():
    e = SM.get("totally:unknown")
    assert e.layer == "unknown" and e.route == "halt"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_signature_map.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.rca'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/rca/__init__.py`: (empty file)

`src/nl2sql/rca/signature_map.py`:
```python
from __future__ import annotations
import yaml
from pydantic import BaseModel


class SigEntry(BaseModel):
    layer: str
    route: str
    recommendation: str


class SignatureMap(BaseModel):
    signatures: dict[str, SigEntry]

    @classmethod
    def load(cls, path: str) -> "SignatureMap":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.model_validate(yaml.safe_load(fh))

    def get(self, signature: str) -> SigEntry:
        if signature in self.signatures:
            return self.signatures[signature]
        prefix = signature.split(":", 1)[0]
        wildcard = f"{prefix}:*"
        if wildcard in self.signatures:
            return self.signatures[wildcard]
        return self.signatures["default"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_signature_map.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/rca/__init__.py src/nl2sql/rca/signature_map.py config/rca_signatures.yaml tests/test_signature_map.py
git commit -m "feat: RCA signature map (#10)"
```

---

### Task 2: RCA engine — diagnose() (C-RCA)

**Files:**
- Create: `src/nl2sql/rca/rca.py`
- Test: `tests/test_rca.py`

**Interfaces:**
- Consumes: `SignatureMap`/`SigEntry` (Task 1), `ResolveOutcome` (P4a Task 3), `CompileError` (core Task 8), `VerifyResult` (core Task 9).
- Produces:
  - `class Diagnosis(BaseModel)`: `signature: str`, `layer: str`, `route: str`, `recommendation: str`
  - `failure_signature(*, resolve_outcome=None, compile_error=None, verify_results=None) -> str | None` — the first failure signal as a signature string, or `None` if nothing failed.
  - `diagnose(sigmap: SignatureMap, *, resolve_outcome=None, compile_error=None, verify_results=None) -> Diagnosis | None`

Signature derivation (first match wins, in this order):
1. `resolve_outcome` present and not feasible:
   - reason starts `"retrieval_miss"` → `"resolve:retrieval_miss"`
   - reason starts `"resolve_parse_error"` → `"resolve:parse_error"`
   - else → `"resolve:semantic_gap"`
2. `compile_error` present: message contains `"macro"` → `"compile:unknown_macro"`, else `"compile:unknown_ref"`.
3. `verify_results` present and not all passed: first failing `VerifyResult`, its first failing `Finding` → `"<verifier>:<check>"`.
4. else `None`.

- [ ] **Step 1: Write the failing test**

`tests/test_rca.py`:
```python
from nl2sql.rca.signature_map import SignatureMap
from nl2sql.rca.rca import diagnose, failure_signature
from nl2sql.resolve.resolve import ResolveOutcome
from nl2sql.compiler.compile import CompileError
from nl2sql.verify.types import Finding, VerifyResult

SM = SignatureMap.load("config/rca_signatures.yaml")


def test_no_failure_returns_none():
    ok = [VerifyResult(verifier="V1", passed=True,
                       findings=[Finding(check="read_only", passed=True)])]
    assert failure_signature(verify_results=ok) is None
    assert diagnose(SM, verify_results=ok) is None


def test_resolve_retrieval_miss():
    out = ResolveOutcome(feasible=False, reason="retrieval_miss: ['metric:x']")
    d = diagnose(SM, resolve_outcome=out)
    assert d.signature == "resolve:retrieval_miss"
    assert d.layer == "retrieval" and d.route == "retry"


def test_resolve_semantic_gap_halts():
    out = ResolveOutcome(feasible=False, reason="loyal writers undefined")
    d = diagnose(SM, resolve_outcome=out)
    assert d.signature == "resolve:semantic_gap" and d.route == "halt"


def test_compile_error_macro():
    d = diagnose(SM, compile_error=CompileError("macro not found: macro.x"))
    assert d.signature == "compile:unknown_macro" and d.layer == "semantic"


def test_verify_first_failing_check():
    results = [
        VerifyResult(verifier="V1", passed=True,
                     findings=[Finding(check="read_only", passed=True)]),
        VerifyResult(verifier="V2", passed=False, findings=[
            Finding(check="tables_exist", passed=True),
            Finding(check="columns_exist", passed=False, message="X")]),
    ]
    d = diagnose(SM, verify_results=results)
    assert d.signature == "V2:columns_exist" and d.layer == "schema_drift"


def test_v3_intent_routes_retry():
    results = [VerifyResult(verifier="V3", passed=False,
               findings=[Finding(check="intent_fidelity", passed=False)])]
    d = diagnose(SM, verify_results=results)
    assert d.route == "retry"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_rca.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.rca.rca'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/rca/rca.py`:
```python
from __future__ import annotations
from pydantic import BaseModel
from nl2sql.rca.signature_map import SignatureMap


class Diagnosis(BaseModel):
    signature: str
    layer: str
    route: str
    recommendation: str


def failure_signature(*, resolve_outcome=None, compile_error=None,
                      verify_results=None) -> str | None:
    if resolve_outcome is not None and not resolve_outcome.feasible:
        reason = resolve_outcome.reason or ""
        if reason.startswith("retrieval_miss"):
            return "resolve:retrieval_miss"
        if reason.startswith("resolve_parse_error"):
            return "resolve:parse_error"
        return "resolve:semantic_gap"
    if compile_error is not None:
        msg = str(compile_error).lower()
        return "compile:unknown_macro" if "macro" in msg else "compile:unknown_ref"
    if verify_results is not None:
        for r in verify_results:
            if not r.passed:
                for f in r.findings:
                    if not f.passed:
                        return f"{r.verifier}:{f.check}"
                return f"{r.verifier}:unknown"
    return None


def diagnose(sigmap: SignatureMap, *, resolve_outcome=None,
             compile_error=None, verify_results=None) -> Diagnosis | None:
    sig = failure_signature(resolve_outcome=resolve_outcome,
                            compile_error=compile_error,
                            verify_results=verify_results)
    if sig is None:
        return None
    e = sigmap.get(sig)
    return Diagnosis(signature=sig, layer=e.layer, route=e.route,
                     recommendation=e.recommendation)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_rca.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/rca/rca.py tests/test_rca.py
git commit -m "feat: RCA engine diagnose() (C-RCA)"
```

---

### Task 3: SequenceModelClient test double (core seam helper)

**Files:**
- Modify: `src/nl2sql/toolcontract/model_client.py` (add `SequenceModelClient`)
- Test: `tests/test_sequence_client.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class SequenceModelClient`: `__init__(self, responses: list[str])`; `complete(system, user) -> str` returns responses in order; raises `IndexError` if exhausted; records all calls in `.calls: list[tuple[str, str]]`.

Rationale: the repair-loop tests need the LLM to return different answers on successive attempts. `FakeModelClient` returns one canned answer; this returns a scripted sequence.

- [ ] **Step 1: Write the failing test**

`tests/test_sequence_client.py`:
```python
import pytest
from nl2sql.toolcontract.model_client import SequenceModelClient


def test_returns_in_order_and_records():
    c = SequenceModelClient(["a", "b"])
    assert c.complete("s", "u1") == "a"
    assert c.complete("s", "u2") == "b"
    assert [u for _, u in c.calls] == ["u1", "u2"]


def test_exhaustion_raises():
    c = SequenceModelClient(["only"])
    c.complete("s", "u")
    with pytest.raises(IndexError):
        c.complete("s", "u")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_sequence_client.py -v`
Expected: FAIL — `ImportError: cannot import name 'SequenceModelClient'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/nl2sql/toolcontract/model_client.py`:
```python
class SequenceModelClient:
    """Returns scripted responses in order. For multi-attempt tests."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._i = 0
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if self._i >= len(self._responses):
            raise IndexError("SequenceModelClient exhausted")
        out = self._responses[self._i]
        self._i += 1
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_sequence_client.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/toolcontract/model_client.py tests/test_sequence_client.py
git commit -m "test: SequenceModelClient scripted test double"
```

---

### Task 4: Repair loop (C-REP)

**Files:**
- Create: `src/nl2sql/repair/__init__.py`
- Create: `src/nl2sql/repair/loop.py`
- Test: `tests/test_repair_loop.py`

**Interfaces:**
- Consumes: `resolve`/`ResolveOutcome` (P4a), `SemanticIndex` (P4a), `compile_ir`/`CompileError` (core), `run_verifiers`/`all_passed` (core), `diagnose`/`Diagnosis` (Task 2), `SignatureMap` (Task 1), `RunFolder` (core), loaders, `ModelClient`.
- Produces:
  - `class RepairResult(BaseModel)`: `run_id: str`, `passed: bool`, `attempts: int`, `sql: str = ""`, `run_dir: str`, `final_signature: str = ""`, `final_layer: str = ""`, `reason: str = ""`
  - `run_repair(question, model, macros, policy, catalog, index, charter_text, sigmap, resolve_client, judge_client, run_id, root, max_attempts=3) -> RepairResult`

Behavior per attempt `n` (1-based), writing to `RunFolder(f"{run_id}/05_repair/attempt_{n}", root)`:
1. `resolve(question_aug, ...)`; write `00_question.txt` (the augmented question), `01_resolve.input.json` (the prompt), and `01_resolve.output.json` (the outcome). `question_aug` = the question on attempt 1, else the question + a `[Repair hint]` line carrying the last diagnosis recommendation.
2. If infeasible → `diagnose(resolve_outcome=...)`; write `04_rca.json` (per attempt). `route=="halt"` → stop (failed). `route=="retry"` → carry hint, next attempt.
3. Else compile: on `CompileError` → `diagnose(compile_error=...)`, write rca, route as above. On success write `02_compile.output.sql`.
4. Verify; write `03_verify.V*.json`. `all_passed` → success (write top-level `run_manifest.json` with `passed=true`, return). Else `diagnose(verify_results=...)`, write rca, route as above.
After `max_attempts` exhausted → failed with the last diagnosis. On any terminal exit, write the top-level `04_rca.json` (final diagnosis) and `run_manifest.json`.

- [ ] **Step 1: Write the failing test**

`tests/test_repair_loop.py`:
```python
import json
import os
from nl2sql.semantic.model import SemanticModel
from nl2sql.semantic.macros import MacroRegistry
from nl2sql.guardrails.policy import GuardrailPolicy
from nl2sql.catalog.catalog import Catalog
from nl2sql.retrieval.glossary import Glossary
from nl2sql.retrieval.index import SemanticIndex
from nl2sql.rca.signature_map import SignatureMap
from nl2sql.toolcontract.model_client import FakeModelClient, SequenceModelClient
from nl2sql.repair.loop import run_repair

MODEL = SemanticModel.load("config/semantic_model.yaml")
MACROS = MacroRegistry.load("config/macros.yaml")
POLICY = GuardrailPolicy.load("config/guardrails.yaml")
CAT = Catalog.load("config/catalog.yaml")
IDX = SemanticIndex.build(MODEL, Glossary.load("config/glossary.yaml"), MACROS)
SM = SignatureMap.load("config/rca_signatures.yaml")
CHARTER = "Pharma."

FEASIBLE = """
{"feasible": true, "ir": {
  "ir_version": "1.0", "question": "weekly trx by indication for ibd",
  "metrics": ["trx_adjusted"], "dimensions": ["indication", "week_ending"],
  "filters": [{"ref": "filter.ibd_market"}], "grain": "indication x week"
}}
"""
SEMANTIC_GAP = '{"feasible": false, "reason": "loyal writers undefined", "proposal": "define"}'


def test_first_attempt_success(tmp_path):
    res = run_repair("weekly trx by indication for ibd", MODEL, MACROS, POLICY,
                     CAT, IDX, CHARTER, SM,
                     resolve_client=FakeModelClient(FEASIBLE),
                     judge_client=FakeModelClient('{"passed": true, "reasons": []}'),
                     run_id="run_2026-06-18_020", root=str(tmp_path))
    assert res.passed is True and res.attempts == 1
    assert "SUM(WEEKLY.TRX_ADJUSTED)" in res.sql
    assert os.path.isfile(os.path.join(res.run_dir, "run_manifest.json"))
    assert os.path.isfile(os.path.join(
        res.run_dir, "05_repair", "attempt_1", "02_compile.output.sql"))


def test_retry_then_success(tmp_path):
    # V3 judge fails attempt 1, passes attempt 2 -> route retry -> 2 attempts.
    res = run_repair("weekly trx by indication for ibd", MODEL, MACROS, POLICY,
                     CAT, IDX, CHARTER, SM,
                     resolve_client=SequenceModelClient([FEASIBLE, FEASIBLE]),
                     judge_client=SequenceModelClient([
                         '{"passed": false, "reasons": ["drift"]}',
                         '{"passed": true, "reasons": []}']),
                     run_id="run_2026-06-18_021", root=str(tmp_path), max_attempts=3)
    assert res.passed is True and res.attempts == 2
    assert os.path.isdir(os.path.join(res.run_dir, "05_repair", "attempt_2"))


def test_semantic_gap_halts_immediately(tmp_path):
    res = run_repair("show loyal writers", MODEL, MACROS, POLICY, CAT, IDX,
                     CHARTER, SM, resolve_client=FakeModelClient(SEMANTIC_GAP),
                     judge_client=FakeModelClient('{"passed": true, "reasons": []}'),
                     run_id="run_2026-06-18_022", root=str(tmp_path))
    assert res.passed is False and res.attempts == 1
    assert res.final_layer == "semantic"
    with open(os.path.join(res.run_dir, "04_rca.json"), encoding="utf-8") as fh:
        assert json.load(fh)["layer"] == "semantic"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_repair_loop.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.repair'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/repair/__init__.py`: (empty file)

`src/nl2sql/repair/loop.py`:
```python
from __future__ import annotations
from pydantic import BaseModel
from nl2sql.semantic.model import SemanticModel
from nl2sql.semantic.macros import MacroRegistry
from nl2sql.guardrails.policy import GuardrailPolicy
from nl2sql.catalog.catalog import Catalog
from nl2sql.retrieval.index import SemanticIndex
from nl2sql.toolcontract.model_client import ModelClient
from nl2sql.resolve.resolve import resolve
from nl2sql.compiler.compile import compile_ir, CompileError
from nl2sql.verify.runner import run_verifiers, all_passed
from nl2sql.rca.signature_map import SignatureMap
from nl2sql.rca.rca import diagnose, Diagnosis
from nl2sql.obs.run import RunFolder


class RepairResult(BaseModel):
    run_id: str
    passed: bool
    attempts: int
    sql: str = ""
    run_dir: str
    final_signature: str = ""
    final_layer: str = ""
    reason: str = ""


def _augment(question: str, diag: Diagnosis | None) -> str:
    if diag is None:
        return question
    return f"{question}\n\n[Repair hint] Previous attempt failed " \
           f"({diag.layer}): {diag.recommendation}"


def run_repair(question: str, model: SemanticModel, macros: MacroRegistry,
               policy: GuardrailPolicy, catalog: Catalog, index: SemanticIndex,
               charter_text: str, sigmap: SignatureMap,
               resolve_client: ModelClient, judge_client: ModelClient,
               run_id: str, root: str, max_attempts: int = 3) -> RepairResult:
    top = RunFolder(run_id, root)
    last: Diagnosis | None = None

    for n in range(1, max_attempts + 1):
        af = RunFolder(f"{run_id}/05_repair/attempt_{n}", root)
        aug = _augment(question, last)
        outcome = resolve(aug, model, index, charter_text, resolve_client)
        af.write_text("00_question.txt", aug)
        af.write_json("01_resolve.input.json", {"prompt": outcome.prompt})
        af.write_json("01_resolve.output.json", outcome.model_dump())

        if not outcome.feasible or outcome.ir is None:
            d = diagnose(sigmap, resolve_outcome=outcome)
            af.write_json("04_rca.json", d.model_dump())
            last = d
            if d.route == "halt":
                break
            continue

        try:
            compiled = compile_ir(outcome.ir, model, macros, policy)
        except CompileError as e:
            d = diagnose(sigmap, compile_error=e)
            af.write_json("04_rca.json", d.model_dump())
            last = d
            if d.route == "halt":
                break
            continue
        af.write_sql("02_compile.output.sql", compiled.sql)
        af.write_json("02_compile.provenance.json", compiled.provenance)

        results = run_verifiers(compiled.sql, compiled.params, outcome.ir,
                                policy, catalog, judge_client)
        for r in results:
            af.write_json(f"03_verify.{r.verifier}.json", r.model_dump())

        if all_passed(results):
            top.write_manifest({"run_id": run_id, "passed": True,
                                "attempts": n})
            return RepairResult(run_id=run_id, passed=True, attempts=n,
                                sql=compiled.sql, run_dir=top.dir)
        d = diagnose(sigmap, verify_results=results)
        af.write_json("04_rca.json", d.model_dump())
        last = d
        if d.route == "halt":
            break

    # terminal failure
    attempts = n
    sig = last.signature if last else ""
    layer = last.layer if last else ""
    rec = last.recommendation if last else ""
    if last is not None:
        top.write_json("04_rca.json", last.model_dump())
    top.write_manifest({"run_id": run_id, "passed": False, "attempts": attempts,
                        "final_signature": sig, "final_layer": layer})
    return RepairResult(run_id=run_id, passed=False, attempts=attempts,
                        run_dir=top.dir, final_signature=sig, final_layer=layer,
                        reason=rec)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_repair_loop.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/repair/ tests/test_repair_loop.py
git commit -m "feat: RCA-routed repair loop (C-REP)"
```

---

### Task 5: Claude Code adapter — tool dispatch (C-ADPT-CC)

**Files:**
- Create: `src/nl2sql/adapter/__init__.py`
- Create: `src/nl2sql/adapter/claude_code.py`
- Test: `tests/test_adapter_cc.py`

**Interfaces:**
- Consumes: `TOOL_SCHEMAS`/`tool_names` (core Task 14), `QueryIntent` (core), `SemanticIndex` (P4a), `compile_ir` (core), `run_verifiers` (core), `diagnose`/`SignatureMap` (Tasks 1–2), loaders, `ModelClient`.
- Produces:
  - `build_tool_dispatch(model, macros, policy, catalog, index, sigmap, judge_client) -> dict[str, callable]` — one handler per name in `TOOL_SCHEMAS`. Each handler takes a single `args: dict` and returns a JSON-serializable `dict`.
    - `search_semantic_model(args)` → `index.search(args["query"]).model_dump()`
    - `fetch_schema(args)` → `{"tables": {t: catalog.tables[t] for t in args["tables"] if t in catalog.tables}}`
    - `compile_ir(args)` → `compile_ir(QueryIntent.model_validate(args["ir"]), model, macros, policy).model_dump()`
    - `run_verifiers(args)` → `{"results": [r.model_dump() for r in run_verifiers(args["sql"], args.get("params", {}), QueryIntent.model_validate(args["ir"]), policy, catalog, judge_client)]}`
    - `rca_diagnose(args)` → diagnosis from `args["verify_results"]`-shaped data (rebuilt into `VerifyResult`s) → `diagnose(...).model_dump()` or `{}` if no failure
    - `dry_run(args)` → raises `NotImplementedError` (Snowflake EXPLAIN is a follow-on)

Note on the seam: the Claude Code skill (a thin markdown wrapper, not in this library) registers `TOOL_SCHEMAS` as tools, routes each tool call to this dispatch table, and binds `model_client` to the Claude Code harness. The migration plan (P6) re-uses this exact dispatch with a different `model_client`. The skill markdown holds no logic — it only orchestrates.

- [ ] **Step 1: Write the failing test**

`tests/test_adapter_cc.py`:
```python
import pytest
from nl2sql.semantic.model import SemanticModel
from nl2sql.semantic.macros import MacroRegistry
from nl2sql.guardrails.policy import GuardrailPolicy
from nl2sql.catalog.catalog import Catalog
from nl2sql.retrieval.glossary import Glossary
from nl2sql.retrieval.index import SemanticIndex
from nl2sql.rca.signature_map import SignatureMap
from nl2sql.toolcontract.model_client import FakeModelClient
from nl2sql.toolcontract.schemas import tool_names
from nl2sql.adapter.claude_code import build_tool_dispatch

MODEL = SemanticModel.load("config/semantic_model.yaml")
MACROS = MacroRegistry.load("config/macros.yaml")
POLICY = GuardrailPolicy.load("config/guardrails.yaml")
CAT = Catalog.load("config/catalog.yaml")
IDX = SemanticIndex.build(MODEL, Glossary.load("config/glossary.yaml"), MACROS)
SM = SignatureMap.load("config/rca_signatures.yaml")
DISPATCH = build_tool_dispatch(MODEL, MACROS, POLICY, CAT, IDX, SM,
                               FakeModelClient('{"passed": true, "reasons": []}'))

IR = {"ir_version": "1.0", "question": "q", "metrics": ["trx_adjusted"],
      "dimensions": ["indication", "week_ending"],
      "filters": [{"ref": "filter.ibd_market"}], "grain": "indication x week"}


def test_dispatch_covers_every_tool():
    assert set(DISPATCH.keys()) == set(tool_names())


def test_compile_ir_handler_returns_sql():
    out = DISPATCH["compile_ir"]({"ir": IR})
    assert "SUM(WEEKLY.TRX_ADJUSTED)" in out["sql"]


def test_search_handler_returns_candidates():
    out = DISPATCH["search_semantic_model"]({"query": "split by indication"})
    assert "indication" in out["dimensions"]


def test_dry_run_not_implemented():
    with pytest.raises(NotImplementedError):
        DISPATCH["dry_run"]({"sql": "SELECT 1"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_adapter_cc.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.adapter'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/adapter/__init__.py`: (empty file)

`src/nl2sql/adapter/claude_code.py`:
```python
from __future__ import annotations
from nl2sql.ir import QueryIntent
from nl2sql.compiler.compile import compile_ir as _compile_ir
from nl2sql.verify.runner import run_verifiers as _run_verifiers
from nl2sql.verify.types import VerifyResult
from nl2sql.rca.rca import diagnose


def build_tool_dispatch(model, macros, policy, catalog, index, sigmap,
                        judge_client) -> dict:
    def search_semantic_model(args: dict) -> dict:
        return index.search(args["query"]).model_dump()

    def fetch_schema(args: dict) -> dict:
        want = args["tables"]
        return {"tables": {t: catalog.tables[t] for t in want
                           if t in catalog.tables}}

    def compile_ir(args: dict) -> dict:
        ir = QueryIntent.model_validate(args["ir"])
        return _compile_ir(ir, model, macros, policy).model_dump()

    def run_verifiers(args: dict) -> dict:
        ir = QueryIntent.model_validate(args["ir"])
        results = _run_verifiers(args["sql"], args.get("params", {}), ir,
                                 policy, catalog, judge_client)
        return {"results": [r.model_dump() for r in results]}

    def rca_diagnose(args: dict) -> dict:
        results = [VerifyResult.model_validate(r) for r in args["verify_results"]]
        d = diagnose(sigmap, verify_results=results)
        return d.model_dump() if d is not None else {}

    def dry_run(args: dict) -> dict:
        raise NotImplementedError("Snowflake EXPLAIN dry-run is a follow-on")

    return {
        "search_semantic_model": search_semantic_model,
        "fetch_schema": fetch_schema,
        "compile_ir": compile_ir,
        "run_verifiers": run_verifiers,
        "rca_diagnose": rca_diagnose,
        "dry_run": dry_run,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_adapter_cc.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Run the whole suite + commit**

Run: `py -3 -m pytest -v`
Expected: PASS (core + P4a + P4b all green).

```bash
git add src/nl2sql/adapter/ tests/test_adapter_cc.py
git commit -m "feat: Claude Code adapter tool dispatch (C-ADPT-CC)"
```

---

## Done criteria
- `py -3 -m pytest -v` green (core + P4a + P4b).
- A failing run is localized to a layer (`04_rca.json`) and the repair loop either fixes it within `max_attempts` or halts with a human-facing reason; every attempt is a readable `05_repair/attempt_<n>/` subfolder.
- The L2 tool contract has a working dispatch handler for every tool name; a Claude Code skill can drive the full NL→SQL flow through it.

## Follow-on (next plans)
- **P5** (C-EVAL): golden-set eval harness over the full resolve→compile→verify flow.
- **P6** (C-ADPT-API): Anthropic API agent adapter reusing this dispatch with a different `model_client`.

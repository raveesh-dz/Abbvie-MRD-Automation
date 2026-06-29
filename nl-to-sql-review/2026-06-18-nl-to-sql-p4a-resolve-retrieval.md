# NL → SQL — P4a: Resolve + Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a plain-English question into a validated Query Intent IR — by retrieving relevant semantic-layer candidates and having an LLM (via the `model_client` seam) select from them — with an early feasibility exit when a term cannot be mapped.

**Architecture:** Two new pure-Python modules on top of the core library. A deterministic `SemanticIndex` (C-IDX) ranks semantic-model items by token overlap with the question (plus glossary synonyms). `resolve()` (C-RES) assembles a prompt from the Charter + retrieved candidates + question, calls `model_client.complete`, parses a strict JSON verdict into either a `QueryIntent` or a feasibility refusal, and guards that every referenced name actually exists in the model.

**Tech Stack:** Same as core — Python 3.14 (`py -3`), `pydantic>=2`, `pyyaml`, `pytest`. No embeddings in v1 (deterministic keyword retrieval; embeddings are spec open-Q3, follow-on).

**Depends on:** the core library plan (`2026-06-18-nl-to-sql-core.md`) — components C-IR, C-SM, C-MR, C-CMP, C-GP, C-CAT, C-MC, C-OBS, the verify runner, and `run_pipeline`. This plan implements **C-RES, C-IDX** (spec roadmap P4, Resolve half).

**Spec reference:** `docs/superpowers/specs/2026-06-18-nl-to-sql-semantic-compiler-design.md` §4 (Resolve, early feasibility exit), §5 (#3 glossary, #8 retrieval index).

## Global Constraints

(Inherited from the core plan; repeated essentials.)
- Run Python with `py -3`.
- Retrieval is **deterministic** — same question + same model version → same candidate ranking.
- Resolve **never invents** a column/metric/filter: if the LLM returns an IR referencing a name absent from the semantic model, Resolve downgrades the outcome to infeasible (a retrieval/resolve miss), it does not pass a guessed IR downstream.
- The LLM is reached **only** through the `model_client` seam (`nl2sql.toolcontract.model_client.ModelClient`); tests use `FakeModelClient`.
- Every change to glossary / semantic model is its own commit.

---

### Task 1: Glossary loader (supports C-IDX)

**Files:**
- Create: `src/nl2sql/retrieval/__init__.py`
- Create: `src/nl2sql/retrieval/glossary.py`
- Create: `config/glossary.yaml`
- Test: `tests/test_glossary.py`
- Test fixture: `tests/fixtures/glossary.yaml`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class Glossary(BaseModel)`: `synonyms: dict[str, str]` (lowercased phrase → a semantic-model ref like `"filter.ibd_market"` or `"metric.trx_adjusted"`)
  - `Glossary.load(path: str) -> Glossary`
  - `Glossary.matches(question: str) -> list[str]` — refs whose synonym phrase appears (case-insensitive substring) in `question`, in declaration order, de-duplicated.

- [ ] **Step 1: Write the failing test**

`tests/fixtures/glossary.yaml`:
```yaml
synonyms:
  "ibd market": "filter.ibd_market"
  "ibd": "filter.ibd_market"
  "adjusted trx": "metric.trx_adjusted"
```

`tests/test_glossary.py`:
```python
from nl2sql.retrieval.glossary import Glossary

G = Glossary.load("tests/fixtures/glossary.yaml")


def test_matches_phrase_case_insensitive():
    refs = G.matches("weekly Tremfya TRx for the IBD Market please")
    assert "filter.ibd_market" in refs


def test_no_match_returns_empty():
    assert G.matches("revenue by region") == []


def test_dedupes_refs():
    # "ibd market" and "ibd" both map to filter.ibd_market
    refs = G.matches("ibd market and ibd")
    assert refs.count("filter.ibd_market") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_glossary.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.retrieval'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/retrieval/__init__.py`: (empty file)

`src/nl2sql/retrieval/glossary.py`:
```python
from __future__ import annotations
import yaml
from pydantic import BaseModel


class Glossary(BaseModel):
    synonyms: dict[str, str]

    @classmethod
    def load(cls, path: str) -> "Glossary":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.model_validate(yaml.safe_load(fh))

    def matches(self, question: str) -> list[str]:
        q = question.lower()
        out: list[str] = []
        for phrase, ref in self.synonyms.items():
            if phrase.lower() in q and ref not in out:
                out.append(ref)
        return out
```

`config/glossary.yaml` (the real governed glossary — mirrors the fixture for now):
```yaml
synonyms:
  "ibd market": "filter.ibd_market"
  "ibd": "filter.ibd_market"
  "adjusted trx": "metric.trx_adjusted"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_glossary.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/retrieval/__init__.py src/nl2sql/retrieval/glossary.py config/glossary.yaml tests/test_glossary.py tests/fixtures/glossary.yaml
git commit -m "feat: glossary loader for retrieval (C-IDX dep)"
```

---

### Task 2: Semantic index — build + search (C-IDX)

**Files:**
- Create: `src/nl2sql/retrieval/index.py`
- Test: `tests/test_index.py`

**Interfaces:**
- Consumes: `SemanticModel` (core Task 3), `Glossary` (Task 1).
- Produces:
  - `class Candidates(BaseModel)`: `metrics: list[str]`, `dimensions: list[str]`, `filters: list[str]`, `macros: list[str]`
  - `class SemanticIndex`: `build(model: SemanticModel, glossary: Glossary, macros: MacroRegistry | None = None) -> SemanticIndex` (classmethod)
  - `.search(question: str, k: int = 5) -> Candidates` — per item kind, rank by token-overlap score (question tokens ∩ item tokens), keep score > 0, then top-`k`; glossary-matched refs are force-included at the front of their kind. If a kind has zero overlap matches and zero glossary hits, return that kind's full list capped at `k` (so the LLM still sees options).
  - Module helper `tokens(text: str) -> set[str]` — lowercased alphanumeric tokens.

- [ ] **Step 1: Write the failing test**

`tests/test_index.py`:
```python
from nl2sql.semantic.model import SemanticModel
from nl2sql.semantic.macros import MacroRegistry
from nl2sql.retrieval.glossary import Glossary
from nl2sql.retrieval.index import SemanticIndex, Candidates, tokens

MODEL = SemanticModel.load("tests/fixtures/semantic_model.yaml")
MACROS = MacroRegistry.load("tests/fixtures/macros.yaml")
GLOSS = Glossary.load("tests/fixtures/glossary.yaml")
IDX = SemanticIndex.build(MODEL, GLOSS, MACROS)


def test_tokens_lowercases_and_splits():
    assert tokens("Adjusted TRx, by-week") == {"adjusted", "trx", "by", "week"}


def test_search_ranks_indication_dimension():
    c = IDX.search("split by indication", k=5)
    assert "indication" in c.dimensions


def test_glossary_forces_filter_candidate():
    c = IDX.search("weekly trx for ibd market", k=5)
    # candidates hold BARE names (model keys), not "filter."-prefixed refs
    assert "ibd_market" in c.filters


def test_search_returns_candidates_type():
    assert isinstance(IDX.search("anything"), Candidates)


def test_zero_overlap_falls_back_to_full_list_capped():
    c = IDX.search("completely unrelated words", k=1)
    # metrics fallback: at most k, but non-empty so the LLM has options
    assert 0 < len(c.metrics) <= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_index.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.retrieval.index'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/retrieval/index.py`:
```python
from __future__ import annotations
import re
from pydantic import BaseModel
from nl2sql.semantic.model import SemanticModel
from nl2sql.semantic.macros import MacroRegistry
from nl2sql.retrieval.glossary import Glossary

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


class Candidates(BaseModel):
    metrics: list[str]
    dimensions: list[str]
    filters: list[str]
    macros: list[str]


class SemanticIndex:
    def __init__(self, docs: dict[str, dict[str, set[str]]],
                 glossary: Glossary) -> None:
        # docs[kind][name] = token set
        self._docs = docs
        self._glossary = glossary

    @classmethod
    def build(cls, model: SemanticModel, glossary: Glossary,
              macros: MacroRegistry | None = None) -> "SemanticIndex":
        docs: dict[str, dict[str, set[str]]] = {
            "metrics": {}, "dimensions": {}, "filters": {}, "macros": {}}
        for name, m in model.metrics.items():
            docs["metrics"][name] = tokens(f"{name} {m.label} {m.description}")
        for name, d in model.dimensions.items():
            docs["dimensions"][name] = tokens(f"{name} {d.column} {d.type}")
        for name, f in model.filters.items():
            docs["filters"][name] = tokens(f"{name} {f.expr}")
        if macros is not None:
            for name, mac in macros.macros.items():
                docs["macros"][name] = tokens(f"{name} {mac.description}")
        return cls(docs, glossary)

    def _rank(self, kind: str, q_tokens: set[str], forced: list[str],
              k: int) -> list[str]:
        scored = [(len(q_tokens & toks), name)
                  for name, toks in self._docs[kind].items()]
        ranked = [name for score, name in
                  sorted(scored, key=lambda x: (-x[0], x[1])) if score > 0]
        # force glossary hits to the front (kept unique, order-preserving)
        out: list[str] = []
        for name in forced + ranked:
            if name in self._docs[kind] and name not in out:
                out.append(name)
        if not out:  # zero overlap, no glossary hit -> show full list capped
            out = sorted(self._docs[kind].keys())
        return out[:k]

    def search(self, question: str, k: int = 5) -> Candidates:
        q = tokens(question)
        gloss_refs = self._glossary.matches(question)
        forced = {"metrics": [], "dimensions": [], "filters": [], "macros": []}
        for ref in gloss_refs:
            kind_word, _, name = ref.partition(".")
            kind = {"metric": "metrics", "dimension": "dimensions",
                    "filter": "filters", "macro": "macros"}.get(kind_word)
            if kind and name:
                forced[kind].append(name)
        return Candidates(
            metrics=self._rank("metrics", q, forced["metrics"], k),
            dimensions=self._rank("dimensions", q, forced["dimensions"], k),
            filters=self._rank("filters", q, forced["filters"], k),
            macros=self._rank("macros", q, forced["macros"], k),
        )
```

Note: glossary refs use the singular kind word (`filter.ibd_market`); the index maps singular → plural bucket. A forced name is only kept if it exists in that kind's docs (guards a stale glossary entry).

Convention: `Candidates` lists hold **bare names** (the semantic-model keys: `ibd_market`, `trx_adjusted`, `indication`), NOT `"filter."`-prefixed refs. The IR uses bare names for metrics/dimensions and `filter.<name>` refs for filters; the Resolve system prompt (Task 3) instructs the LLM to wrap filter selections as `filter.<name>`. Keeping candidates bare matches the model keys and keeps the index kind-agnostic.

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_index.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/retrieval/index.py tests/test_index.py
git commit -m "feat: deterministic semantic index + search (C-IDX)"
```

---

### Task 3: Resolve outcome types + feasible path (C-RES)

**Files:**
- Create: `src/nl2sql/resolve/__init__.py`
- Create: `src/nl2sql/resolve/resolve.py`
- Test: `tests/test_resolve_feasible.py`

**Interfaces:**
- Consumes: `QueryIntent` (core Task 2), `SemanticModel` (core Task 3), `SemanticIndex`/`Candidates` (Task 2), `ModelClient` (core Task 11).
- Produces:
  - `class ResolveOutcome(BaseModel)`: `feasible: bool`, `ir: QueryIntent | None = None`, `reason: str = ""`, `proposal: str = ""`, `prompt: str = ""` (the prompt sent — for the run folder)
  - `build_resolve_prompt(question: str, candidates: Candidates, charter_text: str) -> str`
  - `resolve(question: str, model: SemanticModel, index: SemanticIndex, charter_text: str, client: ModelClient) -> ResolveOutcome`

LLM contract (the JSON the `model_client` must return):
```json
{"feasible": true, "ir": { ...QueryIntent fields... }}
// or
{"feasible": false, "reason": "<short>", "proposal": "<a concrete definition to add>"}
```
On `feasible: true`, `resolve` validates `ir` parses as a `QueryIntent`. (Reference-existence guard is added in Task 4.) On JSON/validation error → `feasible=False`, `reason="resolve_parse_error: ..."`.

- [ ] **Step 1: Write the failing test**

`tests/test_resolve_feasible.py`:
```python
from nl2sql.semantic.model import SemanticModel
from nl2sql.semantic.macros import MacroRegistry
from nl2sql.retrieval.glossary import Glossary
from nl2sql.retrieval.index import SemanticIndex
from nl2sql.toolcontract.model_client import FakeModelClient
from nl2sql.resolve.resolve import resolve, build_resolve_prompt

MODEL = SemanticModel.load("tests/fixtures/semantic_model.yaml")
IDX = SemanticIndex.build(MODEL, Glossary.load("tests/fixtures/glossary.yaml"),
                          MacroRegistry.load("tests/fixtures/macros.yaml"))
CHARTER = "Pharma. TRx = adjusted volume. CTE-first, no SELECT *."

FEASIBLE = """
{"feasible": true, "ir": {
  "ir_version": "1.0",
  "question": "weekly trx by indication for ibd",
  "metrics": ["trx_adjusted"],
  "dimensions": ["indication", "week_ending"],
  "filters": [{"ref": "filter.ibd_market"}],
  "grain": "indication x week"
}}
"""


def test_prompt_includes_candidates_and_charter():
    p = build_resolve_prompt("weekly trx by indication",
                             IDX.search("weekly trx by indication"), CHARTER)
    assert "indication" in p
    assert "TRx = adjusted volume" in p


def test_feasible_returns_ir():
    client = FakeModelClient(FEASIBLE)
    out = resolve("weekly trx by indication for ibd", MODEL, IDX, CHARTER, client)
    assert out.feasible is True
    assert out.ir is not None
    assert out.ir.metrics == ["trx_adjusted"]
    assert out.prompt != ""


def test_bad_json_is_infeasible_not_crash():
    out = resolve("q", MODEL, IDX, CHARTER, FakeModelClient("not json"))
    assert out.feasible is False
    assert "resolve_parse_error" in out.reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_resolve_feasible.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.resolve'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/resolve/__init__.py`: (empty file)

`src/nl2sql/resolve/resolve.py`:
```python
from __future__ import annotations
import json
from pydantic import BaseModel, ValidationError
from nl2sql.ir import QueryIntent
from nl2sql.semantic.model import SemanticModel
from nl2sql.retrieval.index import SemanticIndex, Candidates
from nl2sql.toolcontract.model_client import ModelClient

_SYSTEM = (
    "You translate a business question into a Query Intent IR by selecting ONLY "
    "from the provided candidate metrics/dimensions/filters/macros. Never invent "
    "names. Metrics and dimensions use the bare candidate name; filters use the "
    'form "filter.<name>" in the IR ref field. If the question needs a concept '
    "not in the candidates, return feasible=false with a concrete proposal. "
    'Reply ONLY with JSON: {"feasible": true, "ir": {...}} or '
    '{"feasible": false, "reason": "...", "proposal": "..."}.'
)


class ResolveOutcome(BaseModel):
    feasible: bool
    ir: QueryIntent | None = None
    reason: str = ""
    proposal: str = ""
    prompt: str = ""


def build_resolve_prompt(question: str, candidates: Candidates,
                         charter_text: str) -> str:
    return (
        f"CHARTER:\n{charter_text}\n\n"
        f"CANDIDATES:\n{candidates.model_dump_json(indent=2)}\n\n"
        f"QUESTION:\n{question}"
    )


def resolve(question: str, model: SemanticModel, index: SemanticIndex,
            charter_text: str, client: ModelClient) -> ResolveOutcome:
    prompt = build_resolve_prompt(question, index.search(question), charter_text)
    raw = client.complete(_SYSTEM, prompt)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return ResolveOutcome(feasible=False,
                              reason=f"resolve_parse_error: {e}", prompt=prompt)
    if not data.get("feasible"):
        return ResolveOutcome(feasible=False,
                              reason=data.get("reason", "infeasible"),
                              proposal=data.get("proposal", ""), prompt=prompt)
    try:
        ir = QueryIntent.model_validate(data["ir"])
    except (ValidationError, KeyError) as e:
        return ResolveOutcome(feasible=False,
                              reason=f"resolve_parse_error: {e}", prompt=prompt)
    return ResolveOutcome(feasible=True, ir=ir, prompt=prompt)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_resolve_feasible.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/resolve/ tests/test_resolve_feasible.py
git commit -m "feat: resolve feasible path + prompt builder (C-RES)"
```

---

### Task 4: Early feasibility exit + reference-existence guard

**Files:**
- Modify: `src/nl2sql/resolve/resolve.py` (add `_unknown_refs` + wire into `resolve`)
- Test: `tests/test_resolve_infeasible.py`

**Interfaces:**
- Consumes: as Task 3.
- Produces:
  - `unknown_refs(ir: QueryIntent, model: SemanticModel) -> list[str]` — names referenced by the IR (metrics, dimensions, filter `ref` keys) that do not exist in `model`. (Macros are validated by the compiler.)
  - `resolve(...)` now: when the LLM says feasible but the IR references an unknown name, the outcome is downgraded to `feasible=False`, `reason="retrieval_miss: <names>"` — the spec's early exit, so no guessed IR reaches the compiler.

- [ ] **Step 1: Write the failing test**

`tests/test_resolve_infeasible.py`:
```python
from nl2sql.semantic.model import SemanticModel
from nl2sql.semantic.macros import MacroRegistry
from nl2sql.retrieval.glossary import Glossary
from nl2sql.retrieval.index import SemanticIndex
from nl2sql.ir import QueryIntent, Filter
from nl2sql.toolcontract.model_client import FakeModelClient
from nl2sql.resolve.resolve import resolve, unknown_refs

MODEL = SemanticModel.load("tests/fixtures/semantic_model.yaml")
IDX = SemanticIndex.build(MODEL, Glossary.load("tests/fixtures/glossary.yaml"),
                          MacroRegistry.load("tests/fixtures/macros.yaml"))
CHARTER = "Pharma."

INFEASIBLE = ('{"feasible": false, "reason": "loyal writers undefined", '
              '"proposal": "define loyal as >=N scripts"}')

FEASIBLE_BAD_REF = """
{"feasible": true, "ir": {
  "ir_version": "1.0", "question": "q",
  "metrics": ["nonexistent_metric"], "dimensions": ["indication"],
  "filters": [], "grain": "indication"
}}
"""


def test_unknown_refs_detects_missing_metric():
    ir = QueryIntent(ir_version="1.0", question="q", metrics=["ghost"],
                     dimensions=["indication"], grain="g")
    assert unknown_refs(ir, MODEL) == ["metric:ghost"]


def test_unknown_refs_detects_missing_filter():
    ir = QueryIntent(ir_version="1.0", question="q", metrics=["trx_adjusted"],
                     dimensions=["indication"],
                     filters=[Filter(ref="filter.nope")], grain="g")
    assert unknown_refs(ir, MODEL) == ["filter:nope"]


def test_llm_infeasible_passes_through():
    out = resolve("loyal writers", MODEL, IDX, CHARTER,
                  FakeModelClient(INFEASIBLE))
    assert out.feasible is False
    assert "loyal writers" in out.reason
    assert "define loyal" in out.proposal


def test_feasible_but_unknown_ref_downgraded():
    out = resolve("q", MODEL, IDX, CHARTER, FakeModelClient(FEASIBLE_BAD_REF))
    assert out.feasible is False
    assert "retrieval_miss" in out.reason
    assert "metric:nonexistent_metric" in out.reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_resolve_infeasible.py -v`
Expected: FAIL — `ImportError: cannot import name 'unknown_refs'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/nl2sql/resolve/resolve.py` (above `resolve`):
```python
def unknown_refs(ir: QueryIntent, model: SemanticModel) -> list[str]:
    missing: list[str] = []
    for m in ir.metrics:
        if m not in model.metrics:
            missing.append(f"metric:{m}")
    for d in ir.dimensions:
        if d not in model.dimensions:
            missing.append(f"dimension:{d}")
    for f in ir.filters:
        key = f.ref.split(".", 1)[-1]
        if key not in model.filters:
            missing.append(f"filter:{key}")
    return missing
```

In `resolve`, replace the final feasible `return` with the guard:
```python
    try:
        ir = QueryIntent.model_validate(data["ir"])
    except (ValidationError, KeyError) as e:
        return ResolveOutcome(feasible=False,
                              reason=f"resolve_parse_error: {e}", prompt=prompt)
    missing = unknown_refs(ir, model)
    if missing:
        return ResolveOutcome(feasible=False,
                              reason=f"retrieval_miss: {missing}", prompt=prompt)
    return ResolveOutcome(feasible=True, ir=ir, prompt=prompt)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_resolve_infeasible.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/resolve/resolve.py tests/test_resolve_infeasible.py
git commit -m "feat: resolve early feasibility exit + ref guard (C-RES)"
```

---

### Task 5: Resolve → compile → verify end-to-end + run-folder artifacts

**Files:**
- Create: `src/nl2sql/resolve_pipeline.py`
- Test: `tests/test_resolve_pipeline_e2e.py`

**Interfaces:**
- Consumes: `resolve`/`ResolveOutcome` (Tasks 3–4), `SemanticIndex` (Task 2), `Glossary` (Task 1), and from core: `SemanticModel`, `MacroRegistry`, `GuardrailPolicy`, `Catalog`, `run_pipeline`/`PipelineResult`, `ModelClient`, `RunFolder`.
- Produces:
  - `class ResolvePipelineResult(BaseModel)`: `run_id: str`, `feasible: bool`, `passed: bool`, `reason: str = ""`, `run_dir: str`, `sql: str = ""`
  - `run_from_question(question, model, macros, policy, catalog, index, charter_text, resolve_client, judge_client, run_id, root) -> ResolvePipelineResult`
    - Calls `resolve`. Writes `00_question.txt`, `01_resolve.input.json` (the prompt), `01_resolve.output.json` (the outcome).
    - If infeasible → writes a `run_manifest.json` with `feasible=false`, returns early (early exit — no compile).
    - If feasible → delegates the IR to `run_pipeline` (compile + verify + its artifacts) in the **same** run folder, merges the verdict.

Note: `resolve_client` and `judge_client` are separate so the Resolve LLM and the V3 judge can be mocked independently in tests (and use different models in production).

- [ ] **Step 1: Write the failing test**

`tests/test_resolve_pipeline_e2e.py`:
```python
import json
import os
from nl2sql.semantic.model import SemanticModel
from nl2sql.semantic.macros import MacroRegistry
from nl2sql.guardrails.policy import GuardrailPolicy
from nl2sql.catalog.catalog import Catalog
from nl2sql.retrieval.glossary import Glossary
from nl2sql.retrieval.index import SemanticIndex
from nl2sql.toolcontract.model_client import FakeModelClient
from nl2sql.resolve_pipeline import run_from_question

MODEL = SemanticModel.load("config/semantic_model.yaml")
MACROS = MacroRegistry.load("config/macros.yaml")
POLICY = GuardrailPolicy.load("config/guardrails.yaml")
CAT = Catalog.load("config/catalog.yaml")
IDX = SemanticIndex.build(MODEL, Glossary.load("config/glossary.yaml"), MACROS)
CHARTER = "Pharma. TRx adjusted volume."

FEASIBLE = """
{"feasible": true, "ir": {
  "ir_version": "1.0", "question": "weekly trx by indication for ibd",
  "metrics": ["trx_adjusted"], "dimensions": ["indication", "week_ending"],
  "filters": [{"ref": "filter.ibd_market"}], "grain": "indication x week"
}}
"""
INFEASIBLE = '{"feasible": false, "reason": "x undefined", "proposal": "define x"}'


def test_feasible_runs_full_pipeline(tmp_path):
    res = run_from_question(
        "weekly trx by indication for ibd market", MODEL, MACROS, POLICY, CAT,
        IDX, CHARTER, resolve_client=FakeModelClient(FEASIBLE),
        judge_client=FakeModelClient('{"passed": true, "reasons": []}'),
        run_id="run_2026-06-18_010", root=str(tmp_path))
    assert res.feasible is True and res.passed is True
    assert "SUM(WEEKLY.TRX_ADJUSTED)" in res.sql
    for f in ["00_question.txt", "01_resolve.input.json", "01_resolve.output.json",
              "02_compile.output.sql", "03_verify.V1.json", "run_manifest.json"]:
        assert os.path.isfile(os.path.join(res.run_dir, f)), f


def test_infeasible_exits_early(tmp_path):
    res = run_from_question(
        "show me loyal writers", MODEL, MACROS, POLICY, CAT, IDX, CHARTER,
        resolve_client=FakeModelClient(INFEASIBLE),
        judge_client=FakeModelClient('{"passed": true, "reasons": []}'),
        run_id="run_2026-06-18_011", root=str(tmp_path))
    assert res.feasible is False and res.passed is False
    assert "x undefined" in res.reason
    # early exit: no compiled SQL artifact
    assert not os.path.isfile(os.path.join(res.run_dir, "02_compile.output.sql"))
    with open(os.path.join(res.run_dir, "run_manifest.json"), encoding="utf-8") as fh:
        assert json.load(fh)["feasible"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_resolve_pipeline_e2e.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.resolve_pipeline'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/resolve_pipeline.py`:
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
from nl2sql.obs.run import RunFolder
from nl2sql.pipeline import run_pipeline


class ResolvePipelineResult(BaseModel):
    run_id: str
    feasible: bool
    passed: bool
    reason: str = ""
    run_dir: str
    sql: str = ""


def run_from_question(question: str, model: SemanticModel, macros: MacroRegistry,
                      policy: GuardrailPolicy, catalog: Catalog,
                      index: SemanticIndex, charter_text: str,
                      resolve_client: ModelClient, judge_client: ModelClient,
                      run_id: str, root: str) -> ResolvePipelineResult:
    rf = RunFolder(run_id, root)
    rf.write_text("00_question.txt", question)

    outcome = resolve(question, model, index, charter_text, resolve_client)
    rf.write_json("01_resolve.input.json", {"prompt": outcome.prompt})
    rf.write_json("01_resolve.output.json", outcome.model_dump())

    if not outcome.feasible or outcome.ir is None:
        rf.write_manifest({"run_id": run_id, "feasible": False,
                           "passed": False, "reason": outcome.reason})
        return ResolvePipelineResult(run_id=run_id, feasible=False, passed=False,
                                     reason=outcome.reason, run_dir=rf.dir)

    # Feasible: reuse the core pipeline in the SAME run folder.
    pr = run_pipeline(outcome.ir, model, macros, policy, catalog,
                      judge_client, run_id=run_id, root=root)
    return ResolvePipelineResult(run_id=run_id, feasible=True, passed=pr.passed,
                                 run_dir=pr.run_dir, sql=pr.sql)
```

Note: `run_pipeline` (core Task 15) writes into `RunFolder(run_id, root)`, i.e. the same `root/run_id/` directory created here, so the resolve artifacts and the compile/verify artifacts land together. `run_pipeline` overwrites its own `run_manifest.json` with the feasible verdict — intended.

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_resolve_pipeline_e2e.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the whole suite + commit**

Run: `py -3 -m pytest -v`
Expected: PASS (core + P4a tests all green).

```bash
git add src/nl2sql/resolve_pipeline.py tests/test_resolve_pipeline_e2e.py
git commit -m "feat: resolve->compile->verify pipeline + 01_resolve artifacts (C-RES)"
```

---

## Done criteria
- `py -3 -m pytest -v` green (core + P4a).
- A plain-English question yields either a validated IR that flows through compile+verify to SQL, or a clean feasibility refusal with a proposal — never a guessed IR.
- Retrieval is deterministic; the reference-existence guard blocks any IR naming something absent from the semantic model.
- Run folder now carries `00_question.txt` + `01_resolve.input.json`/`01_resolve.output.json` alongside the compile/verify artifacts.

## Follow-on (next plans)
- **P4b** (C-RCA, C-REP, C-ADPT-CC): RCA fault localization, RCA-routed repair loop, Claude Code adapter.
- **P5** (C-EVAL): golden-set eval harness.
- **P6** (C-ADPT-API): Anthropic API agent adapter.

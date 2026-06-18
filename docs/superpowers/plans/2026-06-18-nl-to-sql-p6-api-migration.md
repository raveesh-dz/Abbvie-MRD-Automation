# NL → SQL — P6: Anthropic API Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the exact same NL→SQL system on the pure Anthropic API instead of Claude Code — by binding `model_client` to the Anthropic SDK and registering the identical `TOOL_SCHEMAS` in a tool-use agent loop — proving the migration touches no core logic.

**Architecture:** Three thin additions in the adapter layer. `anthropic_tool_defs()` converts the L2 `TOOL_SCHEMAS` into Anthropic tool definitions. `AnthropicModelClient` implements the `ModelClient` seam by delegating to an *injected* `messages.create` callable (so tests inject a fake; production injects `anthropic.Anthropic().messages.create`). `run_agent()` drives the standard Anthropic tool-use loop, dispatching every tool call through the **unchanged** P4b `build_tool_dispatch`. No file under `nl2sql/{ir,compiler,verify,semantic,guardrails,catalog,resolve,rca,repair,eval}` is modified — migration = a new adapter + a rebound client.

**Tech Stack:** Same as core — Python 3.14 (`py -3`), `pydantic>=2`, `pytest`. The `anthropic` SDK is a production-only dependency; tests inject a fake `messages.create`, so no network and no SDK import in the test path.

**Depends on:** core + P4a + P4b (uses `TOOL_SCHEMAS`/`tool_names`, `build_tool_dispatch`, `ModelClient`). Implements **C-ADPT-API** (spec roadmap P6).

**Spec reference:** `docs/superpowers/specs/2026-06-18-nl-to-sql-semantic-compiler-design.md` §3 (portability seam: "rebind `model_client` + re-register the same L2 tools; no L1 rewrite"), §10 (P6).

## Global Constraints
- Run Python with `py -3`.
- **No core changes.** This plan only adds files under `src/nl2sql/adapter/`. If a task seems to need a core edit, stop — the seam is wrong.
- The agent registers the **identical** `TOOL_SCHEMAS` and dispatches through the **identical** P4b `build_tool_dispatch`. Parity is the deliverable.
- `model_client` is reached only via injection — tests never import or call the `anthropic` SDK.

---

### Task 1: Anthropic tool definitions (C-ADPT-API)

**Files:**
- Create: `src/nl2sql/adapter/anthropic_api.py`
- Test: `tests/test_anthropic_tool_defs.py`

**Interfaces:**
- Consumes: `TOOL_SCHEMAS`/`tool_names` (core Task 14).
- Produces:
  - `anthropic_tool_defs() -> list[dict]` — one dict per tool with `name`, `description`, `input_schema` (the Anthropic tool-definition shape), derived 1:1 from `TOOL_SCHEMAS`.

- [ ] **Step 1: Write the failing test**

`tests/test_anthropic_tool_defs.py`:
```python
from nl2sql.toolcontract.schemas import tool_names
from nl2sql.adapter.anthropic_api import anthropic_tool_defs


def test_defs_match_tool_contract():
    defs = anthropic_tool_defs()
    assert {d["name"] for d in defs} == set(tool_names())


def test_each_def_has_anthropic_shape():
    for d in anthropic_tool_defs():
        assert set(d.keys()) == {"name", "description", "input_schema"}
        assert d["input_schema"]["type"] == "object"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_anthropic_tool_defs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.adapter.anthropic_api'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/adapter/anthropic_api.py`:
```python
from __future__ import annotations
from nl2sql.toolcontract.schemas import TOOL_SCHEMAS


def anthropic_tool_defs() -> list[dict]:
    return [
        {"name": s["name"], "description": s["description"],
         "input_schema": s["input_schema"]}
        for s in TOOL_SCHEMAS.values()
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_anthropic_tool_defs.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/adapter/anthropic_api.py tests/test_anthropic_tool_defs.py
git commit -m "feat: anthropic tool definitions from TOOL_SCHEMAS (C-ADPT-API)"
```

---

### Task 2: AnthropicModelClient (the rebound seam)

**Files:**
- Modify: `src/nl2sql/adapter/anthropic_api.py` (add `AnthropicModelClient`)
- Test: `tests/test_anthropic_model_client.py`

**Interfaces:**
- Consumes: `ModelClient` protocol (core Task 11) — implemented structurally.
- Produces:
  - `class AnthropicModelClient`: `__init__(self, messages_create, model: str = "claude-opus-4-8", max_tokens: int = 2048)`. `messages_create` is a callable with the SDK's `messages.create(**kwargs)` signature, returning an object with `.content` (a list of blocks, each having `.type` and, for text blocks, `.text`).
  - `.complete(self, system: str, user: str) -> str` — calls `messages_create(model=..., max_tokens=..., system=system, messages=[{"role": "user", "content": user}])` and returns the concatenated text of all `type == "text"` content blocks.

Production binding (documented, not tested — no network): `AnthropicModelClient(anthropic.Anthropic().messages.create)`. The same instance is passed wherever the core/P4b code expects a `ModelClient` (Resolve, the V3 judge, the repair loop).

- [ ] **Step 1: Write the failing test**

`tests/test_anthropic_model_client.py`:
```python
from types import SimpleNamespace
from nl2sql.adapter.anthropic_api import AnthropicModelClient


def _fake_create(**kwargs):
    # echo: capture kwargs, return a single text block
    _fake_create.last = kwargs
    return SimpleNamespace(content=[SimpleNamespace(type="text",
                                                    text='{"passed": true}')])


def test_complete_returns_text_and_passes_params():
    client = AnthropicModelClient(_fake_create, model="claude-opus-4-8")
    out = client.complete("SYS", "USER")
    assert out == '{"passed": true}'
    assert _fake_create.last["model"] == "claude-opus-4-8"
    assert _fake_create.last["system"] == "SYS"
    assert _fake_create.last["messages"][0]["content"] == "USER"


def test_concatenates_multiple_text_blocks():
    def create(**kwargs):
        return SimpleNamespace(content=[
            SimpleNamespace(type="text", text="a"),
            SimpleNamespace(type="text", text="b")])
    assert AnthropicModelClient(create).complete("s", "u") == "ab"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_anthropic_model_client.py -v`
Expected: FAIL — `ImportError: cannot import name 'AnthropicModelClient'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/nl2sql/adapter/anthropic_api.py`:
```python
class AnthropicModelClient:
    """Implements the ModelClient seam over an injected messages.create callable."""

    def __init__(self, messages_create, model: str = "claude-opus-4-8",
                 max_tokens: int = 2048) -> None:
        self._create = messages_create
        self._model = model
        self._max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        resp = self._create(
            model=self._model, max_tokens=self._max_tokens, system=system,
            messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in resp.content
                       if getattr(b, "type", None) == "text")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_anthropic_model_client.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/adapter/anthropic_api.py tests/test_anthropic_model_client.py
git commit -m "feat: AnthropicModelClient seam binding (C-ADPT-API)"
```

---

### Task 3: Tool-use agent loop (C-ADPT-API)

**Files:**
- Modify: `src/nl2sql/adapter/anthropic_api.py` (add `run_agent`)
- Test: `tests/test_anthropic_agent.py`

**Interfaces:**
- Consumes: a dispatch table (P4b `build_tool_dispatch`), `anthropic_tool_defs` (Task 1), an injected `messages_create` callable.
- Produces:
  - `run_agent(question: str, dispatch: dict, messages_create, system: str = "", max_turns: int = 8) -> str` — the standard Anthropic tool-use loop:
    1. Seed `messages = [{"role": "user", "content": question}]`.
    2. Call `messages_create(model=..., max_tokens=..., system=system, messages=messages, tools=anthropic_tool_defs())`.
    3. If `resp.stop_reason == "tool_use"`: append the assistant turn (`resp.content`), dispatch each `tool_use` block through `dispatch[name](input)`, append a user turn of `tool_result` blocks (`{"type": "tool_result", "tool_use_id": block.id, "content": <result>}`), loop.
    4. Else: return the concatenated text of `resp.content` text blocks (the final SQL or refusal).
    5. Exceeding `max_turns` raises `RuntimeError`.
  - The agent embeds a `model`/`max_tokens` default consistent with `AnthropicModelClient` (`"claude-opus-4-8"`, `2048`).

- [ ] **Step 1: Write the failing test**

`tests/test_anthropic_agent.py`:
```python
from types import SimpleNamespace
from nl2sql.semantic.model import SemanticModel
from nl2sql.semantic.macros import MacroRegistry
from nl2sql.guardrails.policy import GuardrailPolicy
from nl2sql.catalog.catalog import Catalog
from nl2sql.retrieval.glossary import Glossary
from nl2sql.retrieval.index import SemanticIndex
from nl2sql.rca.signature_map import SignatureMap
from nl2sql.toolcontract.model_client import FakeModelClient
from nl2sql.adapter.claude_code import build_tool_dispatch
from nl2sql.adapter.anthropic_api import run_agent

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


class ScriptedCreate:
    def __init__(self, responses):
        self._responses = responses
        self._i = 0
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        r = self._responses[self._i]
        self._i += 1
        return r


def test_agent_dispatches_tool_then_returns_final_text():
    tool_use = SimpleNamespace(stop_reason="tool_use", content=[
        SimpleNamespace(type="tool_use", id="t1", name="compile_ir",
                        input={"ir": IR})])
    final = SimpleNamespace(stop_reason="end_turn", content=[
        SimpleNamespace(type="text", text="DONE")])
    create = ScriptedCreate([tool_use, final])

    out = run_agent("weekly trx by indication for ibd", DISPATCH, create)
    assert out == "DONE"
    # second call carried the tool_result with the compiled SQL.
    # (assistant content holds SimpleNamespace blocks; only user tool_result
    #  blocks are dicts, so guard with isinstance before .get)
    second_msgs = create.calls[1]["messages"]
    tool_results = [b for m in second_msgs if isinstance(m.get("content"), list)
                    for b in m["content"]
                    if isinstance(b, dict) and b.get("type") == "tool_result"]
    assert tool_results and "sql" in tool_results[0]["content"]
    assert create.calls[0]["tools"]  # tools were registered


def test_agent_max_turns_raises():
    loop = SimpleNamespace(stop_reason="tool_use", content=[
        SimpleNamespace(type="tool_use", id="t", name="compile_ir",
                        input={"ir": IR})])
    create = ScriptedCreate([loop] * 10)
    import pytest
    with pytest.raises(RuntimeError):
        run_agent("q", DISPATCH, create, max_turns=3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_anthropic_agent.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_agent'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/nl2sql/adapter/anthropic_api.py`:
```python
_MODEL = "claude-opus-4-8"
_MAX_TOKENS = 2048


def run_agent(question: str, dispatch: dict, messages_create,
              system: str = "", max_turns: int = 8) -> str:
    messages: list[dict] = [{"role": "user", "content": question}]
    tools = anthropic_tool_defs()
    for _ in range(max_turns):
        resp = messages_create(model=_MODEL, max_tokens=_MAX_TOKENS,
                               system=system, messages=messages, tools=tools)
        if getattr(resp, "stop_reason", None) != "tool_use":
            return "".join(b.text for b in resp.content
                           if getattr(b, "type", None) == "text")
        messages.append({"role": "assistant", "content": resp.content})
        tool_results = []
        for b in resp.content:
            if getattr(b, "type", None) == "tool_use":
                result = dispatch[b.name](b.input)
                tool_results.append({"type": "tool_result",
                                     "tool_use_id": b.id, "content": result})
        messages.append({"role": "user", "content": tool_results})
    raise RuntimeError("run_agent exceeded max_turns")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_anthropic_agent.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/adapter/anthropic_api.py tests/test_anthropic_agent.py
git commit -m "feat: anthropic tool-use agent loop (C-ADPT-API)"
```

---

### Task 4: Migration parity test (no core changes)

**Files:**
- Test: `tests/test_migration_parity.py`

**Interfaces:**
- Consumes: both adapters + the tool contract. No new production code — this task asserts the portability claim.

The deliverable of P6 is parity, so the test *is* the deliverable: the Anthropic agent registers the identical tools and dispatches through the identical P4b table, and the `compile_ir` tool produces byte-identical SQL whether reached via the Claude Code dispatch directly or via the agent loop.

- [ ] **Step 1: Write the failing test**

`tests/test_migration_parity.py`:
```python
from types import SimpleNamespace
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
from nl2sql.adapter.anthropic_api import anthropic_tool_defs, run_agent

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


def test_agent_tools_identical_to_contract_and_dispatch():
    names = {d["name"] for d in anthropic_tool_defs()}
    assert names == set(tool_names()) == set(DISPATCH.keys())


def test_sql_identical_direct_vs_via_agent():
    direct = DISPATCH["compile_ir"]({"ir": IR})["sql"]

    captured = {}

    def create(**kwargs):
        # turn 1: ask for compile_ir; turn 2: echo the SQL the tool produced
        if "captured" not in captured:
            return SimpleNamespace(stop_reason="tool_use", content=[
                SimpleNamespace(type="tool_use", id="t1", name="compile_ir",
                                input={"ir": IR})])
        return SimpleNamespace(stop_reason="end_turn", content=[
            SimpleNamespace(type="text", text=captured["sql"])])

    # capture the tool_result SQL between turns by wrapping dispatch
    base = DISPATCH["compile_ir"]
    def spy(args):
        out = base(args)
        captured["sql"] = out["sql"]
        captured["captured"] = True
        return out
    spy_dispatch = dict(DISPATCH, compile_ir=spy)

    via_agent = run_agent("weekly trx by indication", spy_dispatch, create)
    assert via_agent == direct
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_migration_parity.py -v`
Expected: FAIL — until Tasks 1–3 exist this import/behavior is unavailable (run after they are implemented; expected PASS then).

- [ ] **Step 3: No new implementation**

This task adds no production code. If it fails, the defect is in Tasks 1–3 or indicates an accidental core change — fix there, never by editing the test to pass.

- [ ] **Step 4: Run the whole suite + commit**

Run: `py -3 -m pytest -v`
Expected: PASS (core + P4a + P4b + P5 + P6 all green).

```bash
git add tests/test_migration_parity.py
git commit -m "test: migration parity — agent reuses identical tools + dispatch (C-ADPT-API)"
```

---

## Done criteria
- `py -3 -m pytest -v` green (core + P4a + P4b + P5 + P6).
- `AnthropicModelClient` satisfies the `ModelClient` seam; `run_agent` drives a tool-use loop registering the identical `TOOL_SCHEMAS` and dispatching through the unchanged P4b table.
- Parity proven: the agent's tool names equal the contract and the dispatch keys, and `compile_ir` yields byte-identical SQL directly vs via the agent.
- **No file outside `src/nl2sql/adapter/` was modified** — the migration is purely a rebound `model_client` + a new adapter, exactly as the spec's three-layer design promised.

## Production wiring (out of test scope, documented)
- Install `anthropic`; bind `create = anthropic.Anthropic().messages.create`.
- `model_client = AnthropicModelClient(create)` — pass it wherever a `ModelClient` is expected (Resolve, V3 judge, repair loop), exactly where a Claude Code skill previously bound the harness client.
- Drive either via `run_repair(...)` (deterministic orchestration in code) or `run_agent(...)` (model-driven tool-use loop) — both reuse the same core and dispatch.

## End state
With P1–P6 complete, the system spans: governed semantic layer + macros + charter → deterministic compiler → 4-verifier gate → RCA + repair loop → NL→IR Resolve → eval harness → portable across Claude Code and the Anthropic API. Remaining spec follow-ons (live Snowflake dry-run / V4 activation, macro SQL inlining with declared-join compilation, embeddings-based retrieval) are independent enhancements layered on this foundation.

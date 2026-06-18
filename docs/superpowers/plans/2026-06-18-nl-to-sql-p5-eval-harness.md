# NL → SQL — P5: Eval Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer "is the system working?" across many questions — a golden set of NL cases with recorded LLM responses, run through the full resolve→compile→verify→repair flow, scored for match against expectations, with a pass-rate + RCA-layer report.

**Architecture:** A golden set (cases with the NL question, the *recorded* Resolve and judge responses, and the expected outcome) loaded from YAML. The harness replays each case by binding `FakeModelClient`s built from the recorded responses — so the suite is fully deterministic in CI with no live LLM — runs `run_repair`, and compares the actual outcome to the expectation. Aggregation yields a match rate, actual-pass count, and RCA-layer distribution; a renderer emits Markdown + JSON.

**Tech Stack:** Same as core — Python 3.14 (`py -3`), `pydantic>=2`, `pyyaml`, `pytest`.

**Depends on:** core + P4a + P4b. Uses `run_repair`/`RepairResult`, the loaders, `SemanticIndex`, `SignatureMap`, `FakeModelClient`. Implements **C-EVAL** (spec roadmap P5).

**Spec reference:** `docs/superpowers/specs/2026-06-18-nl-to-sql-semantic-compiler-design.md` §2 (self-verifying goal), §7 (eval dashboard: golden-set pass rate, RCA layer-distribution).

## Global Constraints
- Run Python with `py -3`.
- The eval suite is **deterministic** — recorded responses replayed via `FakeModelClient`, no network. (Recording new responses from a live model is a manual, out-of-band step; not part of CI.)
- The golden set is governed data — every change is its own commit.
- A case **matches** iff actual pass/fail equals expected, the RCA layer matches when the case expects a failure layer, and all `sql_contains` substrings are present when the case expects a pass.

---

### Task 1: Golden set loader (C-EVAL data)

**Files:**
- Create: `src/nl2sql/eval/__init__.py`
- Create: `src/nl2sql/eval/golden.py`
- Create: `config/golden_set.yaml`
- Test: `tests/test_golden.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class GoldenCase(BaseModel)`: `id: str`, `question: str`, `resolve_response: str`, `judge_response: str`, `expect_pass: bool`, `expect_layer: str | None = None`, `sql_contains: list[str] = []`
  - `class GoldenSet(BaseModel)`: `cases: list[GoldenCase]`
  - `GoldenSet.load(path: str) -> GoldenSet`

- [ ] **Step 1: Write the failing test**

`config/golden_set.yaml`:
```yaml
cases:
  - id: tremfya_ibd_split
    question: "weekly trx by indication for ibd market"
    resolve_response: |
      {"feasible": true, "ir": {
        "ir_version": "1.0", "question": "weekly trx by indication for ibd",
        "metrics": ["trx_adjusted"], "dimensions": ["indication", "week_ending"],
        "filters": [{"ref": "filter.ibd_market"}], "grain": "indication x week"}}
    judge_response: '{"passed": true, "reasons": []}'
    expect_pass: true
    sql_contains: ["SUM(WEEKLY.TRX_ADJUSTED)", "GROUP BY INDICATION, WEEK_ENDING"]
  - id: loyal_writers_gap
    question: "show me the loyal writers"
    resolve_response: '{"feasible": false, "reason": "loyal writers undefined", "proposal": "define loyal as >=N scripts"}'
    judge_response: '{"passed": true, "reasons": []}'
    expect_pass: false
    expect_layer: semantic
```

`tests/test_golden.py`:
```python
from nl2sql.eval.golden import GoldenSet

GS = GoldenSet.load("config/golden_set.yaml")


def test_loads_cases():
    assert len(GS.cases) == 2
    ids = [c.id for c in GS.cases]
    assert "tremfya_ibd_split" in ids and "loyal_writers_gap" in ids


def test_case_fields():
    c = next(c for c in GS.cases if c.id == "tremfya_ibd_split")
    assert c.expect_pass is True
    assert "SUM(WEEKLY.TRX_ADJUSTED)" in c.sql_contains
    gap = next(c for c in GS.cases if c.id == "loyal_writers_gap")
    assert gap.expect_pass is False and gap.expect_layer == "semantic"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_golden.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.eval'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/eval/__init__.py`: (empty file)

`src/nl2sql/eval/golden.py`:
```python
from __future__ import annotations
import yaml
from pydantic import BaseModel


class GoldenCase(BaseModel):
    id: str
    question: str
    resolve_response: str
    judge_response: str
    expect_pass: bool
    expect_layer: str | None = None
    sql_contains: list[str] = []


class GoldenSet(BaseModel):
    cases: list[GoldenCase]

    @classmethod
    def load(cls, path: str) -> "GoldenSet":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.model_validate(yaml.safe_load(fh))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_golden.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/eval/__init__.py src/nl2sql/eval/golden.py config/golden_set.yaml tests/test_golden.py
git commit -m "feat: golden set loader (C-EVAL data)"
```

---

### Task 2: Eval harness — run_eval (C-EVAL)

**Files:**
- Create: `src/nl2sql/eval/harness.py`
- Test: `tests/test_harness.py`

**Interfaces:**
- Consumes: `GoldenSet`/`GoldenCase` (Task 1), `run_repair`/`RepairResult` (P4b Task 4), `FakeModelClient` (core), the loaders, `SemanticIndex`, `SignatureMap`.
- Produces:
  - `class EvalCaseResult(BaseModel)`: `id: str`, `matched: bool`, `actual_pass: bool`, `final_layer: str = ""`, `attempts: int`
  - `class EvalReport(BaseModel)`: `total: int`, `matched: int`, `match_rate: float`, `actual_pass_count: int`, `layer_distribution: dict[str, int]`, `cases: list[EvalCaseResult]`
  - `evaluate_case(case, result: RepairResult) -> EvalCaseResult` — pure scoring (no I/O), so it is independently testable.
  - `run_eval(golden, model, macros, policy, catalog, index, charter_text, sigmap, root) -> EvalReport`

Scoring (`evaluate_case`): `pass_ok = result.passed == case.expect_pass`; `layer_ok = case.expect_layer is None or result.final_layer == case.expect_layer`; `sql_ok = (not case.expect_pass) or all(s in result.sql for s in case.sql_contains)`; `matched = pass_ok and layer_ok and sql_ok`. `match_rate = matched/total` (0.0 if total 0). `layer_distribution` counts `final_layer` over cases that did not pass.

- [ ] **Step 1: Write the failing test**

`tests/test_harness.py`:
```python
from nl2sql.eval.golden import GoldenSet, GoldenCase
from nl2sql.eval.harness import run_eval, evaluate_case, EvalCaseResult
from nl2sql.repair.loop import RepairResult
from nl2sql.semantic.model import SemanticModel
from nl2sql.semantic.macros import MacroRegistry
from nl2sql.guardrails.policy import GuardrailPolicy
from nl2sql.catalog.catalog import Catalog
from nl2sql.retrieval.glossary import Glossary
from nl2sql.retrieval.index import SemanticIndex
from nl2sql.rca.signature_map import SignatureMap

MODEL = SemanticModel.load("config/semantic_model.yaml")
MACROS = MacroRegistry.load("config/macros.yaml")
POLICY = GuardrailPolicy.load("config/guardrails.yaml")
CAT = Catalog.load("config/catalog.yaml")
IDX = SemanticIndex.build(MODEL, Glossary.load("config/glossary.yaml"), MACROS)
SM = SignatureMap.load("config/rca_signatures.yaml")
CHARTER = "Pharma."


def test_evaluate_case_pass_match():
    case = GoldenCase(id="c", question="q", resolve_response="{}",
                      judge_response="{}", expect_pass=True,
                      sql_contains=["SUM"])
    res = RepairResult(run_id="r", passed=True, attempts=1,
                       sql="SELECT SUM(x) FROM t", run_dir="/d")
    assert evaluate_case(case, res).matched is True


def test_evaluate_case_layer_mismatch():
    case = GoldenCase(id="c", question="q", resolve_response="{}",
                      judge_response="{}", expect_pass=False,
                      expect_layer="semantic")
    res = RepairResult(run_id="r", passed=False, attempts=1, run_dir="/d",
                       final_layer="schema_drift")
    assert evaluate_case(case, res).matched is False


def test_run_eval_full_golden_set(tmp_path):
    gs = GoldenSet.load("config/golden_set.yaml")
    report = run_eval(gs, MODEL, MACROS, POLICY, CAT, IDX, CHARTER, SM,
                      root=str(tmp_path))
    assert report.total == 2
    assert report.match_rate == 1.0
    assert report.actual_pass_count == 1
    assert report.layer_distribution.get("semantic") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_harness.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.eval.harness'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/eval/harness.py`:
```python
from __future__ import annotations
from pydantic import BaseModel
from nl2sql.eval.golden import GoldenSet, GoldenCase
from nl2sql.repair.loop import run_repair, RepairResult
from nl2sql.toolcontract.model_client import FakeModelClient


class EvalCaseResult(BaseModel):
    id: str
    matched: bool
    actual_pass: bool
    final_layer: str = ""
    attempts: int


class EvalReport(BaseModel):
    total: int
    matched: int
    match_rate: float
    actual_pass_count: int
    layer_distribution: dict[str, int]
    cases: list[EvalCaseResult]


def evaluate_case(case: GoldenCase, result: RepairResult) -> EvalCaseResult:
    pass_ok = result.passed == case.expect_pass
    layer_ok = case.expect_layer is None or result.final_layer == case.expect_layer
    sql_ok = (not case.expect_pass) or all(s in result.sql
                                           for s in case.sql_contains)
    return EvalCaseResult(id=case.id, matched=pass_ok and layer_ok and sql_ok,
                          actual_pass=result.passed,
                          final_layer=result.final_layer, attempts=result.attempts)


def run_eval(golden: GoldenSet, model, macros, policy, catalog, index,
             charter_text, sigmap, root: str) -> EvalReport:
    cases: list[EvalCaseResult] = []
    layer_dist: dict[str, int] = {}
    for case in golden.cases:
        res = run_repair(
            case.question, model, macros, policy, catalog, index, charter_text,
            sigmap, resolve_client=FakeModelClient(case.resolve_response),
            judge_client=FakeModelClient(case.judge_response),
            run_id=f"eval_{case.id}", root=root)
        cr = evaluate_case(case, res)
        cases.append(cr)
        if not res.passed and res.final_layer:
            layer_dist[res.final_layer] = layer_dist.get(res.final_layer, 0) + 1
    total = len(cases)
    matched = sum(1 for c in cases if c.matched)
    return EvalReport(
        total=total, matched=matched,
        match_rate=(matched / total if total else 0.0),
        actual_pass_count=sum(1 for c in cases if c.actual_pass),
        layer_distribution=layer_dist, cases=cases)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_harness.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/eval/harness.py tests/test_harness.py
git commit -m "feat: eval harness run_eval (C-EVAL)"
```

---

### Task 3: Report renderer — Markdown + JSON

**Files:**
- Create: `src/nl2sql/eval/report.py`
- Test: `tests/test_eval_report.py`

**Interfaces:**
- Consumes: `EvalReport`/`EvalCaseResult` (Task 2).
- Produces:
  - `to_markdown(report: EvalReport) -> str` — a summary header (match rate, pass count, layer distribution) + a per-case table.
  - `write_report(report: EvalReport, dir_path: str) -> tuple[str, str]` — writes `eval_report.json` (the model dump) and `eval_report.md` (the markdown); returns both paths.

- [ ] **Step 1: Write the failing test**

`tests/test_eval_report.py`:
```python
import json
import os
from nl2sql.eval.harness import EvalReport, EvalCaseResult
from nl2sql.eval.report import to_markdown, write_report

REPORT = EvalReport(
    total=2, matched=2, match_rate=1.0, actual_pass_count=1,
    layer_distribution={"semantic": 1},
    cases=[EvalCaseResult(id="a", matched=True, actual_pass=True, attempts=1),
           EvalCaseResult(id="b", matched=True, actual_pass=False,
                          final_layer="semantic", attempts=1)])


def test_markdown_has_summary_and_rows():
    md = to_markdown(REPORT)
    assert "Match rate: 100.0%" in md
    assert "| a |" in md and "| b |" in md
    assert "semantic" in md


def test_write_report_emits_both_files(tmp_path):
    j, m = write_report(REPORT, str(tmp_path))
    assert os.path.isfile(j) and os.path.isfile(m)
    with open(j, encoding="utf-8") as fh:
        assert json.load(fh)["match_rate"] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_eval_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.eval.report'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/eval/report.py`:
```python
from __future__ import annotations
import json
import os
from nl2sql.eval.harness import EvalReport


def to_markdown(report: EvalReport) -> str:
    lines = [
        "# Eval Report",
        "",
        f"- Match rate: {report.match_rate * 100:.1f}% "
        f"({report.matched}/{report.total})",
        f"- Cases that passed: {report.actual_pass_count}/{report.total}",
        f"- Failure layers: {report.layer_distribution or '{}'}",
        "",
        "| id | matched | passed | layer | attempts |",
        "|----|---------|--------|-------|----------|",
    ]
    for c in report.cases:
        lines.append(f"| {c.id} | {c.matched} | {c.actual_pass} | "
                     f"{c.final_layer or '-'} | {c.attempts} |")
    return "\n".join(lines) + "\n"


def write_report(report: EvalReport, dir_path: str) -> tuple[str, str]:
    os.makedirs(dir_path, exist_ok=True)
    jpath = os.path.join(dir_path, "eval_report.json")
    mpath = os.path.join(dir_path, "eval_report.md")
    with open(jpath, "w", encoding="utf-8") as fh:
        json.dump(report.model_dump(), fh, indent=2, sort_keys=True)
    with open(mpath, "w", encoding="utf-8") as fh:
        fh.write(to_markdown(report))
    return jpath, mpath
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_eval_report.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/eval/report.py tests/test_eval_report.py
git commit -m "feat: eval report renderer (markdown + json)"
```

---

### Task 4: Eval runner entrypoint + CI gate

**Files:**
- Create: `src/nl2sql/eval/run.py`
- Test: `tests/test_eval_run.py`

**Interfaces:**
- Consumes: everything in this plan + the loaders + `SemanticIndex`/`Glossary` + `SignatureMap`.
- Produces:
  - `run_eval_from_config(config_dir: str, out_dir: str, charter_text: str = "") -> EvalReport` — loads every governed input from `config_dir` (`semantic_model.yaml`, `macros.yaml`, `guardrails.yaml`, `catalog.yaml`, `glossary.yaml`, `rca_signatures.yaml`, `golden_set.yaml`), builds the index, runs the eval, writes the report into `out_dir`, returns the report.
  - `gate(report: EvalReport, threshold: float = 1.0) -> bool` — `True` iff `match_rate >= threshold`. A CI step asserts this.

- [ ] **Step 1: Write the failing test**

`tests/test_eval_run.py`:
```python
import os
from nl2sql.eval.run import run_eval_from_config, gate


def test_run_from_config_writes_report_and_passes_gate(tmp_path):
    report = run_eval_from_config("config", str(tmp_path), charter_text="Pharma.")
    assert report.total == 2
    assert os.path.isfile(os.path.join(str(tmp_path), "eval_report.md"))
    assert os.path.isfile(os.path.join(str(tmp_path), "eval_report.json"))
    assert gate(report, threshold=1.0) is True


def test_gate_fails_below_threshold():
    from nl2sql.eval.harness import EvalReport
    low = EvalReport(total=2, matched=1, match_rate=0.5, actual_pass_count=1,
                     layer_distribution={}, cases=[])
    assert gate(low, threshold=1.0) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_eval_run.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.eval.run'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/eval/run.py`:
```python
from __future__ import annotations
import os
from nl2sql.semantic.model import SemanticModel
from nl2sql.semantic.macros import MacroRegistry
from nl2sql.guardrails.policy import GuardrailPolicy
from nl2sql.catalog.catalog import Catalog
from nl2sql.retrieval.glossary import Glossary
from nl2sql.retrieval.index import SemanticIndex
from nl2sql.rca.signature_map import SignatureMap
from nl2sql.eval.golden import GoldenSet
from nl2sql.eval.harness import run_eval, EvalReport
from nl2sql.eval.report import write_report


def run_eval_from_config(config_dir: str, out_dir: str,
                         charter_text: str = "") -> EvalReport:
    def p(name: str) -> str:
        return os.path.join(config_dir, name)

    model = SemanticModel.load(p("semantic_model.yaml"))
    macros = MacroRegistry.load(p("macros.yaml"))
    policy = GuardrailPolicy.load(p("guardrails.yaml"))
    catalog = Catalog.load(p("catalog.yaml"))
    glossary = Glossary.load(p("glossary.yaml"))
    sigmap = SignatureMap.load(p("rca_signatures.yaml"))
    golden = GoldenSet.load(p("golden_set.yaml"))
    index = SemanticIndex.build(model, glossary, macros)

    report = run_eval(golden, model, macros, policy, catalog, index,
                      charter_text, sigmap, root=os.path.join(out_dir, "runs"))
    write_report(report, out_dir)
    return report


def gate(report: EvalReport, threshold: float = 1.0) -> bool:
    return report.match_rate >= threshold
```

- [ ] **Step 4: Run the whole suite + commit**

Run: `py -3 -m pytest -v`
Expected: PASS (core + P4a + P4b + P5 all green).

```bash
git add src/nl2sql/eval/run.py tests/test_eval_run.py
git commit -m "feat: eval runner entrypoint + CI gate (C-EVAL)"
```

---

## Done criteria
- `py -3 -m pytest -v` green (core + P4a + P4b + P5).
- `run_eval_from_config("config", out_dir)` writes `eval_report.md` + `eval_report.json` and the golden set scores `match_rate == 1.0`.
- The report shows match rate, actual-pass count, and RCA-layer distribution; `gate()` gives CI a single boolean to enforce.

## Follow-on (next plan)
- **P6** (C-ADPT-API): Anthropic API agent adapter reusing the P4b dispatch with a live `model_client`. Recording fresh golden responses from that live model (to expand the golden set) is a manual step layered on top.

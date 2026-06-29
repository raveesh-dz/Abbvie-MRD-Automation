# NL → SQL Semantic Compiler — Core Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic core that turns a validated Query Intent IR into a verified Snowflake SQL string, with every stage's input/output written as readable artifacts.

**Architecture:** Pure-Python library (L1 in the spec's three-layer model). A pydantic IR feeds a deterministic compiler (string-builder + `sqlglot` for dialect-safe parsing) that emits parameterized Snowflake SQL; four verifiers gate it; an observability layer writes a per-run folder. The one LLM-using verifier (V3) calls through a `model_client` seam (L2) so it stays portable and is mockable in tests. No LLM is required to run or test this library.

**Tech Stack:** Python 3.14 (`py -3` on this machine), `pydantic>=2`, `pyyaml`, `sqlglot>=25`, `pytest`.

**Scope:** This plan implements spec sections covering components **C-IR, C-SM, C-MR, C-GP, C-CAT, C-CMP, C-V1, C-V2, C-V3, C-V4, C-MC, C-TOOL, C-OBS, C-CHTR** (spec roadmap **P1–P3**). Explicitly **out of scope** (follow-on plans): C-RES (NL→IR Resolve), C-RCA (RCA engine), C-REP (repair loop), C-ADPT-CC/API (orchestration adapters), C-EVAL (eval harness). **Deliberate deviation from the spec roadmap:** C-IDX (retrieval index) is listed under spec-P1 but is deferred here — it only has value once Resolve (P4) consumes it, so it ships with the Resolve follow-on. The deliverable: feed a hand-written IR → get verified SQL + a complete run folder, or a structured rejection.

**Spec reference:** `docs/superpowers/specs/2026-06-18-nl-to-sql-semantic-compiler-design.md`. Built in a SEPARATE repo (this repo is reference-only); all paths below are relative to the new project root.

## Global Constraints

Every task's requirements implicitly include these (verbatim from the spec):
- Run Python with `py -3` (the bare `python` is a broken Windows Store alias on the dev machine).
- Target dialect is **Snowflake**; `sqlglot` reads/writes with `dialect="snowflake"`.
- Generated SQL is **read-only**: `SELECT` only, never DML/DDL.
- **No `SELECT *`** — explicit column lists only.
- **Filter values are parameterized**, never concatenated into SQL text (Snowflake `pyformat` binds: `%(name)s`). The compiler returns `(sql, params)` with values held separately.
- **Patient-grain output is banned** — the guardrail rejects any grain listed in `banned_grains`.
- The compiler is **deterministic**: same IR + same semantic-model version → byte-identical SQL.
- **Joins only on declared edges** — SQL joining an undeclared table is rejected.
- Run artifacts are human-readable JSON / SQL / plain text. `run_id` = `run_<YYYY-MM-DD>_<NNN>`.
- Every change to semantic model / macros / guardrail policy is its own commit.

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/nl2sql/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`
- Create: `pytest.ini`

**Interfaces:**
- Consumes: nothing.
- Produces: importable package `nl2sql` (`nl2sql.__version__: str`); a working `py -3 -m pytest` command.

- [ ] **Step 1: Write the failing test**

`tests/test_smoke.py`:
```python
import nl2sql


def test_package_imports_and_has_version():
    assert isinstance(nl2sql.__version__, str)
    assert nl2sql.__version__ != ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql'`.

- [ ] **Step 3: Write minimal implementation**

`pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "nl2sql"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["pydantic>=2", "pyyaml>=6", "sqlglot>=25"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[tool.setuptools.packages.find]
where = ["src"]
```

`pytest.ini`:
```ini
[pytest]
pythonpath = src
testpaths = tests
```

`src/nl2sql/__init__.py`:
```python
__version__ = "0.1.0"
```

`tests/__init__.py`: (empty file)

- [ ] **Step 4: Install deps and run test to verify it passes**

Run: `py -3 -m pip install -e ".[dev]"` then `py -3 -m pytest tests/test_smoke.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml pytest.ini src/nl2sql/__init__.py tests/__init__.py tests/test_smoke.py
git commit -m "chore: project scaffold for nl2sql core"
```

---

### Task 2: Query Intent IR schema (C-IR)

**Files:**
- Create: `src/nl2sql/ir.py`
- Test: `tests/test_ir.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class Filter(BaseModel)`: `ref: str`, `value: str | int | float | None = None`
  - `class TimeSpec(BaseModel)`: `grain: str`, `window: dict`
  - `class Assumption(BaseModel)`: `text: str`, `status: str`
  - `class QueryIntent(BaseModel)`: `ir_version: str`, `question: str`, `metrics: list[str]`, `dimensions: list[str]`, `filters: list[Filter] = []`, `time: TimeSpec | None = None`, `macros: list[str] = []`, `grain: str`, `top_n: int | None = None`, `assumptions: list[Assumption] = []`
  - `QueryIntent.from_json(text: str) -> QueryIntent` (raises `pydantic.ValidationError` on bad input)

- [ ] **Step 1: Write the failing test**

`tests/test_ir.py`:
```python
import pytest
from pydantic import ValidationError
from nl2sql.ir import QueryIntent, Filter

VALID = """
{
  "ir_version": "1.0",
  "question": "weekly tremfya trx split by indication for IBD",
  "metrics": ["trx_adjusted"],
  "dimensions": ["indication", "week_ending"],
  "filters": [{"ref": "filter.ibd_market"},
              {"ref": "filter.product", "value": "TREMFYA"}],
  "time": {"grain": "week", "window": {"name": "R13W_default"}},
  "macros": [],
  "grain": "indication x week",
  "top_n": null,
  "assumptions": [{"text": "IBD = {UC, CD}", "status": "default_applied"}]
}
"""


def test_parses_valid_ir():
    ir = QueryIntent.from_json(VALID)
    assert ir.metrics == ["trx_adjusted"]
    assert ir.filters[1] == Filter(ref="filter.product", value="TREMFYA")
    assert ir.grain == "indication x week"


def test_missing_required_field_raises():
    with pytest.raises(ValidationError):
        QueryIntent.from_json('{"ir_version": "1.0"}')


def test_unknown_field_rejected():
    bad = '{"ir_version":"1.0","question":"q","metrics":[],"dimensions":[],"grain":"g","surprise":1}'
    with pytest.raises(ValidationError):
        QueryIntent.from_json(bad)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_ir.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.ir'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/ir.py`:
```python
from __future__ import annotations
from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Filter(_Strict):
    ref: str
    value: str | int | float | None = None


class TimeSpec(_Strict):
    grain: str
    window: dict


class Assumption(_Strict):
    text: str
    status: str


class QueryIntent(_Strict):
    ir_version: str
    question: str
    metrics: list[str]
    dimensions: list[str]
    filters: list[Filter] = []
    time: TimeSpec | None = None
    macros: list[str] = []
    grain: str
    top_n: int | None = None
    assumptions: list[Assumption] = []

    @classmethod
    def from_json(cls, text: str) -> "QueryIntent":
        return cls.model_validate_json(text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_ir.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/ir.py tests/test_ir.py
git commit -m "feat: query intent IR schema (C-IR)"
```

---

### Task 3: Semantic model loader (C-SM)

**Files:**
- Create: `src/nl2sql/semantic/__init__.py`
- Create: `src/nl2sql/semantic/model.py`
- Test: `tests/test_semantic_model.py`
- Test fixture: `tests/fixtures/semantic_model.yaml`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class MetricDef(BaseModel)`: `label: str`, `description: str = ""`, `sql: str`, `grain_floor: str`
  - `class DimensionDef(BaseModel)`: `column: str`, `type: str`, `grain: str | None = None`
  - `class FilterDef(BaseModel)`: `expr: str` (a `{value}` token marks a parameterized filter)
  - `class JoinDef(BaseModel)`: `type: str`, `left_table: str`, `right_table: str`, `on: str`
  - `class SemanticModel(BaseModel)`: `version: str`, `base_table: str`, `metrics: dict[str, MetricDef]`, `dimensions: dict[str, DimensionDef]`, `filters: dict[str, FilterDef]`, `joins: dict[str, JoinDef] = {}`
  - `SemanticModel.load(path: str) -> SemanticModel`
  - `FilterDef.is_parameterized -> bool` (True iff `"{value}"` in `expr`)

- [ ] **Step 1: Write the failing test**

`tests/fixtures/semantic_model.yaml`:
```yaml
version: "2026-06-18.1"
base_table: WEEKLY
metrics:
  trx_adjusted:
    label: "Adjusted TRx"
    description: "Adjusted volume, not script count."
    sql: "SUM({table}.TRX_ADJUSTED)"
    grain_floor: product
dimensions:
  indication: { column: INDICATION, type: string }
  week_ending: { column: WEEK_ENDING, type: date, grain: week }
filters:
  ibd_market: { expr: "INDICATION IN ('UC','CD')" }
  product: { expr: "PRODUCT = {value}" }
joins:
  weekly_to_monthly:
    type: left
    left_table: WEEKLY
    right_table: MONTHLY
    on: "WEEKLY.PRODUCT = MONTHLY.PRODUCT"
```

`tests/test_semantic_model.py`:
```python
from nl2sql.semantic.model import SemanticModel

PATH = "tests/fixtures/semantic_model.yaml"


def test_loads_model():
    m = SemanticModel.load(PATH)
    assert m.version == "2026-06-18.1"
    assert m.base_table == "WEEKLY"
    assert m.metrics["trx_adjusted"].grain_floor == "product"
    assert m.dimensions["week_ending"].column == "WEEK_ENDING"


def test_parameterized_filter_detection():
    m = SemanticModel.load(PATH)
    assert m.filters["product"].is_parameterized is True
    assert m.filters["ibd_market"].is_parameterized is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_semantic_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.semantic'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/semantic/__init__.py`: (empty file)

`src/nl2sql/semantic/model.py`:
```python
from __future__ import annotations
import yaml
from pydantic import BaseModel


class MetricDef(BaseModel):
    label: str
    description: str = ""
    sql: str
    grain_floor: str


class DimensionDef(BaseModel):
    column: str
    type: str
    grain: str | None = None


class FilterDef(BaseModel):
    expr: str

    @property
    def is_parameterized(self) -> bool:
        return "{value}" in self.expr


class JoinDef(BaseModel):
    type: str
    left_table: str
    right_table: str
    on: str


class SemanticModel(BaseModel):
    version: str
    base_table: str
    metrics: dict[str, MetricDef]
    dimensions: dict[str, DimensionDef]
    filters: dict[str, FilterDef]
    joins: dict[str, JoinDef] = {}

    @classmethod
    def load(cls, path: str) -> "SemanticModel":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.model_validate(yaml.safe_load(fh))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_semantic_model.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/semantic/ tests/test_semantic_model.py tests/fixtures/semantic_model.yaml
git commit -m "feat: semantic model loader (C-SM)"
```

---

### Task 4: Macro registry loader (C-MR)

**Files:**
- Create: `src/nl2sql/semantic/macros.py`
- Test: `tests/test_macros.py`
- Test fixture: `tests/fixtures/macros.yaml`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class MacroDef(BaseModel)`: `id: str`, `description: str = ""`, `params: list[str] = []`, `sql_template: str`, `tests: list[str] = []`
  - `class MacroRegistry(BaseModel)`: `macros: dict[str, MacroDef]`
  - `MacroRegistry.load(path: str) -> MacroRegistry`
  - `MacroRegistry.get(macro_id: str) -> MacroDef` (raises `KeyError` if missing)

Note: macro *inlining into compiled SQL* (procedural allocation needing the weekly→monthly join) is a follow-on; this task delivers the registry + lookup, which the compiler records in provenance.

- [ ] **Step 1: Write the failing test**

`tests/fixtures/macros.yaml`:
```yaml
macros:
  macro.indication_allocation:
    id: macro.indication_allocation
    description: "Renormalize-within-reported-set allocation."
    params: [reported_set]
    sql_template: |
      -- vetted CTE; full body lives here, proven by the linked test
    tests: [tests/macros/indication_allocation_test.sql]
```

`tests/test_macros.py`:
```python
import pytest
from nl2sql.semantic.macros import MacroRegistry

PATH = "tests/fixtures/macros.yaml"


def test_loads_and_gets_macro():
    reg = MacroRegistry.load(PATH)
    m = reg.get("macro.indication_allocation")
    assert m.params == ["reported_set"]
    assert "renormalize" in m.description.lower()


def test_missing_macro_raises():
    reg = MacroRegistry.load(PATH)
    with pytest.raises(KeyError):
        reg.get("macro.nope")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_macros.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.semantic.macros'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/semantic/macros.py`:
```python
from __future__ import annotations
import yaml
from pydantic import BaseModel


class MacroDef(BaseModel):
    id: str
    description: str = ""
    params: list[str] = []
    sql_template: str
    tests: list[str] = []


class MacroRegistry(BaseModel):
    macros: dict[str, MacroDef]

    @classmethod
    def load(cls, path: str) -> "MacroRegistry":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.model_validate(yaml.safe_load(fh))

    def get(self, macro_id: str) -> MacroDef:
        if macro_id not in self.macros:
            raise KeyError(f"macro not found: {macro_id}")
        return self.macros[macro_id]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_macros.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/semantic/macros.py tests/test_macros.py tests/fixtures/macros.yaml
git commit -m "feat: macro registry loader (C-MR)"
```

---

### Task 5: Guardrail policy (C-GP)

**Files:**
- Create: `src/nl2sql/guardrails/__init__.py`
- Create: `src/nl2sql/guardrails/policy.py`
- Test: `tests/test_policy.py`
- Test fixture: `tests/fixtures/guardrails.yaml`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class GuardrailPolicy(BaseModel)`: `row_limit: int`, `max_scanned_bytes: int`, `statement_timeout_s: int`, `cost_ceiling: float`, `banned_grains: list[str]`, `allowed_join_tables: list[str]`, `forbid_select_star: bool = True`, `read_only: bool = True`
  - `GuardrailPolicy.load(path: str) -> GuardrailPolicy`

- [ ] **Step 1: Write the failing test**

`tests/fixtures/guardrails.yaml`:
```yaml
row_limit: 2000
max_scanned_bytes: 1000000000
statement_timeout_s: 60
cost_ceiling: 5.0
banned_grains: [patient, patient x week]
allowed_join_tables: [MONTHLY]
forbid_select_star: true
read_only: true
```

`tests/test_policy.py`:
```python
from nl2sql.guardrails.policy import GuardrailPolicy

PATH = "tests/fixtures/guardrails.yaml"


def test_loads_policy():
    p = GuardrailPolicy.load(PATH)
    assert p.row_limit == 2000
    assert "patient" in p.banned_grains
    assert p.allowed_join_tables == ["MONTHLY"]
    assert p.forbid_select_star is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_policy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.guardrails'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/guardrails/__init__.py`: (empty file)

`src/nl2sql/guardrails/policy.py`:
```python
from __future__ import annotations
import yaml
from pydantic import BaseModel


class GuardrailPolicy(BaseModel):
    row_limit: int
    max_scanned_bytes: int
    statement_timeout_s: int
    cost_ceiling: float
    banned_grains: list[str]
    allowed_join_tables: list[str]
    forbid_select_star: bool = True
    read_only: bool = True

    @classmethod
    def load(cls, path: str) -> "GuardrailPolicy":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.model_validate(yaml.safe_load(fh))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_policy.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/guardrails/ tests/test_policy.py tests/fixtures/guardrails.yaml
git commit -m "feat: guardrail policy loader (C-GP)"
```

---

### Task 6: Physical schema catalog (C-CAT)

**Files:**
- Create: `src/nl2sql/catalog/__init__.py`
- Create: `src/nl2sql/catalog/catalog.py`
- Test: `tests/test_catalog.py`
- Test fixture: `tests/fixtures/catalog.yaml`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class Catalog(BaseModel)`: `tables: dict[str, list[str]]` (table → column names, all UPPERCASE)
  - `Catalog.load(path: str) -> Catalog`
  - `Catalog.has_table(name: str) -> bool`
  - `Catalog.has_column(table: str, column: str) -> bool`
  - `Catalog.column_in_any(column: str) -> bool` (column exists in at least one table)

Note: live Snowflake `EXPLAIN` dry-run is a follow-on; v1 validates against this static catalog snapshot.

- [ ] **Step 1: Write the failing test**

`tests/fixtures/catalog.yaml`:
```yaml
tables:
  WEEKLY: [PRODUCT, INDICATION, WEEK_ENDING, TRX_ADJUSTED]
  MONTHLY: [PRODUCT, INDICATION, MONTH, TRX_VOLUME]
```

`tests/test_catalog.py`:
```python
from nl2sql.catalog.catalog import Catalog

PATH = "tests/fixtures/catalog.yaml"


def test_table_and_column_lookups():
    c = Catalog.load(PATH)
    assert c.has_table("WEEKLY")
    assert not c.has_table("NOPE")
    assert c.has_column("WEEKLY", "TRX_ADJUSTED")
    assert not c.has_column("WEEKLY", "MONTH")
    assert c.column_in_any("INDICATION")
    assert not c.column_in_any("MADE_UP")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.catalog'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/catalog/__init__.py`: (empty file)

`src/nl2sql/catalog/catalog.py`:
```python
from __future__ import annotations
import yaml
from pydantic import BaseModel


class Catalog(BaseModel):
    tables: dict[str, list[str]]

    @classmethod
    def load(cls, path: str) -> "Catalog":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.model_validate(yaml.safe_load(fh))

    def has_table(self, name: str) -> bool:
        return name.upper() in self.tables

    def has_column(self, table: str, column: str) -> bool:
        return column.upper() in self.tables.get(table.upper(), [])

    def column_in_any(self, column: str) -> bool:
        col = column.upper()
        return any(col in cols for cols in self.tables.values())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_catalog.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/catalog/ tests/test_catalog.py tests/fixtures/catalog.yaml
git commit -m "feat: physical schema catalog (C-CAT)"
```

---

### Task 7: Dialect helpers + bind handling (#5)

**Files:**
- Create: `src/nl2sql/compiler/__init__.py`
- Create: `src/nl2sql/compiler/dialect.py`
- Test: `tests/test_dialect.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `DIALECT = "snowflake"` (str constant)
  - `bind(name: str) -> str` → `"%(name)s"` (Snowflake pyformat)
  - `BIND_RE` (compiled regex matching `%(name)s`, capturing `name`)
  - `strip_binds(sql: str) -> str` → replaces every `%(...)s` with the literal `'__BIND__'` so `sqlglot` can parse the statement for AST checks
  - `quote_ident(name: str) -> str` → wraps in double quotes only if not already a bare uppercase identifier

- [ ] **Step 1: Write the failing test**

`tests/test_dialect.py`:
```python
import sqlglot
from nl2sql.compiler.dialect import bind, BIND_RE, strip_binds, quote_ident, DIALECT


def test_bind_format():
    assert bind("p0") == "%(p0)s"


def test_bind_re_captures_names():
    assert BIND_RE.findall("a = %(p0)s AND b = %(p1)s") == ["p0", "p1"]


def test_strip_binds_makes_parseable_sql():
    sql = "SELECT X FROM T WHERE PRODUCT = %(p0)s"
    stripped = strip_binds(sql)
    assert "%(p0)s" not in stripped
    sqlglot.parse_one(stripped, dialect=DIALECT)  # must not raise


def test_quote_ident():
    assert quote_ident("PRODUCT") == "PRODUCT"
    assert quote_ident("weird col") == '"weird col"'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_dialect.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.compiler'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/compiler/__init__.py`: (empty file)

`src/nl2sql/compiler/dialect.py`:
```python
from __future__ import annotations
import re

DIALECT = "snowflake"
BIND_RE = re.compile(r"%\((\w+)\)s")
_BARE_IDENT = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def bind(name: str) -> str:
    return f"%({name})s"


def strip_binds(sql: str) -> str:
    return BIND_RE.sub("'__BIND__'", sql)


def quote_ident(name: str) -> str:
    return name if _BARE_IDENT.match(name) else '"' + name.replace('"', '""') + '"'
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_dialect.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/compiler/__init__.py src/nl2sql/compiler/dialect.py tests/test_dialect.py
git commit -m "feat: snowflake dialect + bind helpers (#5)"
```

---

### Task 8: Deterministic compiler IR → SQL (C-CMP)

**Files:**
- Create: `src/nl2sql/compiler/compile.py`
- Test: `tests/test_compile.py`

**Interfaces:**
- Consumes: `QueryIntent` (Task 2), `SemanticModel`/`FilterDef` (Task 3), `MacroRegistry` (Task 4), `GuardrailPolicy` (Task 5), `bind`/`quote_ident` (Task 7).
- Produces:
  - `class CompileResult(BaseModel)`: `sql: str`, `params: dict[str, str | int | float]`, `provenance: dict`
  - `class CompileError(Exception)` — raised when the IR references an unknown metric/dimension/filter (a Resolve bug, surfaced not guessed)
  - `compile_ir(ir: QueryIntent, model: SemanticModel, macros: MacroRegistry, policy: GuardrailPolicy) -> CompileResult`

Behavior (single base table; declared-join compilation is a follow-on — see note):
- SELECT = dimension columns (in IR order) + metric expressions (`MetricDef.sql` with `{table}` → `base_table`), each metric aliased to its IR key.
- FROM = `model.base_table`.
- WHERE = AND of: every static filter expr; every parameterized filter with its value bound (`{value}` → `bind("pN")`, value recorded in `params`).
- GROUP BY = dimension columns. ORDER BY = dimension columns (deterministic).
- LIMIT = `policy.row_limit` (always present).
- `provenance` = `{"metrics": [...], "dimensions": [...], "filters": [...], "macros": ir.macros, "semantic_model_version": model.version}`.
- Determinism: filters bound in IR order → `p0, p1, ...` stable.

Note: if any `ir.macros` entry is unknown to the registry, raise `CompileError` (fail fast). Macro SQL inlining itself is deferred; provenance records the referenced ids.

- [ ] **Step 1: Write the failing test**

`tests/test_compile.py`:
```python
import pytest
from nl2sql.ir import QueryIntent, Filter
from nl2sql.semantic.model import SemanticModel
from nl2sql.semantic.macros import MacroRegistry
from nl2sql.guardrails.policy import GuardrailPolicy
from nl2sql.compiler.compile import compile_ir, CompileError

MODEL = SemanticModel.load("tests/fixtures/semantic_model.yaml")
MACROS = MacroRegistry.load("tests/fixtures/macros.yaml")
POLICY = GuardrailPolicy.load("tests/fixtures/guardrails.yaml")


def _ir(**over):
    base = dict(
        ir_version="1.0", question="q",
        metrics=["trx_adjusted"], dimensions=["indication", "week_ending"],
        filters=[Filter(ref="filter.ibd_market"),
                 Filter(ref="filter.product", value="TREMFYA")],
        grain="indication x week", macros=[],
    )
    base.update(over)
    return QueryIntent(**base)


def test_compiles_expected_sql_and_params():
    r = compile_ir(_ir(), MODEL, MACROS, POLICY)
    assert "SELECT" in r.sql
    assert "INDICATION" in r.sql and "WEEK_ENDING" in r.sql
    assert "SUM(WEEKLY.TRX_ADJUSTED) AS trx_adjusted" in r.sql
    assert "FROM WEEKLY" in r.sql
    assert "INDICATION IN ('UC','CD')" in r.sql
    assert "PRODUCT = %(p0)s" in r.sql
    assert "GROUP BY INDICATION, WEEK_ENDING" in r.sql
    assert "ORDER BY INDICATION, WEEK_ENDING" in r.sql
    assert "LIMIT 2000" in r.sql
    assert r.params == {"p0": "TREMFYA"}


def test_is_deterministic():
    a = compile_ir(_ir(), MODEL, MACROS, POLICY)
    b = compile_ir(_ir(), MODEL, MACROS, POLICY)
    assert a.sql == b.sql and a.params == b.params


def test_unknown_metric_raises():
    with pytest.raises(CompileError):
        compile_ir(_ir(metrics=["nope"]), MODEL, MACROS, POLICY)


def test_unknown_macro_raises():
    with pytest.raises(CompileError):
        compile_ir(_ir(macros=["macro.nope"]), MODEL, MACROS, POLICY)


def test_provenance_records_version_and_refs():
    r = compile_ir(_ir(), MODEL, MACROS, POLICY)
    assert r.provenance["semantic_model_version"] == MODEL.version
    assert r.provenance["metrics"] == ["trx_adjusted"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_compile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.compiler.compile'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/compiler/compile.py`:
```python
from __future__ import annotations
from pydantic import BaseModel
from nl2sql.ir import QueryIntent
from nl2sql.semantic.model import SemanticModel
from nl2sql.semantic.macros import MacroRegistry
from nl2sql.guardrails.policy import GuardrailPolicy
from nl2sql.compiler.dialect import bind


class CompileError(Exception):
    pass


class CompileResult(BaseModel):
    sql: str
    params: dict[str, str | int | float]
    provenance: dict


def compile_ir(ir: QueryIntent, model: SemanticModel,
               macros: MacroRegistry, policy: GuardrailPolicy) -> CompileResult:
    # Validate macro references fail-fast (unknown macro -> CompileError).
    for mid in ir.macros:
        try:
            macros.get(mid)
        except KeyError as e:
            raise CompileError(str(e)) from e

    select_cols: list[str] = []
    for dim in ir.dimensions:
        d = model.dimensions.get(dim)
        if d is None:
            raise CompileError(f"unknown dimension: {dim}")
        select_cols.append(d.column)

    for met in ir.metrics:
        m = model.metrics.get(met)
        if m is None:
            raise CompileError(f"unknown metric: {met}")
        select_cols.append(f"{m.sql.format(table=model.base_table)} AS {met}")

    where_parts: list[str] = []
    params: dict[str, str | int | float] = {}
    pidx = 0
    for f in ir.filters:
        key = f.ref.split(".", 1)[-1]
        fdef = model.filters.get(key)
        if fdef is None:
            raise CompileError(f"unknown filter: {f.ref}")
        if fdef.is_parameterized:
            pname = f"p{pidx}"
            pidx += 1
            where_parts.append(fdef.expr.format(value=bind(pname)))
            params[pname] = f.value
        else:
            where_parts.append(fdef.expr)

    dim_cols = [model.dimensions[d].column for d in ir.dimensions]
    sql_lines = [
        "SELECT " + ", ".join(select_cols),
        f"FROM {model.base_table}",
    ]
    if where_parts:
        sql_lines.append("WHERE " + " AND ".join(where_parts))
    if dim_cols:
        sql_lines.append("GROUP BY " + ", ".join(dim_cols))
        sql_lines.append("ORDER BY " + ", ".join(dim_cols))
    sql_lines.append(f"LIMIT {policy.row_limit}")
    sql = "\n".join(sql_lines)

    provenance = {
        "metrics": list(ir.metrics),
        "dimensions": list(ir.dimensions),
        "filters": [f.ref for f in ir.filters],
        "macros": list(ir.macros),
        "semantic_model_version": model.version,
    }
    return CompileResult(sql=sql, params=params, provenance=provenance)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_compile.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/compiler/compile.py tests/test_compile.py
git commit -m "feat: deterministic IR->SQL compiler (C-CMP)"
```

---

### Task 9: Verifier types + V1 static safety (C-V1)

**Files:**
- Create: `src/nl2sql/verify/__init__.py`
- Create: `src/nl2sql/verify/types.py`
- Create: `src/nl2sql/verify/v1_static.py`
- Test: `tests/test_v1_static.py`

**Interfaces:**
- Consumes: `QueryIntent` (Task 2), `GuardrailPolicy` (Task 5), `strip_binds`/`DIALECT`/`BIND_RE` (Task 7).
- Produces:
  - `class Finding(BaseModel)`: `check: str`, `passed: bool`, `message: str = ""`
  - `class VerifyResult(BaseModel)`: `verifier: str`, `passed: bool`, `status: str = "ran"`, `findings: list[Finding] = []`
  - `verify_static(sql: str, params: dict, ir: QueryIntent, policy: GuardrailPolicy) -> VerifyResult` (`verifier="V1"`)

Checks: `read_only` (parsed root is a SELECT, no Insert/Update/Delete/Create/Drop/Merge anywhere), `no_select_star` (no top-level `Star` projection), `allowed_joins` (every joined table ∈ `policy.allowed_join_tables`), `has_limit`, `grain_not_banned` (`ir.grain` ∉ `policy.banned_grains`), `values_parameterized` (count of `%(...)s` == count of IR filters carrying a value; and no IR value string appears as a literal in `sql`).

- [ ] **Step 1: Write the failing test**

`tests/test_v1_static.py`:
```python
from nl2sql.ir import QueryIntent, Filter
from nl2sql.guardrails.policy import GuardrailPolicy
from nl2sql.verify.v1_static import verify_static

POLICY = GuardrailPolicy.load("tests/fixtures/guardrails.yaml")


def _ir(grain="indication x week"):
    return QueryIntent(ir_version="1.0", question="q", metrics=["m"],
                       dimensions=["indication"],
                       filters=[Filter(ref="filter.product", value="TREMFYA")],
                       grain=grain)


GOOD = ("SELECT INDICATION, SUM(WEEKLY.TRX_ADJUSTED) AS m\n"
        "FROM WEEKLY\nWHERE PRODUCT = %(p0)s\n"
        "GROUP BY INDICATION\nORDER BY INDICATION\nLIMIT 2000")


def test_good_sql_passes():
    r = verify_static(GOOD, {"p0": "TREMFYA"}, _ir(), POLICY)
    assert r.verifier == "V1" and r.passed is True


def test_select_star_fails():
    sql = "SELECT * FROM WEEKLY LIMIT 2000"
    r = verify_static(sql, {}, _ir(), POLICY)
    assert r.passed is False
    assert any(f.check == "no_select_star" and not f.passed for f in r.findings)


def test_dml_fails():
    r = verify_static("DELETE FROM WEEKLY", {}, _ir(), POLICY)
    assert r.passed is False
    assert any(f.check == "read_only" and not f.passed for f in r.findings)


def test_missing_limit_fails():
    sql = "SELECT INDICATION FROM WEEKLY GROUP BY INDICATION"
    r = verify_static(sql, {}, _ir(), POLICY)
    assert any(f.check == "has_limit" and not f.passed for f in r.findings)


def test_undeclared_join_fails():
    sql = ("SELECT INDICATION FROM WEEKLY "
           "JOIN SECRET ON WEEKLY.PRODUCT = SECRET.PRODUCT LIMIT 2000")
    r = verify_static(sql, {}, _ir(), POLICY)
    assert any(f.check == "allowed_joins" and not f.passed for f in r.findings)


def test_banned_grain_fails():
    r = verify_static(GOOD, {"p0": "TREMFYA"}, _ir(grain="patient"), POLICY)
    assert any(f.check == "grain_not_banned" and not f.passed for f in r.findings)


def test_inlined_value_fails_parameterization():
    sql = ("SELECT INDICATION FROM WEEKLY WHERE PRODUCT = 'TREMFYA' "
           "GROUP BY INDICATION LIMIT 2000")
    r = verify_static(sql, {}, _ir(), POLICY)
    assert any(f.check == "values_parameterized" and not f.passed for f in r.findings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_v1_static.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.verify'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/verify/__init__.py`: (empty file)

`src/nl2sql/verify/types.py`:
```python
from __future__ import annotations
from pydantic import BaseModel


class Finding(BaseModel):
    check: str
    passed: bool
    message: str = ""


class VerifyResult(BaseModel):
    verifier: str
    passed: bool
    status: str = "ran"
    findings: list[Finding] = []
```

`src/nl2sql/verify/v1_static.py`:
```python
from __future__ import annotations
import sqlglot
from sqlglot import exp
from nl2sql.ir import QueryIntent
from nl2sql.guardrails.policy import GuardrailPolicy
from nl2sql.compiler.dialect import DIALECT, BIND_RE, strip_binds
from nl2sql.verify.types import Finding, VerifyResult

_FORBIDDEN = (exp.Insert, exp.Update, exp.Delete, exp.Create,
              exp.Drop, exp.Merge, exp.Alter)


def verify_static(sql: str, params: dict, ir: QueryIntent,
                  policy: GuardrailPolicy) -> VerifyResult:
    findings: list[Finding] = []
    try:
        tree = sqlglot.parse_one(strip_binds(sql), dialect=DIALECT)
    except Exception as e:  # unparseable
        return VerifyResult(verifier="V1", passed=False,
                            findings=[Finding(check="parseable", passed=False,
                                              message=str(e))])

    # read_only
    is_select = isinstance(tree, (exp.Select, exp.Query))
    has_forbidden = any(tree.find_all(*_FORBIDDEN))
    ro_ok = is_select and not has_forbidden
    findings.append(Finding(check="read_only", passed=ro_ok,
                            message="" if ro_ok else "non-SELECT statement"))

    # no_select_star
    star_ok = True
    if policy.forbid_select_star and isinstance(tree, exp.Select):
        star_ok = not any(isinstance(p, exp.Star) for p in tree.expressions)
    findings.append(Finding(check="no_select_star", passed=star_ok,
                            message="" if star_ok else "SELECT * not allowed"))

    # allowed_joins
    joined = []
    for j in tree.find_all(exp.Join):
        t = j.find(exp.Table)
        if t is not None:
            joined.append(t.name.upper())
    bad_join = [t for t in joined if t not in
                {x.upper() for x in policy.allowed_join_tables}]
    findings.append(Finding(check="allowed_joins", passed=not bad_join,
                            message="" if not bad_join else f"undeclared: {bad_join}"))

    # has_limit
    limit_ok = tree.args.get("limit") is not None
    findings.append(Finding(check="has_limit", passed=limit_ok,
                            message="" if limit_ok else "no LIMIT cap"))

    # grain_not_banned
    grain_ok = ir.grain not in policy.banned_grains
    findings.append(Finding(check="grain_not_banned", passed=grain_ok,
                            message="" if grain_ok else f"banned grain: {ir.grain}"))

    # values_parameterized
    n_binds = len(BIND_RE.findall(sql))
    n_vals = sum(1 for f in ir.filters if f.value is not None)
    inlined = [str(f.value) for f in ir.filters
               if f.value is not None and f"'{f.value}'" in sql]
    pv_ok = (n_binds == n_vals) and not inlined
    findings.append(Finding(check="values_parameterized", passed=pv_ok,
                            message="" if pv_ok else "values must be bound, not inlined"))

    return VerifyResult(verifier="V1", passed=all(f.passed for f in findings),
                        findings=findings)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_v1_static.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/verify/__init__.py src/nl2sql/verify/types.py src/nl2sql/verify/v1_static.py tests/test_v1_static.py
git commit -m "feat: V1 static SQL safety verifier (C-V1)"
```

---

### Task 10: V2 schema/dialect verifier (C-V2)

**Files:**
- Create: `src/nl2sql/verify/v2_schema.py`
- Test: `tests/test_v2_schema.py`

**Interfaces:**
- Consumes: `Catalog` (Task 6), `Finding`/`VerifyResult` (Task 9), `strip_binds`/`DIALECT` (Task 7).
- Produces: `verify_schema(sql: str, catalog: Catalog) -> VerifyResult` (`verifier="V2"`)

Checks: every `Table` in the parsed SQL exists in the catalog; every `Column` exists in some catalogued table (qualified column → that table; bare column → `column_in_any`). Live Snowflake `EXPLAIN` dry-run is a follow-on (noted in the spec §6).

- [ ] **Step 1: Write the failing test**

`tests/test_v2_schema.py`:
```python
from nl2sql.catalog.catalog import Catalog
from nl2sql.verify.v2_schema import verify_schema

CAT = Catalog.load("tests/fixtures/catalog.yaml")

GOOD = ("SELECT INDICATION, SUM(WEEKLY.TRX_ADJUSTED) AS m\n"
        "FROM WEEKLY WHERE PRODUCT = %(p0)s GROUP BY INDICATION LIMIT 2000")


def test_known_schema_passes():
    r = verify_schema(GOOD, CAT)
    assert r.verifier == "V2" and r.passed is True


def test_unknown_table_fails():
    sql = "SELECT X FROM GHOST LIMIT 10"
    r = verify_schema(sql, CAT)
    assert r.passed is False
    assert any(f.check == "tables_exist" and not f.passed for f in r.findings)


def test_unknown_column_fails():
    sql = "SELECT MADE_UP FROM WEEKLY LIMIT 10"
    r = verify_schema(sql, CAT)
    assert r.passed is False
    assert any(f.check == "columns_exist" and not f.passed for f in r.findings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_v2_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.verify.v2_schema'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/verify/v2_schema.py`:
```python
from __future__ import annotations
import sqlglot
from sqlglot import exp
from nl2sql.catalog.catalog import Catalog
from nl2sql.compiler.dialect import DIALECT, strip_binds
from nl2sql.verify.types import Finding, VerifyResult


def verify_schema(sql: str, catalog: Catalog) -> VerifyResult:
    findings: list[Finding] = []
    try:
        tree = sqlglot.parse_one(strip_binds(sql), dialect=DIALECT)
    except Exception as e:
        return VerifyResult(verifier="V2", passed=False,
                            findings=[Finding(check="parseable", passed=False,
                                              message=str(e))])

    bad_tables = [t.name.upper() for t in tree.find_all(exp.Table)
                  if not catalog.has_table(t.name)]
    findings.append(Finding(check="tables_exist", passed=not bad_tables,
                            message="" if not bad_tables else f"unknown: {bad_tables}"))

    bad_cols: list[str] = []
    for c in tree.find_all(exp.Column):
        col = c.name
        tbl = c.table  # qualifier or "" if bare
        if tbl:
            if not catalog.has_column(tbl, col):
                bad_cols.append(f"{tbl}.{col}")
        else:
            if not catalog.column_in_any(col):
                bad_cols.append(col)
    findings.append(Finding(check="columns_exist", passed=not bad_cols,
                            message="" if not bad_cols else f"unknown: {bad_cols}"))

    return VerifyResult(verifier="V2", passed=all(f.passed for f in findings),
                        findings=findings)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_v2_schema.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/verify/v2_schema.py tests/test_v2_schema.py
git commit -m "feat: V2 schema/dialect verifier (C-V2)"
```

---

### Task 11: model_client seam + V3 intent-fidelity judge (C-MC, C-V3)

**Files:**
- Create: `src/nl2sql/toolcontract/__init__.py`
- Create: `src/nl2sql/toolcontract/model_client.py`
- Create: `src/nl2sql/verify/v3_intent.py`
- Test: `tests/test_v3_intent.py`

**Interfaces:**
- Consumes: `QueryIntent` (Task 2), `Finding`/`VerifyResult` (Task 9).
- Produces:
  - `class ModelClient(Protocol)`: `complete(self, system: str, user: str) -> str` (returns raw text; the implementation guarantees JSON)
  - `class FakeModelClient`: constructed with a canned response string; records the last `(system, user)` it received in `.last_call`
  - `verify_intent(sql: str, ir: QueryIntent, client: ModelClient) -> VerifyResult` (`verifier="V3"`). Builds a judge prompt, calls `client.complete`, parses JSON `{"passed": bool, "reasons": [str]}`. On JSON parse failure → `passed=False`, a `judge_parse` finding.

- [ ] **Step 1: Write the failing test**

`tests/test_v3_intent.py`:
```python
from nl2sql.ir import QueryIntent
from nl2sql.toolcontract.model_client import FakeModelClient
from nl2sql.verify.v3_intent import verify_intent

IR = QueryIntent(ir_version="1.0", question="weekly trx by indication",
                 metrics=["trx_adjusted"], dimensions=["indication"],
                 grain="indication")
SQL = "SELECT INDICATION, SUM(WEEKLY.TRX_ADJUSTED) AS trx_adjusted FROM WEEKLY GROUP BY INDICATION LIMIT 2000"


def test_judge_pass():
    client = FakeModelClient('{"passed": true, "reasons": []}')
    r = verify_intent(SQL, IR, client)
    assert r.verifier == "V3" and r.passed is True
    assert "trx_adjusted" in client.last_call[1]  # IR is in the prompt


def test_judge_fail_with_reason():
    client = FakeModelClient('{"passed": false, "reasons": ["wrong metric"]}')
    r = verify_intent(SQL, IR, client)
    assert r.passed is False
    assert any("wrong metric" in f.message for f in r.findings)


def test_judge_non_json_fails_safe():
    client = FakeModelClient("the sql looks fine to me")
    r = verify_intent(SQL, IR, client)
    assert r.passed is False
    assert any(f.check == "judge_parse" for f in r.findings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_v3_intent.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.toolcontract'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/toolcontract/__init__.py`: (empty file)

`src/nl2sql/toolcontract/model_client.py`:
```python
from __future__ import annotations
from typing import Protocol


class ModelClient(Protocol):
    def complete(self, system: str, user: str) -> str:
        ...


class FakeModelClient:
    """Deterministic test double. Returns its canned response, records the call."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.last_call: tuple[str, str] | None = None

    def complete(self, system: str, user: str) -> str:
        self.last_call = (system, user)
        return self._response
```

`src/nl2sql/verify/v3_intent.py`:
```python
from __future__ import annotations
import json
from nl2sql.ir import QueryIntent
from nl2sql.toolcontract.model_client import ModelClient
from nl2sql.verify.types import Finding, VerifyResult

_SYSTEM = (
    "You are a SQL intent auditor. Given a Query Intent (JSON) and a SQL "
    "statement, decide if the SQL faithfully answers the intent: same metrics, "
    "filters, time window, and grain. Reply ONLY with JSON: "
    '{"passed": <bool>, "reasons": [<short strings>]}.'
)


def verify_intent(sql: str, ir: QueryIntent, client: ModelClient) -> VerifyResult:
    user = f"INTENT:\n{ir.model_dump_json(indent=2)}\n\nSQL:\n{sql}"
    raw = client.complete(_SYSTEM, user)
    try:
        verdict = json.loads(raw)
        passed = bool(verdict["passed"])
        reasons = verdict.get("reasons", [])
    except (json.JSONDecodeError, KeyError, TypeError):
        return VerifyResult(verifier="V3", passed=False,
                            findings=[Finding(check="judge_parse", passed=False,
                                              message="judge did not return valid JSON")])
    findings = [Finding(check="intent_fidelity", passed=passed,
                        message="; ".join(str(r) for r in reasons))]
    return VerifyResult(verifier="V3", passed=passed, findings=findings)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_v3_intent.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/toolcontract/ src/nl2sql/verify/v3_intent.py tests/test_v3_intent.py
git commit -m "feat: model_client seam + V3 intent judge (C-MC, C-V3)"
```

---

### Task 12: V4 deferred stub + verify runner

**Files:**
- Create: `src/nl2sql/verify/v4_result.py`
- Create: `src/nl2sql/verify/runner.py`
- Test: `tests/test_verify_runner.py`

**Interfaces:**
- Consumes: `verify_static` (Task 9), `verify_schema` (Task 10), `verify_intent` + `ModelClient` (Task 11), `Catalog` (Task 6), `GuardrailPolicy` (Task 5), `QueryIntent` (Task 2), `VerifyResult` (Task 9).
- Produces:
  - `verify_result_sanity() -> VerifyResult` (`verifier="V4"`, `status="skipped"`, `passed=True`, one `Finding(check="deferred", passed=True, message="V4 deferred in v1")`)
  - `run_verifiers(sql, params, ir, policy, catalog, client) -> list[VerifyResult]` — runs V1, V2, V3, V4 in order, always returns all four.
  - `all_passed(results: list[VerifyResult]) -> bool`

- [ ] **Step 1: Write the failing test**

`tests/test_verify_runner.py`:
```python
from nl2sql.ir import QueryIntent, Filter
from nl2sql.guardrails.policy import GuardrailPolicy
from nl2sql.catalog.catalog import Catalog
from nl2sql.toolcontract.model_client import FakeModelClient
from nl2sql.verify.runner import run_verifiers, all_passed

POLICY = GuardrailPolicy.load("tests/fixtures/guardrails.yaml")
CAT = Catalog.load("tests/fixtures/catalog.yaml")
IR = QueryIntent(ir_version="1.0", question="q", metrics=["trx_adjusted"],
                 dimensions=["indication"],
                 filters=[Filter(ref="filter.product", value="TREMFYA")],
                 grain="indication")
GOOD = ("SELECT INDICATION, SUM(WEEKLY.TRX_ADJUSTED) AS trx_adjusted\n"
        "FROM WEEKLY WHERE PRODUCT = %(p0)s GROUP BY INDICATION ORDER BY INDICATION LIMIT 2000")


def test_runs_all_four_and_v4_skipped():
    client = FakeModelClient('{"passed": true, "reasons": []}')
    results = run_verifiers(GOOD, {"p0": "TREMFYA"}, IR, POLICY, CAT, client)
    assert [r.verifier for r in results] == ["V1", "V2", "V3", "V4"]
    v4 = results[3]
    assert v4.status == "skipped" and v4.passed is True
    assert all_passed(results) is True


def test_all_passed_false_when_one_fails():
    client = FakeModelClient('{"passed": false, "reasons": ["bad"]}')
    results = run_verifiers(GOOD, {"p0": "TREMFYA"}, IR, POLICY, CAT, client)
    assert all_passed(results) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_verify_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.verify.runner'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/verify/v4_result.py`:
```python
from __future__ import annotations
from nl2sql.verify.types import Finding, VerifyResult


def verify_result_sanity() -> VerifyResult:
    return VerifyResult(
        verifier="V4", passed=True, status="skipped",
        findings=[Finding(check="deferred", passed=True,
                          message="V4 deferred in v1")],
    )
```

`src/nl2sql/verify/runner.py`:
```python
from __future__ import annotations
from nl2sql.ir import QueryIntent
from nl2sql.guardrails.policy import GuardrailPolicy
from nl2sql.catalog.catalog import Catalog
from nl2sql.toolcontract.model_client import ModelClient
from nl2sql.verify.types import VerifyResult
from nl2sql.verify.v1_static import verify_static
from nl2sql.verify.v2_schema import verify_schema
from nl2sql.verify.v3_intent import verify_intent
from nl2sql.verify.v4_result import verify_result_sanity


def run_verifiers(sql: str, params: dict, ir: QueryIntent,
                  policy: GuardrailPolicy, catalog: Catalog,
                  client: ModelClient) -> list[VerifyResult]:
    return [
        verify_static(sql, params, ir, policy),
        verify_schema(sql, catalog),
        verify_intent(sql, ir, client),
        verify_result_sanity(),
    ]


def all_passed(results: list[VerifyResult]) -> bool:
    return all(r.passed for r in results)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_verify_runner.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/verify/v4_result.py src/nl2sql/verify/runner.py tests/test_verify_runner.py
git commit -m "feat: V4 deferred stub + verify runner (C-V4)"
```

---

### Task 13: Observability run folder + manifest (C-OBS)

**Files:**
- Create: `src/nl2sql/obs/__init__.py`
- Create: `src/nl2sql/obs/run.py`
- Test: `tests/test_obs.py`

**Interfaces:**
- Consumes: nothing (operates on plain dicts/strings so it stays decoupled).
- Produces:
  - `class RunFolder`: `__init__(self, run_id: str, root: str)` (creates `root/run_id/`); exposes `.dir: str` (the run folder path) and `.run_id: str`
  - `.write_text(name: str, text: str) -> str` (returns full path)
  - `.write_json(name: str, obj) -> str` (json.dumps, indent=2, sorted keys)
  - `.write_sql(name: str, sql: str) -> str`
  - `.write_manifest(manifest: dict) -> str` (writes `run_manifest.json`)
  - `.path(name: str) -> str`

- [ ] **Step 1: Write the failing test**

`tests/test_obs.py`:
```python
import json
import os
from nl2sql.obs.run import RunFolder


def test_writes_artifacts(tmp_path):
    rf = RunFolder("run_2026-06-18_001", str(tmp_path))
    p1 = rf.write_text("00_question.txt", "weekly trx by indication")
    p2 = rf.write_json("01_resolve.output.json", {"metrics": ["trx_adjusted"]})
    p3 = rf.write_sql("02_compile.output.sql", "SELECT 1")
    p4 = rf.write_manifest({"status": "done", "verifiers": ["V1", "V2"]})

    assert os.path.isfile(p1) and os.path.isfile(p2)
    assert os.path.isfile(p3) and os.path.isfile(p4)
    with open(p2, encoding="utf-8") as fh:
        assert json.load(fh) == {"metrics": ["trx_adjusted"]}
    assert p4.endswith("run_manifest.json")
    assert "run_2026-06-18_001" in p1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_obs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.obs'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/obs/__init__.py`: (empty file)

`src/nl2sql/obs/run.py`:
```python
from __future__ import annotations
import json
import os


class RunFolder:
    def __init__(self, run_id: str, root: str) -> None:
        self.run_id = run_id
        self.dir = os.path.join(root, run_id)
        os.makedirs(self.dir, exist_ok=True)

    def path(self, name: str) -> str:
        return os.path.join(self.dir, name)

    def write_text(self, name: str, text: str) -> str:
        p = self.path(name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return p

    def write_sql(self, name: str, sql: str) -> str:
        return self.write_text(name, sql)

    def write_json(self, name: str, obj) -> str:
        return self.write_text(name, json.dumps(obj, indent=2, sort_keys=True))

    def write_manifest(self, manifest: dict) -> str:
        return self.write_json("run_manifest.json", manifest)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_obs.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/obs/ tests/test_obs.py
git commit -m "feat: observability run folder + manifest (C-OBS)"
```

---

### Task 14: L2 tool-contract schemas (C-TOOL)

**Files:**
- Create: `src/nl2sql/toolcontract/schemas.py`
- Test: `tests/test_toolcontract.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `TOOL_SCHEMAS: dict[str, dict]` — JSON-schema-shaped descriptors keyed by tool name for `search_semantic_model`, `fetch_schema`, `compile_ir`, `run_verifiers`, `dry_run`, `rca_diagnose`. Each value has `name`, `description`, `input_schema` (a JSON Schema dict), `output_schema`.
  - `tool_names() -> list[str]`

This is the portability seam's contract: both the Claude Code adapter and the Anthropic API adapter (follow-on plans) register these identical schemas.

- [ ] **Step 1: Write the failing test**

`tests/test_toolcontract.py`:
```python
from nl2sql.toolcontract.schemas import TOOL_SCHEMAS, tool_names


def test_expected_tools_present():
    assert set(tool_names()) == {
        "search_semantic_model", "fetch_schema", "compile_ir",
        "run_verifiers", "dry_run", "rca_diagnose",
    }


def test_each_tool_has_required_keys():
    for name, schema in TOOL_SCHEMAS.items():
        assert schema["name"] == name
        assert "description" in schema
        assert schema["input_schema"]["type"] == "object"
        assert "output_schema" in schema
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_toolcontract.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.toolcontract.schemas'`.

- [ ] **Step 3: Write minimal implementation**

`src/nl2sql/toolcontract/schemas.py`:
```python
from __future__ import annotations


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


TOOL_SCHEMAS: dict[str, dict] = {
    "search_semantic_model": {
        "name": "search_semantic_model",
        "description": "Retrieve relevant metrics/dimensions/filters for an NL query.",
        "input_schema": _obj({"query": {"type": "string"}}, ["query"]),
        "output_schema": _obj({"matches": {"type": "array"}}, ["matches"]),
    },
    "fetch_schema": {
        "name": "fetch_schema",
        "description": "Return the physical schema catalog for given tables.",
        "input_schema": _obj({"tables": {"type": "array"}}, ["tables"]),
        "output_schema": _obj({"tables": {"type": "object"}}, ["tables"]),
    },
    "compile_ir": {
        "name": "compile_ir",
        "description": "Compile a Query Intent IR into Snowflake SQL + params.",
        "input_schema": _obj({"ir": {"type": "object"}}, ["ir"]),
        "output_schema": _obj(
            {"sql": {"type": "string"}, "params": {"type": "object"},
             "provenance": {"type": "object"}}, ["sql", "params", "provenance"]),
    },
    "run_verifiers": {
        "name": "run_verifiers",
        "description": "Run V1-V4 over compiled SQL; return per-verifier results.",
        "input_schema": _obj(
            {"sql": {"type": "string"}, "params": {"type": "object"},
             "ir": {"type": "object"}}, ["sql", "ir"]),
        "output_schema": _obj({"results": {"type": "array"}}, ["results"]),
    },
    "dry_run": {
        "name": "dry_run",
        "description": "Snowflake EXPLAIN dry-run (follow-on; not wired in core v1).",
        "input_schema": _obj({"sql": {"type": "string"}}, ["sql"]),
        "output_schema": _obj({"ok": {"type": "boolean"}}, ["ok"]),
    },
    "rca_diagnose": {
        "name": "rca_diagnose",
        "description": "Localize a verify failure to a layer (follow-on; not in core v1).",
        "input_schema": _obj(
            {"ir": {"type": "object"}, "results": {"type": "array"}},
            ["ir", "results"]),
        "output_schema": _obj({"layer": {"type": "string"}}, ["layer"]),
    },
}


def tool_names() -> list[str]:
    return sorted(TOOL_SCHEMAS.keys())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_toolcontract.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/nl2sql/toolcontract/schemas.py tests/test_toolcontract.py
git commit -m "feat: L2 tool-contract schemas (C-TOOL)"
```

---

### Task 15: Charter, example config, end-to-end pipeline + integration test (C-CHTR)

**Files:**
- Create: `config/charter.md`
- Create: `config/semantic_model.yaml`
- Create: `config/macros.yaml`
- Create: `config/guardrails.yaml`
- Create: `config/catalog.yaml`
- Create: `src/nl2sql/pipeline.py`
- Test: `tests/test_pipeline_e2e.py`

**Interfaces:**
- Consumes: every prior task — `QueryIntent`, `SemanticModel`, `MacroRegistry`, `GuardrailPolicy`, `Catalog`, `compile_ir`, `run_verifiers`/`all_passed`, `ModelClient`, `RunFolder`.
- Produces:
  - `class PipelineResult(BaseModel)`: `run_id: str`, `passed: bool`, `sql: str`, `run_dir: str`
  - `run_pipeline(ir: QueryIntent, model, macros, policy, catalog, client, run_id, root) -> PipelineResult` — compiles, verifies, writes the full run folder (`00_question.txt`, `02_compile.output.sql`, `02_compile.provenance.json`, `03_verify.V*.json`, `run_manifest.json`), returns the result.

This task wires the deterministic core into one callable and proves the spec's headline behavior: hand-written IR → verified SQL + complete, readable run folder. The `config/` files are the real (small) governed inputs; `config/charter.md` is C-CHTR.

Note: this core run folder is intentionally **partial** vs spec §7 — it omits `01_resolve.*` (Resolve is out of scope; the IR is given), `04_rca.json`, and `05_repair/` (RCA + repair loop are follow-on plans). The same `RunFolder` writes those artifacts unchanged once those stages exist.

- [ ] **Step 1: Write the failing test**

`tests/test_pipeline_e2e.py`:
```python
import json
import os
from nl2sql.ir import QueryIntent, Filter, TimeSpec
from nl2sql.semantic.model import SemanticModel
from nl2sql.semantic.macros import MacroRegistry
from nl2sql.guardrails.policy import GuardrailPolicy
from nl2sql.catalog.catalog import Catalog
from nl2sql.toolcontract.model_client import FakeModelClient
from nl2sql.pipeline import run_pipeline

MODEL = SemanticModel.load("config/semantic_model.yaml")
MACROS = MacroRegistry.load("config/macros.yaml")
POLICY = GuardrailPolicy.load("config/guardrails.yaml")
CAT = Catalog.load("config/catalog.yaml")


def _ir():
    return QueryIntent(
        ir_version="1.0",
        question="weekly tremfya trx split by indication for IBD market",
        metrics=["trx_adjusted"], dimensions=["indication", "week_ending"],
        filters=[Filter(ref="filter.ibd_market"),
                 Filter(ref="filter.product", value="TREMFYA")],
        time=TimeSpec(grain="week", window={"name": "R13W_default"}),
        grain="indication x week",
    )


def test_charter_exists():
    assert os.path.isfile("config/charter.md")


def test_e2e_pass_writes_full_run_folder(tmp_path):
    client = FakeModelClient('{"passed": true, "reasons": []}')
    res = run_pipeline(_ir(), MODEL, MACROS, POLICY, CAT, client,
                       run_id="run_2026-06-18_001", root=str(tmp_path))
    assert res.passed is True
    assert "SUM(WEEKLY.TRX_ADJUSTED) AS trx_adjusted" in res.sql
    for fname in ["00_question.txt", "02_compile.output.sql",
                  "02_compile.provenance.json", "03_verify.V1.json",
                  "03_verify.V2.json", "03_verify.V3.json",
                  "03_verify.V4.json", "run_manifest.json"]:
        assert os.path.isfile(os.path.join(res.run_dir, fname)), fname
    with open(os.path.join(res.run_dir, "run_manifest.json"), encoding="utf-8") as fh:
        man = json.load(fh)
    assert man["passed"] is True
    assert man["semantic_model_version"] == MODEL.version


def test_e2e_fail_is_recorded(tmp_path):
    client = FakeModelClient('{"passed": false, "reasons": ["wrong grain"]}')
    res = run_pipeline(_ir(), MODEL, MACROS, POLICY, CAT, client,
                       run_id="run_2026-06-18_002", root=str(tmp_path))
    assert res.passed is False
    assert os.path.isfile(os.path.join(res.run_dir, "03_verify.V3.json"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_pipeline_e2e.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl2sql.pipeline'` (and missing `config/`).

- [ ] **Step 3: Write the config files and the pipeline**

`config/charter.md`:
```markdown
# System Charter — NL → SQL Semantic Compiler

## Market / domain
Pharma analytics (IQVIA-style TRx panels) against a Snowflake warehouse.
TRx = adjusted/projected volume, NOT script count. There is no NRx in source.
Consumers: analysts who need governed, auditable SQL — not raw exploration.

## SQL style (steers the compiled output)
- CTE-first where a query has stages; explicit column lists, never SELECT *.
- Deterministic ORDER BY on all grouping dimensions.
- Uppercase bare identifiers; quote only non-bare names.
- Filter values are bound parameters, never inlined.

## Soft defaults
- No stated window → apply the documented default and surface it as an assumption.
- Wide dimensions → top-N + an "Other" rollup.
- Surface every assumption in plain English before finalizing.

## Precedence
Charter < Semantic model < Guardrail policy < explicit user ask.
Hard limits live in the guardrail policy, never here.
```

`config/semantic_model.yaml`:
```yaml
version: "2026-06-18.1"
base_table: WEEKLY
metrics:
  trx_adjusted:
    label: "Adjusted TRx"
    description: "Adjusted volume, not script count. No NRx in source."
    sql: "SUM({table}.TRX_ADJUSTED)"
    grain_floor: product
dimensions:
  indication: { column: INDICATION, type: string }
  week_ending: { column: WEEK_ENDING, type: date, grain: week }
filters:
  ibd_market: { expr: "INDICATION IN ('UC','CD')" }
  product: { expr: "PRODUCT = {value}" }
joins:
  weekly_to_monthly:
    type: left
    left_table: WEEKLY
    right_table: MONTHLY
    on: "WEEKLY.PRODUCT = MONTHLY.PRODUCT"
```

`config/macros.yaml`:
```yaml
macros:
  macro.indication_allocation:
    id: macro.indication_allocation
    description: "Renormalize-within-reported-set allocation (procedural rule)."
    params: [reported_set]
    sql_template: |
      -- vetted CTE; full body lives here, proven by the linked test
    tests: [tests/macros/indication_allocation_test.sql]
```

`config/guardrails.yaml`:
```yaml
row_limit: 2000
max_scanned_bytes: 1000000000
statement_timeout_s: 60
cost_ceiling: 5.0
banned_grains: [patient, patient x week]
allowed_join_tables: [MONTHLY]
forbid_select_star: true
read_only: true
```

`config/catalog.yaml`:
```yaml
tables:
  WEEKLY: [PRODUCT, INDICATION, WEEK_ENDING, TRX_ADJUSTED]
  MONTHLY: [PRODUCT, INDICATION, MONTH, TRX_VOLUME]
```

`src/nl2sql/pipeline.py`:
```python
from __future__ import annotations
from pydantic import BaseModel
from nl2sql.ir import QueryIntent
from nl2sql.semantic.model import SemanticModel
from nl2sql.semantic.macros import MacroRegistry
from nl2sql.guardrails.policy import GuardrailPolicy
from nl2sql.catalog.catalog import Catalog
from nl2sql.toolcontract.model_client import ModelClient
from nl2sql.compiler.compile import compile_ir
from nl2sql.verify.runner import run_verifiers, all_passed
from nl2sql.obs.run import RunFolder


class PipelineResult(BaseModel):
    run_id: str
    passed: bool
    sql: str
    run_dir: str


def run_pipeline(ir: QueryIntent, model: SemanticModel, macros: MacroRegistry,
                 policy: GuardrailPolicy, catalog: Catalog, client: ModelClient,
                 run_id: str, root: str) -> PipelineResult:
    rf = RunFolder(run_id, root)
    rf.write_text("00_question.txt", ir.question)

    compiled = compile_ir(ir, model, macros, policy)
    rf.write_sql("02_compile.output.sql", compiled.sql)
    rf.write_json("02_compile.provenance.json", compiled.provenance)

    results = run_verifiers(compiled.sql, compiled.params, ir, policy, catalog, client)
    for r in results:
        rf.write_json(f"03_verify.{r.verifier}.json", r.model_dump())

    passed = all_passed(results)
    rf.write_manifest({
        "run_id": run_id,
        "passed": passed,
        "semantic_model_version": model.version,
        "verifiers": {r.verifier: {"passed": r.passed, "status": r.status}
                      for r in results},
    })
    return PipelineResult(run_id=run_id, passed=passed,
                          sql=compiled.sql, run_dir=rf.dir)
```

- [ ] **Step 4: Run the full suite to verify everything passes**

Run: `py -3 -m pytest -v`
Expected: PASS (all tests across all tasks green).

- [ ] **Step 5: Commit**

```bash
git add config/ src/nl2sql/pipeline.py tests/test_pipeline_e2e.py
git commit -m "feat: charter, config, end-to-end pipeline + integration test (C-CHTR)"
```

---

## Done criteria

- `py -3 -m pytest -v` is green.
- Feeding a hand-written `QueryIntent` to `run_pipeline` yields verified Snowflake SQL and a complete, human-readable run folder (`00_question.txt`, `02_compile.output.sql`, `02_compile.provenance.json`, `03_verify.V1..V4.json`, `run_manifest.json`).
- All Global Constraints hold: read-only, no `SELECT *`, parameterized values, LIMIT cap, banned-grain rejection, declared-join enforcement, deterministic output.

## Follow-on plans (not in this plan)
1. **Resolve + retrieval (C-RES, C-IDX)** — NL → IR with the LLM, plus the retrieval index; early feasibility exit.
2. **RCA + repair loop (C-RCA, C-REP)** — fault localization to a layer + RCA-routed retry.
3. **Orchestration adapters (C-ADPT-CC, C-ADPT-API)** — Claude Code skills, then the Anthropic API agent loop, both binding `model_client` and registering `TOOL_SCHEMAS`.
4. **Live Snowflake dry-run + V4 activation** — wire `dry_run`, enable result-sanity sampling.
5. **Macro SQL inlining** — compile referenced macros (needs declared-join compilation) and run macro tests.
6. **Eval harness (C-EVAL)** — golden NL→IR→SQL set, CI pass-rate + RCA-layer dashboard.

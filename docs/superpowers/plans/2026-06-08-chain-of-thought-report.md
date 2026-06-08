# Chain-of-Thought (CoT) Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an on-demand Python generator that scans the engine's live source (CLAUDE.md workflow, semantic rules, metadata, run artifacts) and renders a DataZymes-coloured HTML "Chain-of-Thought report" whose heroes are the business rule(s) and a worked example computed from real data.

**Architecture:** A deterministic pipeline — `scan → model → examples → render → structural-QA → write`. Numbers flow through a single `example_for()` path (run `result.csv` is authoritative; intermediates from an optional `cot_trace.json`, else a reconciled recompute). The "why" is authored into each rule's source as a `rationale` field. Two modes: run mode (`output/<run_id>/chain_of_thought.html`) and engine mode (`docs/chain_of_thought.html`).

**Tech Stack:** Python 3.14 via `py -3`, pandas 3.0.2, PyYAML (all installed). No new dependencies — HTML via Python string templating. Tests via pytest 9.0.2.

**Spec:** `docs/superpowers/specs/2026-06-08-chain-of-thought-documentation-design.md`

---

> **⚠ Git is not initialised in this repo** (per MEMORY.md — the user chose to skip git). There are no commits. Each task ends with a **Checkpoint** step (run the task's tests green) instead of a commit. If git is later initialised, each Checkpoint maps to a commit with the suggested message shown.
>
> **Run commands from the project root** `C:\Users\RounakSuranshe\Documents\query-to-slide`. Use `py -3`, never `python`.

## File structure (locked before tasks)

**New — generator (each file one responsibility):**
- `scripts/cot_model.py` — dataclasses only (`Rule`, `WorkflowStep`, `ExampleStep`, `Example`, `RunArtifacts`, `CotModel`). No logic.
- `scripts/cot_scan.py` — read & parse live sources → model objects (rules, workflow, relationships, rule-log, run artifacts, schema status, governing-rule detection).
- `scripts/cot_examples.py` — the single `example_for(rule, source)` path + RULE-004 reconciled recompute fallback.
- `scripts/cot_render.py` — model → HTML fragments + `render_html()` + `structural_qa()`.
- `scripts/cot_template.html` — `<head>` + the approved v2 CSS + body skeleton with `<!--SLOT-->` markers.
- `scripts/build_cot.py` — CLI orchestrator (mode detection, wires scan→examples→render→QA→write).

**New — tests:** `tests/test_cot_scan.py`, `tests/test_cot_examples.py`, `tests/test_cot_render.py`, `tests/test_build_cot.py`.

**Modified:**
- `semantic/metrics.md` — add `rationale` to RULE-003, RULE-004.
- `semantic/context.md` — add `rationale` to RULE-301.
- `output/run_2026-06-04_002/analysis_code.py` — emit `cot_trace.json` (reference implementation of the contract).
- `CLAUDE.md` — add `rationale` to the §4 rule template; add opt-in Step 9.
- `MEMORY.md` — record the artifact, builder, trigger.

**Reference (do not paste 200 lines — reuse):** the approved design CSS lives in `docs/chain_of_thought_mockup_v2.html`. Task 7 copies its `<style>` block verbatim.

---

### Task 1: Data model

**Files:**
- Create: `scripts/cot_model.py`
- Test: `tests/test_cot_scan.py` (model import test lives here to avoid a near-empty file)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cot_scan.py
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from cot_model import Rule, WorkflowStep, ExampleStep, Example, RunArtifacts, CotModel


def test_rule_defaults():
    r = Rule(id="RULE-004", name="Indication allocation", file="metrics.md",
             category="metric", applies_to="x", definition="d", formula="f",
             caveats="c", rationale=None, provenance="p")
    assert r.reviewed is False           # default
    assert r.rationale is None           # missing why allowed


def test_example_shape():
    s = ExampleStep(id=1, label="mix", code_line=24, values={"UC": 41.0, "CD": 52.0})
    e = Example(rule_id="RULE-004", period="2026-05-08", steps=[s],
                final={"UC": 3120.92, "CD": 3905.16}, reconciles_to=7026.07,
                reconciled=True, source="trace")
    assert e.steps[0].values["UC"] == 41.0
    assert e.reconciled is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_cot_scan.py::test_rule_defaults -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cot_model'`.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/cot_model.py
"""Dataclasses for the Chain-of-Thought report. No logic lives here."""
from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class Rule:
    id: str
    name: str
    file: str
    category: str
    applies_to: str
    definition: str
    formula: str
    caveats: str
    rationale: Optional[str]      # None -> renders "⚠ why pending"
    provenance: str
    reviewed: bool = False        # from _rule_log.csv


@dataclass
class WorkflowStep:
    number: int
    title: str
    summary: str


@dataclass
class ExampleStep:
    id: int                       # ↔ markers ❶❷❸
    label: str
    code_line: Optional[int]
    values: dict
    extra: dict = field(default_factory=dict)


@dataclass
class Example:
    rule_id: str
    period: str
    steps: list
    final: dict
    reconciles_to: Optional[float]
    reconciled: bool
    source: str                   # "trace" | "recompute" | "none"
    warning: Optional[str] = None


@dataclass
class RunArtifacts:
    run_id: str
    query: str
    plan_text: str
    code_text: str
    context_text: str
    result_df: Any                # pandas DataFrame
    trace: Optional[dict]


@dataclass
class CotModel:
    mode: str                     # "run" | "engine"
    generated: str
    schema_status: str
    rules: list
    workflow: list
    relationships: list
    run: Optional[RunArtifacts]
    governing_rule_ids: list
    examples: dict                # rule_id -> Example
    scanned: list = field(default_factory=list)   # files read this build (audit strip)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_cot_scan.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Checkpoint** — tests green. *(git msg: `feat: cot data model`)*

---

### Task 2: Rule parser (the hard part — multi-line folded fields)

**Files:**
- Create: `scripts/cot_scan.py`
- Test: `tests/test_cot_scan.py` (append)

Rule blocks look like (real sample from `semantic/metrics.md`):
```
## RULE-004: Indication allocation of weekly volume
- applies_to: Weekly_Data_Tabular.TRX_ADJUSTED, Monthly_Data_Tabular.TRX_VOLUME
- category: metric
- definition: >
    The Weekly table carries a brand's total weekly TRx but no indication
    ...
- provenance: auto-saved | 2026-06-04 | R | run_id=discussion | revised ...
```
Fields are `- key: value`; a `>` value means a folded block whose content is the indented lines that follow, until the next `- key:` or end of block.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cot_scan.py  (append)
import cot_scan

SEM = pathlib.Path(__file__).resolve().parents[1] / "semantic"


def test_parse_rules_finds_all_three():
    rules = cot_scan.parse_rules(SEM)
    ids = {r.id for r in rules}
    assert {"RULE-003", "RULE-004", "RULE-301"} <= ids


def test_parse_rule_004_fields():
    rules = {r.id: r for r in cot_scan.parse_rules(SEM)}
    r = rules["RULE-004"]
    assert r.name.startswith("Indication allocation")
    assert r.category == "metric"
    assert r.file == "metrics.md"
    assert "renormalise" in r.definition.lower()
    assert "overstates" in r.caveats.lower()
    assert "TRX_ADJUSTED" in r.applies_to
    assert r.provenance.startswith("auto-saved")


def test_rationale_absent_is_none(tmp_path):
    # A rule with no `rationale` field parses to rationale=None. Verified against a
    # SYNTHETIC rule (not a live one) so this test stays valid after Task 4 adds a
    # rationale to all three real rules — it never needs to be deleted or rescoped.
    (tmp_path / "scratch.md").write_text(
        "## RULE-900: scratch\n- category: filter\n- definition: d\n- provenance: p\n",
        encoding="utf-8")
    rules = {r.id: r for r in cot_scan.parse_rules(tmp_path)}
    assert rules["RULE-900"].rationale is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_cot_scan.py::test_parse_rules_finds_all_three -v`
Expected: FAIL — `AttributeError: module 'cot_scan' has no attribute 'parse_rules'`.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/cot_scan.py
"""Read and parse the engine's live sources into model objects."""
import re
import textwrap
import pathlib
from cot_model import Rule

_RULE_HEADER = re.compile(r"^## (RULE-\d+):\s*(.+?)\s*$")
_FIELD = re.compile(r"^- (\w+):\s?(.*)$")
_KNOWN_FIELDS = {"applies_to", "category", "definition", "formula",
                 "caveats", "rationale", "provenance"}


def _finalize(buf):
    return textwrap.dedent("\n".join(buf)).strip()


def _parse_block(block_lines):
    header = _RULE_HEADER.match(block_lines[0])
    rid, name = header.group(1), header.group(2)
    fields, key, buf = {}, None, []
    for line in block_lines[1:]:
        fm = _FIELD.match(line)
        if fm and fm.group(1) in _KNOWN_FIELDS:
            if key is not None:
                fields[key] = _finalize(buf)
            key = fm.group(1)
            first = fm.group(2)
            buf = [] if first.strip() in ("", ">") else [first]
        elif key is not None:
            buf.append(line)
    if key is not None:
        fields[key] = _finalize(buf)
    return rid, name, fields


def parse_rules(semantic_dir):
    """Parse every RULE-NNN block across all semantic/*.md files."""
    semantic_dir = pathlib.Path(semantic_dir)
    reviewed = parse_rule_log(semantic_dir / "_rule_log.csv")
    rules = []
    for md in sorted(semantic_dir.glob("*.md")):
        lines = md.read_text(encoding="utf-8").splitlines()
        # find rule header line indices
        starts = [i for i, ln in enumerate(lines) if _RULE_HEADER.match(ln)]
        for n, start in enumerate(starts):
            end = starts[n + 1] if n + 1 < len(starts) else len(lines)
            rid, name, f = _parse_block(lines[start:end])
            rules.append(Rule(
                id=rid, name=name, file=md.name,
                category=f.get("category", ""),
                applies_to=f.get("applies_to", ""),
                definition=f.get("definition", ""),
                formula=f.get("formula", ""),
                caveats=f.get("caveats", ""),
                rationale=f.get("rationale"),         # None if absent
                provenance=f.get("provenance", ""),
                reviewed=reviewed.get(rid, False),
            ))
    return rules


def parse_rule_log(path):
    """Return {rule_id: reviewed_bool} from _rule_log.csv."""
    import csv
    path = pathlib.Path(path)
    out = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[row["rule_id"]] = row.get("reviewed", "").strip().lower() == "yes"
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_cot_scan.py -v`
Expected: PASS (5 passed — model + parser tests).

- [ ] **Step 5: Checkpoint** — tests green. *(git msg: `feat: cot rule parser`)*

---

### Task 3: Scan workflow, relationships, run artifacts, governing rules, schema status

**Files:**
- Modify: `scripts/cot_scan.py`
- Test: `tests/test_cot_scan.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cot_scan.py  (append)
ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_parse_workflow_steps():
    steps = cot_scan.parse_workflow(ROOT / "CLAUDE.md")
    nums = [s.number for s in steps]
    # Steps 1-8 are the analysis workflow. Task 10 appends the engine's own opt-in
    # Step 9 (CoT report) to CLAUDE.md, so assert the 1-8 prefix + ascending order
    # rather than strict equality with [1..8] (which would break once Step 9 exists
    # and the full suite re-runs at Task 11).
    assert nums[:8] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert nums == sorted(nums)       # contiguous, ascending (8 now, 9 after Task 10)
    assert steps[0].title.lower().startswith("parse")
    assert steps[0].summary           # non-empty first sentence


def test_parse_relationships():
    edges = cot_scan.parse_relationships(ROOT / "metadata" / "relationships.yaml")
    assert len(edges) == 1
    assert edges[0]["type"] == "many-to-one"


def test_load_run_and_governing_rules():
    run = cot_scan.load_run(ROOT / "output" / "run_2026-06-04_002")
    assert run.run_id == "run_2026-06-04_002"
    assert "tremfya" in run.query.lower()
    assert list(run.result_df.columns) == ["WEEK_ENDING", "UC", "CD", "TREMFYA_TRx_total"]
    gov = cot_scan.governing_rule_ids(run, {"RULE-003", "RULE-004", "RULE-301"})
    assert gov == ["RULE-003", "RULE-004", "RULE-301"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_cot_scan.py::test_parse_workflow_steps -v`
Expected: FAIL — `AttributeError: ... no attribute 'parse_workflow'`.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/cot_scan.py  (append these imports at top alongside existing ones)
import subprocess
import yaml
import pandas as pd
from cot_model import WorkflowStep, RunArtifacts

_STEP_HEADER = re.compile(r"^### Step (\d+) — (.+?)\s*$")
_RULE_TOKEN = re.compile(r"RULE-\d+")


def parse_workflow(claude_md):
    """Parse '### Step N — Title' headers + first sentence from CLAUDE.md."""
    lines = pathlib.Path(claude_md).read_text(encoding="utf-8").splitlines()
    steps = []
    for i, ln in enumerate(lines):
        m = _STEP_HEADER.match(ln)
        if not m:
            continue
        summary = ""
        for nxt in lines[i + 1:]:
            if nxt.strip() and not nxt.startswith("#"):
                summary = nxt.strip().lstrip("- ").split(". ")[0].strip(". ")
                break
        steps.append(WorkflowStep(number=int(m.group(1)),
                                  title=m.group(2).split(" — ")[0].strip(),
                                  summary=summary))
    return steps


def parse_relationships(path):
    """Return the list of declared join edges from relationships.yaml."""
    data = yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8"))
    return data.get("relationships", []) if data else []


def _read(path):
    p = pathlib.Path(path)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def load_run(run_dir):
    """Load one run folder's artifacts (run mode)."""
    run_dir = pathlib.Path(run_dir)
    trace_path = run_dir / "cot_trace.json"
    trace = None
    if trace_path.exists():
        import json
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
    return RunArtifacts(
        run_id=run_dir.name,
        query=_read(run_dir / "query.txt").strip(),
        plan_text=_read(run_dir / "analysis_plan.md"),
        code_text=_read(run_dir / "analysis_code.py"),
        context_text=_read(run_dir / "context.md"),
        result_df=pd.read_csv(run_dir / "result.csv"),
        trace=trace,
    )


def governing_rule_ids(run, known_ids):
    """RULE-NNN tokens mentioned in the run's plan + code + context."""
    text = run.plan_text + run.code_text + run.context_text
    found = sorted(set(_RULE_TOKEN.findall(text)) & set(known_ids))
    return found


def schema_status(project_root):
    """Run validate_schema.py and return a one-line verdict for the header."""
    try:
        out = subprocess.run(["py", "-3", "scripts/validate_schema.py"],
                             cwd=str(project_root), capture_output=True,
                             text=True, timeout=120)
        text = (out.stdout + out.stderr).strip().splitlines()
        for ln in reversed(text):
            if ln.strip():
                return ln.strip()
    except Exception as exc:                       # never block the build
        return f"schema check unavailable ({exc.__class__.__name__})"
    return "unknown"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_cot_scan.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Checkpoint** — tests green. *(git msg: `feat: cot scanners for workflow/relationships/run`)*

---

### Task 4: Add `rationale` to the three live rules

**Files:**
- Modify: `semantic/metrics.md` (RULE-003, RULE-004)
- Modify: `semantic/context.md` (RULE-301)
- Test: `tests/test_cot_scan.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cot_scan.py  (append)
def test_rationale_now_present():
    rules = {r.id: r for r in cot_scan.parse_rules(SEM)}
    for rid in ("RULE-003", "RULE-004", "RULE-301"):
        assert rules[rid].rationale, f"{rid} missing rationale"
    assert "sum back to the true weekly total" in rules["RULE-004"].rationale.lower() \
        or "never silently lose" in rules["RULE-004"].rationale.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_cot_scan.py::test_rationale_now_present -v`
Expected: FAIL — assertion error (rationale is None).

- [ ] **Step 3: Add the field.** In `semantic/metrics.md`, insert a `rationale:` line directly **above** each `- provenance:` line.

For RULE-003:
```markdown
- rationale: >
    The two extracts label the same brand differently — Weekly carries one
    form-specific line, Monthly splits by dose/form. Without a crosswalk the
    Monthly indication mix can't be borrowed at all, so this rule is the
    precondition for any indication split. Matching FORM (never folding IV into
    SQ) keeps the borrowed mix true to what the weekly line actually represents.
```

For RULE-004:
```markdown
- rationale: >
    The weekly panel has no indication breakdown — only the monthly table does.
    Renormalising the mix within the reported set guarantees the parts sum back
    to the true weekly total, so a UC/CD view never silently loses volume.
    Trade-off, stated: a subset like IBD then absorbs the whole total, which
    overstates it versus an on-label denominator — acceptable only because the
    weekly panel is genuinely IBD-only (RULE-301).
```

In `semantic/context.md`, insert above RULE-301's `- provenance:` line:
```markdown
- rationale: >
    The "SI Market + Oral" weekly panel is a GI/IBD panel, so a product's whole
    weekly TRx here is IBD usage even for drugs used in derm/rheum nationally.
    This is what makes RULE-004's "whole total to {UC, CD}" correct rather than
    an overstatement — it tells the allocation which denominator is the truth.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_cot_scan.py -v`
Expected: PASS (9 passed).

- [ ] **Step 5: Checkpoint** — tests green. *(git msg: `rule: add rationale to RULE-003/004/301`)*

---

### Task 5: Worked-example engine (`example_for` + RULE-004 reconciled recompute)

**Files:**
- Create: `scripts/cot_examples.py`
- Test: `tests/test_cot_examples.py`

Real reconciliation target (run_002, week 2026-05-08): `UC=3120.916383`, `CD=3905.157025`, `TREMFYA_TRx_total=7026.073408`. `UC+CD == total`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cot_examples.py
import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import pandas as pd
import cot_examples
from cot_model import Rule

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN = ROOT / "output" / "run_2026-06-04_002"


def _rule(rid, cat="metric"):
    return Rule(id=rid, name="x", file="metrics.md", category=cat, applies_to="",
                definition="", formula="", caveats="", rationale="r", provenance="p")


def _source():
    return {"result_df": pd.read_csv(RUN / "result.csv"),
            "data_dir": ROOT / "data", "trace": None}


def test_rule004_recompute_reconciles():
    ex = cot_examples.example_for(_rule("RULE-004"), _source())
    assert ex.source == "recompute"
    assert ex.reconciled is True
    assert abs(ex.final["UC"] - 3121) < 1     # final rounded to whole TRx (matches §3.3.1 trace contract)
    assert abs(ex.final["CD"] - 3905) < 1
    assert abs(ex.final["UC"] + ex.final["CD"] - ex.reconciles_to) < 1e-3
    # shares step sums to 1.0
    shares = next(s for s in ex.steps if "share" in s.label.lower())
    assert abs(sum(shares.values.values()) - 1.0) < 1e-6


def test_trace_takes_precedence():
    src = _source()
    src["trace"] = {"schema": "cot_trace/v1", "example_period": "2026-05-08",
                    "rules": {"RULE-004": {
                        "steps": [
                            {"id": 1, "label": "monthly mix", "code_line": 24,
                             "values": {"UC": 41.0, "CD": 52.0}},
                            {"id": 2, "label": "renormalised shares", "code_line": 27,
                             "values": {"UC": 0.4442, "CD": 0.5558}},
                            {"id": 3, "label": "applied to total", "code_line": 31,
                             "values": {"UC": 3120.916383, "CD": 3905.157025}},
                        ],
                        "final": {"UC": 3120.916383, "CD": 3905.157025},
                        "reconciles_to": 7026.073408}}}
    ex = cot_examples.example_for(_rule("RULE-004"), src)
    assert ex.source == "trace"
    assert ex.steps[0].code_line == 24
    assert ex.reconciled is True


def test_no_compute_fn_is_pending_not_fabricated():
    ex = cot_examples.example_for(_rule("RULE-301", cat="context"), _source())
    assert ex.source == "none"
    assert ex.final == {}            # nothing fabricated
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_cot_examples.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cot_examples'`.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/cot_examples.py
"""The single worked-example path. result.csv is always authoritative for
finals; intermediates come from cot_trace.json when present, else a reconciled
recompute. Never fabricates numbers."""
import pandas as pd
from cot_model import Example, ExampleStep

_TOL = 1e-3
_REPORTED = ["UC", "CD"]
_TREMFYA_SQ = ["TREMFYA SQ 100MG", "TREMFYA SQ 200MG", "TREMFYA SQ INDUCTION"]


def example_for(rule, source):
    """Return an Example for `rule` using the precedence in spec §3.3."""
    trace = (source.get("trace") or {}).get("rules", {}).get(rule.id)
    if trace:
        return _from_trace(rule, source, trace)
    if rule.id == "RULE-004" and source.get("result_df") is not None:
        return _recompute_rule004(rule, source)
    return Example(rule_id=rule.id, period="", steps=[], final={},
                   reconciles_to=None, reconciled=False, source="none",
                   warning="example pending — no trace or compute function")


def _from_trace(rule, source, trace):
    steps = [ExampleStep(id=s["id"], label=s["label"], code_line=s.get("code_line"),
                         values=s["values"], extra={k: v for k, v in s.items()
                         if k not in ("id", "label", "code_line", "values")})
             for s in trace["steps"]]
    final = trace["final"]
    recon = trace.get("reconciles_to")
    reconciled = _check_reconcile(final, recon, source.get("result_df"))
    return Example(rule_id=rule.id, period=(source.get("trace") or {}).get("example_period", ""),
                   steps=steps, final=final, reconciles_to=recon,
                   reconciled=reconciled, source="trace",
                   warning=None if reconciled else "⚠ example could not be reconciled")


def _recompute_rule004(rule, source):
    df = source["result_df"].copy()
    df["WEEK_ENDING"] = pd.to_datetime(df["WEEK_ENDING"])
    last = df.sort_values("WEEK_ENDING").iloc[-1]
    total = float(last["TREMFYA_TRx_total"])
    final = {"UC": float(last["UC"]), "CD": float(last["CD"])}   # authoritative

    monthly = pd.read_csv(source["data_dir"] / "Monthly_Data_Tabular.csv",
                          parse_dates=["MONTH_DATE"])
    b = monthly[(monthly["ROW_TYPE"] == "PRODUCT")
                & monthly["PRODUCT"].isin(_TREMFYA_SQ)
                & monthly["INDICATION"].isin(_REPORTED)]
    mt = (b.groupby(["MONTH_DATE", "INDICATION"])["TRX_VOLUME"].sum()
           .unstack(fill_value=0.0).reindex(columns=_REPORTED, fill_value=0.0))
    week_month = last["WEEK_ENDING"].to_period("M").to_timestamp()
    months = mt.index.sort_values()
    eligible = months[months <= week_month]
    rmonth = eligible.max() if len(eligible) else months.min()
    raw = mt.loc[rmonth]
    raw_vals = {"UC": float(raw["UC"]), "CD": float(raw["CD"])}
    denom = raw["UC"] + raw["CD"]
    shares = {"UC": float(raw["UC"] / denom), "CD": float(raw["CD"] / denom)}
    applied = {k: round(total * shares[k], 6) for k in _REPORTED}

    reconciled = (abs(final["UC"] + final["CD"] - total) < _TOL
                  and abs(applied["UC"] - final["UC"]) < 1.0
                  and abs(applied["CD"] - final["CD"]) < 1.0)

    steps = [
        ExampleStep(1, "monthly mix (UC,CD) TRX_VOLUME", 24, raw_vals,
                    extra={"month": str(rmonth.date())}),
        ExampleStep(2, "renormalised shares", 27,
                    {k: round(v, 4) for k, v in shares.items()}),
        ExampleStep(3, "applied to weekly total", 31, {k: round(v) for k, v in final.items()},
                    extra={"weekly_total": round(total)}),
    ]
    return Example(rule_id=rule.id, period=str(last["WEEK_ENDING"].date()),
                   steps=steps, final={k: round(v) for k, v in final.items()},
                   reconciles_to=round(total), reconciled=reconciled,
                   source="recompute",
                   warning=None if reconciled else "⚠ example could not be reconciled")


def _check_reconcile(final, recon, result_df):
    if recon is None:
        return False
    if abs(sum(final.values()) - recon) >= _TOL:
        return False
    if result_df is not None:
        df = result_df.copy()
        df["WEEK_ENDING"] = pd.to_datetime(df["WEEK_ENDING"])
        last = df.sort_values("WEEK_ENDING").iloc[-1]
        for k in final:
            if k in result_df.columns and abs(final[k] - float(last[k])) > 1.0:
                return False
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_cot_examples.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Checkpoint** — tests green. *(git msg: `feat: cot worked-example engine`)*

---

### Task 6: Emit `cot_trace.json` from the run's analysis code (reference contract)

**Files:**
- Modify: `output/run_2026-06-04_002/analysis_code.py`
- Test: `tests/test_cot_examples.py` (append)

This makes the run's own computation the source of intermediates (spec §3.3.1) and gives us real trace data.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cot_examples.py  (append)
def test_run002_emits_valid_trace():
    trace_path = RUN / "cot_trace.json"
    assert trace_path.exists(), "run analysis_code.py must emit cot_trace.json"
    t = json.loads(trace_path.read_text(encoding="utf-8"))
    assert t["schema"] == "cot_trace/v1"
    r4 = t["rules"]["RULE-004"]
    assert abs(r4["final"]["UC"] + r4["final"]["CD"] - r4["reconciles_to"]) < 1e-3
    assert [s["id"] for s in r4["steps"]] == [1, 2, 3]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_cot_examples.py::test_run002_emits_valid_trace -v`
Expected: FAIL — file does not exist.

- [ ] **Step 3: Add trace emission.** In `output/run_2026-06-04_002/analysis_code.py`, add this function and call it from `main()` after `result` is built (it recomputes the example month locally so the run owns its trace):

```python
def write_trace(result, shares):
    """Emit cot_trace.json — the intermediates behind the latest week's split."""
    import json
    res = result.copy()
    res["WEEK_ENDING"] = pd.to_datetime(res["WEEK_ENDING"])
    last = res.sort_values("WEEK_ENDING").iloc[-1]
    total = float(last["TREMFYA_TRx_total"])
    week_month = last["WEEK_ENDING"].to_period("M").to_timestamp()
    months = shares.index.sort_values()
    eligible = months[months <= week_month]
    rmonth = eligible.max() if len(eligible) else months.min()
    sh = shares.loc[rmonth]
    trace = {
        "schema": "cot_trace/v1",
        "example_period": str(last["WEEK_ENDING"].date()),
        "rules": {"RULE-004": {
            "steps": [
                {"id": 1, "label": "renormalised monthly shares (UC,CD)",
                 "code_line": 95, "values": {"UC": round(float(sh["UC"]), 4),
                                             "CD": round(float(sh["CD"]), 4)},
                 "month": str(rmonth.date())},
                {"id": 2, "label": "weekly TREMFYA total", "code_line": 108,
                 "values": {"total": round(total)}},
                {"id": 3, "label": "allocated UC / CD", "code_line": 118,
                 "values": {"UC": round(float(last["UC"])),
                            "CD": round(float(last["CD"]))}},
            ],
            "final": {"UC": round(float(last["UC"])), "CD": round(float(last["CD"]))},
            "reconciles_to": round(total),
        }},
    }
    out = Path(__file__).resolve().parent / "cot_trace.json"
    out.write_text(json.dumps(trace, indent=2), encoding="utf-8")
```

Then change the tail of `main()` from:
```python
    result.to_csv(OUTPUT_CSV, index=False)
    print(f"wrote {len(result)} rows -> {OUTPUT_CSV}")
```
to:
```python
    result.to_csv(OUTPUT_CSV, index=False)
    write_trace(result, shares)
    print(f"wrote {len(result)} rows -> {OUTPUT_CSV} (+ cot_trace.json)")
```
(`shares` is already a local in `main()` from `monthly_indication_shares(monthly)`.)

- [ ] **Step 4: Regenerate the run, then run the test**

Run: `py -3 output/run_2026-06-04_002/analysis_code.py`
Expected: `wrote 106 rows -> ...result.csv (+ cot_trace.json)`
Run: `py -3 -m pytest tests/test_cot_examples.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Checkpoint** — tests green; `cot_trace.json` exists in the run folder. *(git msg: `feat: emit cot_trace.json from run_002`)*

---

### Task 7: HTML template (approved design)

**Files:**
- Create: `scripts/cot_template.html`
- Test: `tests/test_cot_render.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cot_render.py
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_template_has_slots_and_brand_colours():
    tpl = (ROOT / "scripts" / "cot_template.html").read_text(encoding="utf-8")
    assert "<!--BODY-->" in tpl
    assert "<!--GENERATED-->" in tpl
    assert "071D49" in tpl and "07B2AC" in tpl and "E40D62" in tpl  # DZ colours
    assert "Fraunces" in tpl and "JetBrains Mono" in tpl
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_cot_render.py::test_template_has_slots_and_brand_colours -v`
Expected: FAIL — template file missing.

- [ ] **Step 3: Create the template.** Create `scripts/cot_template.html` with this exact skeleton, and paste the **entire `<style>…</style>` block copied verbatim from `docs/chain_of_thought_mockup_v2.html`** where shown (it is the approved v2 design; do not redesign):

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chain of Thought — <!--RUNID--></title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300..900;1,9..144,300..700&family=Hanken+Grotesk:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<!-- PASTE THE <style>…</style> BLOCK FROM docs/chain_of_thought_mockup_v2.html HERE VERBATIM -->
</head>
<body>
<div class="spine"></div>
<div class="wrap">
<!--BODY-->
<footer class="foot">
  <span>Query-to-Slide · Chain-of-Thought report · <!--RUNID--></span>
  <span class="wm">▶ DataZymes<i>.</i></span>
  <span>generated <!--GENERATED--></span>
</footer>
</div>
</body>
</html>
```

After pasting the mockup `<style>` verbatim, append CSS for the renderer-emitted classes that the mockup does not already define, using **DataZymes colours only** (navy `071D49`, teal `07B2AC`, amber `FFC000` as a *fill with dark text*, magenta `E40D62`) and the established editorial type scale — so the new sections match the approved look rather than falling back to unstyled defaults. Classes to cover: `.scan .chip`, `.pipe .stages .stage .stage.hero .snum .slab .branch`, `.sec.ctx .ctx-row`, `.codepanel .cline .lno .mk`, `.work-sec`, `.catalogue .catlist .catrow .cname .cstat`, `.wf-step .wf-fork`, and `.pill.warn`. Keep all infographics carrying their adjacent numeric labels (no colour-only meaning) per spec §4 accessibility.

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_cot_render.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Checkpoint** — tests green. *(git msg: `feat: cot html template`)*

---

### Task 8: Renderer + structural QA

**Files:**
- Create: `scripts/cot_render.py`
- Test: `tests/test_cot_render.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cot_render.py  (append)
import cot_render
from cot_model import Rule, Example, ExampleStep, WorkflowStep, CotModel, RunArtifacts
import pandas as pd

RUN = ROOT / "output" / "run_2026-06-04_002"


def _model():
    df = pd.read_csv(RUN / "result.csv")
    rule = Rule(id="RULE-004", name="Indication allocation", file="metrics.md",
                category="metric", applies_to="x", definition="splits the total",
                formula="f", caveats="estimates not census",
                rationale="never loses volume", provenance="auto-saved | R", reviewed=True)
    rule301 = Rule(id="RULE-301", name="IBD-only panel", file="context.md",
                   category="context", applies_to="x", definition="d", formula="n/a",
                   caveats="c", rationale=None, provenance="auto-saved", reviewed=True)
    ex = Example(rule_id="RULE-004", period="2026-05-08",
                 steps=[ExampleStep(2, "renormalised shares", 27, {"UC": 0.4442, "CD": 0.5558})],
                 final={"UC": 3121, "CD": 3905}, reconciles_to=7026,
                 reconciled=True, source="recompute")
    run = RunArtifacts("run_2026-06-04_002", "weekly tremfya TRx split by indication for IBD",
                       "plan", "code", "ctx", df, None)
    return CotModel(mode="run", generated="2026-06-08 14:00", schema_status="ALL CLEAR",
                    rules=[rule, rule301], workflow=[WorkflowStep(1, "Parse", "Read the query")],
                    relationships=[{"type": "many-to-one"}], run=run,
                    governing_rule_ids=["RULE-004", "RULE-301"], examples={"RULE-004": ex})


def test_render_contains_heroes_and_numbers():
    html = cot_render.render_html(_model())
    assert "weekly tremfya TRx split" in html       # the request
    assert "3,121" in html or "3121" in html         # worked-example number
    assert "RULE-004" in html and "RULE-301" in html
    assert "DataZymes" in html
    assert "0.4442" in html                          # per-step worked-example annotation (renormalised share)


def test_missing_rationale_renders_badge():
    html = cot_render.render_html(_model())
    assert "why pending" in html.lower()             # RULE-301 has no rationale


def test_structural_qa_passes_on_good_html():
    html = cot_render.render_html(_model())
    assert cot_render.structural_qa(html) == []

def test_structural_qa_flags_unbalanced():
    errs = cot_render.structural_qa("<div><span></div>")
    assert errs                                       # non-empty


def test_render_contains_all_section4_sections():
    # Spec §4 run-mode section order: pipeline (#3), §02 Context (#5), §04 Code (#7),
    # §05 Worked-example hero (#8), and the rule catalogue (#9) must all be emitted.
    html = cot_render.render_html(_model())
    assert 'class="pipe"' in html                     # §4 #3 run pipeline
    assert '<span class="num">02</span>' in html       # §4 #5 context
    assert '<span class="num">04</span>' in html       # §4 #7 code panel
    assert '<span class="num">05</span>' in html       # §4 #8 worked-example hero
    assert 'class="catalogue"' in html                 # §4 #9 rule catalogue
    assert "❷" in html                                 # code↔example marker keyed to step.id


def test_structural_qa_flags_empty_hero():
    # spec §8: a present-but-empty hero block must fail (not just balanced tags).
    errs = cot_render.structural_qa(
        '<header class="hero"></header><div class="scan"></div>'
        '<span class="num">01</span><span class="num">03</span>'
        '<span class="heroTag">x</span>DataZymes')
    assert any("empty hero" in e for e in errs)


def test_structural_qa_flags_dropped_section():
    # Dropping a run-mode section anchor must be caught (the old 2-needle QA missed it).
    html = cot_render.render_html(_model()).replace('<span class="num">03</span>', '')
    assert cot_render.structural_qa(html) != []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_cot_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cot_render'`.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/cot_render.py
"""Render a CotModel to HTML and run a no-browser structural QA pass."""
import html as _html
import pathlib
import re as _re
from html.parser import HTMLParser

_TPL = pathlib.Path(__file__).with_name("cot_template.html")
_VOID = {"meta", "link", "br", "hr", "img", "input"}
_MARK = {1: "❶", 2: "❷", 3: "❸", 4: "❹", 5: "❺"}   # step.id -> code↔example marker


def _num(v):
    """Format a number with thousands separators; pass strings through."""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return f"{v:,}" if isinstance(v, (int, float)) else _html.escape(str(v))


def _rule_card(rule, example, hero):
    why = (f'<div class="cell why"><span class="lab">Why it exists</span>'
           f'<p>{_html.escape(rule.rationale)}</p></div>') if rule.rationale else \
          ('<div class="cell why"><span class="lab">Why it exists</span>'
           '<p><span class="pendbadge">⚠ why pending</span></p></div>')
    reviewed = '✓ reviewed' if rule.reviewed else '⚠ unreviewed'
    klass = "rule" if hero else "rule condensed"
    # The worked example renders as its own §05 hero section (not inside the card).
    ex_html = ""
    return f"""
<article class="{klass}">
  <div class="rule-top"><span class="rid">{rule.id}</span>
    <h3>{_html.escape(rule.name)}</h3>
    <div class="pills"><span class="pill metric">{_html.escape(rule.category)}</span>
      <span class="pill ok">{reviewed}</span></div></div>
  <div class="rule-grid">
    <div class="cell"><span class="lab">What it does</span>
      <p class="defn">{_html.escape(rule.definition)}</p></div>
    {why}
  </div>
  <div class="cell"><span class="lab">Caveats</span><p>{_html.escape(rule.caveats)}</p></div>
  {ex_html}
</article>"""


def _example_block(ex):
    if ex.source == "none":
        return ('<div class="work"><span class="lab">Worked example</span>'
                '<p class="pendbadge">example pending</p></div>')
    rows = ""
    for s in ex.steps:
        vals = " · ".join(f"{k} {_num(v)}" for k, v in s.values.items())
        line = f'line {s.code_line}' if s.code_line else ''
        rows += (f'<div class="srow"><span class="mk">{_MARK.get(s.id, s.id)}</span>'
                 f'<span class="slbl">{_html.escape(s.label)}<br>{line}</span>'
                 f'<div class="barwrap"><div class="note">{vals}</div></div></div>')
    warn = f'<p class="pendbadge">{_html.escape(ex.warning)}</p>' if ex.warning else ''
    recon = (f'✓ {" + ".join(_num(v) for v in ex.final.values())} = '
             f'{_num(ex.reconciles_to)} — reconciles') if ex.reconciled else ''
    final = " / ".join(f"{k} {_num(v)}" for k, v in ex.final.items())
    return f"""
<div class="work"><span class="lab">Worked example — week {_html.escape(ex.period)}</span>
  <div class="steps">{rows}</div>
  <div class="result"><span class="big">{final}</span><span class="chk">{recon}</span></div>
  {warn}
</div>"""


def _scan_strip(model):
    """The 'scanned →' audit strip: the files read this build + timestamp (§3.1 / §4 #2)."""
    chips = "".join(f'<span class="chip">{_html.escape(f)}</span>' for f in model.scanned)
    return (f'<div class="scan"><span class="lab">scanned →</span>{chips}'
            f'<span class="chip">schema: {_html.escape(model.schema_status)}</span>'
            f'<span class="chip">rules: {len(model.rules)}</span>'
            f'<span class="chip">generated {_html.escape(model.generated)}</span></div>')


def _pipeline(model):
    """§4 #3 — the five-act run pipeline; Plan & Rule and Worked example are heroes."""
    acts = [("01", "Request", False), ("02", "Context", False),
            ("03", "Plan &amp; Rule", True), ("04", "Code", False),
            ("05", "Worked example", True)]
    cells = ""
    for num, label, hero in acts:
        cls = "stage hero" if hero else "stage"
        tag = '<span class="heroTag">HERO</span>' if hero else ''
        cells += (f'<div class="{cls}"><span class="snum">{num}</span>'
                  f'<span class="slab">{label}</span>{tag}</div>')
    return (f'<section class="pipe"><div class="sec-h"><h2>Run pipeline</h2></div>'
            f'<div class="stages">{cells}</div>'
            f'<p class="branch">rule exists → apply · missing → '
            f'define &amp; auto-save RULE-NNN</p></section>')


def _context_section(run):
    """§4 #5 — the context built for this run (verbatim context.md)."""
    body = _html.escape((run.context_text or "").strip()) or "context pending"
    return (f'<section class="sec ctx"><div class="sec-h"><span class="num">02</span>'
            f'<h2>Context</h2></div><pre class="ctx-row">{body}</pre></section>')


def _code_panel(code_text, example):
    """§4 #7 — analysis_code.py with ❶❷❸ markers on the example's code lines."""
    marks = {}
    if example:
        for s in example.steps:
            if s.code_line:
                marks[s.code_line] = _MARK.get(s.id, "•")
    rows = ""
    for i, ln in enumerate((code_text or "").split("\n"), 1):
        mk = marks.get(i, "")
        rows += (f'<div class="cline"><span class="mk">{mk}</span>'
                 f'<span class="lno">{i}</span>'
                 f'<code>{_html.escape(ln)}</code></div>')
    return (f'<section class="sec"><div class="sec-h"><span class="num">04</span>'
            f'<h2>Code</h2></div><div class="codepanel">{rows}</div></section>')


def _worked_example_section(example):
    """§4 #8 — the worked example as its own ★ hero section."""
    inner = _example_block(example) if example else (
        '<div class="work"><p class="pendbadge">example pending</p></div>')
    return (f'<section class="sec work-sec"><div class="sec-h"><span class="num">05</span>'
            f'<h2>Worked example</h2><span class="heroTag">★ hero</span></div>'
            f'{inner}</section>')


def _catalogue(rules):
    """§4 #9 — compact index of every live rule (id, name, category, status)."""
    rows = ""
    for r in rules:
        status = "✓ reviewed" if r.reviewed else "⚠ unreviewed"
        rows += (f'<li class="catrow"><span class="rid">{_html.escape(r.id)}</span>'
                 f'<span class="cname">{_html.escape(r.name)}</span>'
                 f'<span class="pill metric">{_html.escape(r.category)}</span>'
                 f'<span class="cstat">{status}</span></li>')
    return (f'<section class="catalogue"><div class="sec-h"><span class="num">09</span>'
            f'<h2>Rule catalogue</h2></div><ul class="catlist">{rows}</ul></section>')


def _reasoning_path(workflow):
    """Engine-mode infographic — CLAUDE.md workflow steps + the feasibility fork."""
    steps = ""
    for s in workflow:
        steps += (f'<div class="wf-step"><span class="num">{s.number}</span>'
                  f'<span class="slbl">{_html.escape(s.title)}</span>'
                  f'<span class="note">{_html.escape(s.summary)}</span></div>')
    fork = ('<div class="wf-fork"><span class="lab">feasibility</span>'
            '<span class="pill ok">Feasible</span>'
            '<span class="pill metric">With assumptions</span>'
            '<span class="pill warn">Not feasible</span></div>')
    return ('<section class="sec"><div class="sec-h"><span class="num">00</span>'
            '<h2>How the engine reasons</h2>'
            '<span class="heroTag">★ reasoning path</span></div>'
            f'<div class="steps">{steps}</div>{fork}</section>')


def _body(model):
    parts = []
    primary = _primary(model)
    if model.run:
        parts.append(f'<header class="hero"><div class="kick">Chain of Thought · '
                     f'{_html.escape(model.run.run_id)}</div>'
                     f'<h1>From question to <em>number</em>.</h1>'
                     f'<p class="dek">{_html.escape(model.run.query)}</p></header>')
        parts.append(_scan_strip(model))
        parts.append(_pipeline(model))                                   # §4 #3
        parts.append(f'<section class="sec"><div class="sec-h"><span class="num">01</span>'
                     f'<h2>Request</h2></div><p class="req-q">'
                     f'{_html.escape(model.run.query)}</p></section>')    # §4 #4
        parts.append(_context_section(model.run))                        # §4 #5
    else:
        parts.append('<header class="hero"><div class="kick">Chain of Thought · engine</div>'
                     '<h1>How the engine <em>reasons</em>.</h1>'
                     '<p class="dek">The workflow it follows and every rule in force.</p></header>')
        parts.append(_scan_strip(model))
        parts.append(_reasoning_path(model.workflow))                    # engine reasoning path
    parts.append('<section class="sec"><div class="sec-h"><span class="num">03</span>'
                 '<h2>Plan &amp; the rules</h2><span class="heroTag">★ hero</span></div>')
    order = model.governing_rule_ids or [r.id for r in model.rules]
    by_id = {r.id: r for r in model.rules}
    for rid in order:
        if rid in by_id:
            parts.append(_rule_card(by_id[rid], model.examples.get(rid),
                                    hero=(rid == primary)))
    parts.append('</section>')                                           # §4 #6
    if model.run:
        parts.append(_code_panel(model.run.code_text, model.examples.get(primary)))   # §4 #7
        parts.append(_worked_example_section(model.examples.get(primary)))            # §4 #8
    parts.append(_catalogue(model.rules))                                # §4 #9
    return "\n".join(parts)


def _primary(model):
    for rid in model.governing_rule_ids:
        ex = model.examples.get(rid)
        if ex and ex.source != "none" and ex.reconciled:
            return rid
    return model.governing_rule_ids[0] if model.governing_rule_ids else (
        model.rules[0].id if model.rules else "")


def render_html(model):
    tpl = _TPL.read_text(encoding="utf-8")
    runid = model.run.run_id if model.run else "engine"
    return (tpl.replace("<!--BODY-->", _body(model))
               .replace("<!--RUNID-->", _html.escape(runid))
               .replace("<!--GENERATED-->", _html.escape(model.generated)))


class _Checker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in _VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unbalanced </{tag}>")
        else:
            self.stack.pop()


def structural_qa(html):
    """Return a list of structural problems (empty = pass). No browser needed.

    Mirrors spec §8: balanced tags, presence of required section anchors, and that
    every hero block has content. Mode-aware — engine pages omit the run-only acts,
    detected by the run-only `class="req-q"` marker.
    """
    c = _Checker()
    c.feed(html)
    errors = list(c.errors)
    if c.stack:
        errors.append(f"unclosed tags: {c.stack}")
    # Footer wordmark + a hero header are required in BOTH modes.
    if "DataZymes" not in html:
        errors.append('missing required element: DataZymes')
    if '<header class="hero">' not in html:
        errors.append('missing required element: class="hero"')
    # Run-mode pages must carry the five-act anchors + catalogue.
    if 'class="req-q"' in html:
        for needle in ('class="scan"', 'class="pipe"',
                       '<span class="num">01</span>', '<span class="num">02</span>',
                       '<span class="num">03</span>', '<span class="num">04</span>',
                       '<span class="num">05</span>', 'class="catalogue"'):
            if needle not in html:
                errors.append(f"missing required section anchor: {needle}")
    # spec §8: every hero block must have content (present-but-empty fails).
    for m in _re.finditer(
            r'<(header|section|article)[^>]*class="[^"]*\bhero\b[^"]*"[^>]*>(.*?)</\1>',
            html, _re.S):
        if not _re.sub(r"<[^>]+>", "", m.group(2)).strip():
            errors.append("empty hero block")
    return errors
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_cot_render.py -v`
Expected: PASS (8 passed — 1 template + 4 original render tests + `test_render_contains_all_section4_sections` + `test_structural_qa_flags_empty_hero` + `test_structural_qa_flags_dropped_section`).

- [ ] **Step 5: Checkpoint** — tests green. *(git msg: `feat: cot renderer + structural QA`)*

---

### Task 9: CLI orchestrator (`build_cot.py`) — run + engine modes

**Files:**
- Create: `scripts/build_cot.py`
- Test: `tests/test_build_cot.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_build_cot.py
import sys, pathlib, subprocess
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
ROOT = pathlib.Path(__file__).resolve().parents[1]
import build_cot


def test_build_run_mode_writes_reconciled_html():
    out = build_cot.build(ROOT / "output" / "run_2026-06-04_002",
                          generated="2026-06-08 14:00")
    html = out["html"]
    assert out["qa_errors"] == []
    assert out["path"].name == "chain_of_thought.html"
    assert "RULE-004" in html and "RULE-301" in html
    assert "3,121" in html and "3,905" in html        # real reconciled numbers
    assert "7,026" in html
    assert "why pending" not in html.lower()           # all 3 rules have rationale now
    assert "scanned →" in html                          # audit strip present (spec §3.1 / §4 #2)
    assert "semantic/metrics.md" in html and "result.csv" in html  # files read are listed
    assert "2026-06-08 14:00" in html                   # generated timestamp shown in the strip


def test_cli_run_mode():
    r = subprocess.run(["py", "-3", "scripts/build_cot.py",
                        "output/run_2026-06-04_002"],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (ROOT / "output" / "run_2026-06-04_002" / "chain_of_thought.html").exists()


def test_build_engine_mode_writes_reasoning_path():
    out = build_cot.build(None, generated="2026-06-08 14:00")
    html = out["html"]
    assert out["qa_errors"] == []                       # engine mode passes structural QA
    assert out["path"].name == "chain_of_thought.html"
    assert "How the engine reasons" in html             # reasoning-path infographic
    assert "Feasible" in html and "Not feasible" in html  # feasibility fork
    assert "Parse the query" in html                    # a CLAUDE.md workflow step title
    assert "RULE-003" in html and "RULE-004" in html and "RULE-301" in html  # full catalogue


def test_cli_engine_mode():
    r = subprocess.run(["py", "-3", "scripts/build_cot.py"],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (ROOT / "docs" / "chain_of_thought.html").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_build_cot.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'build_cot'`.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/build_cot.py
"""Build the Chain-of-Thought report. Run mode or engine mode.

    py -3 scripts/build_cot.py output/<run_id>   # run mode
    py -3 scripts/build_cot.py                    # engine mode
"""
import sys
import pathlib
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cot_scan
import cot_examples
import cot_render
from cot_model import CotModel

ROOT = pathlib.Path(__file__).resolve().parents[1]


def build(run_dir=None, generated=None):
    generated = generated or datetime.now().strftime("%Y-%m-%d %H:%M")
    rules = cot_scan.parse_rules(ROOT / "semantic")
    workflow = cot_scan.parse_workflow(ROOT / "CLAUDE.md")
    rels = cot_scan.parse_relationships(ROOT / "metadata" / "relationships.yaml")
    status = cot_scan.schema_status(ROOT)
    known = {r.id for r in rules}

    run = examples = governing = None
    if run_dir:
        run = cot_scan.load_run(run_dir)
        governing = cot_scan.governing_rule_ids(run, known)
        source = {"result_df": run.result_df, "data_dir": ROOT / "data",
                  "trace": run.trace}
        examples = {r.id: cot_examples.example_for(r, source)
                    for r in rules if r.id in governing}
        out_path = pathlib.Path(run_dir) / "chain_of_thought.html"
    else:
        governing = [r.id for r in rules]
        # engine mode: reuse the latest run's artifacts for examples if available
        latest = _latest_run()
        latest_run = cot_scan.load_run(latest) if latest else None   # load once, not twice
        source = {"result_df": latest_run.result_df if latest_run else None,
                  "data_dir": ROOT / "data",
                  "trace": latest_run.trace if latest_run else None}
        examples = {r.id: cot_examples.example_for(r, source) for r in rules}
        out_path = ROOT / "docs" / "chain_of_thought.html"

    # The audit strip lists exactly the live sources read this build (spec §3.1 / §4 #2).
    scanned = ["CLAUDE.md", "semantic/metrics.md", "semantic/filters.md",
               "semantic/context.md", "semantic/time.md", "semantic/_rule_log.csv",
               "metadata/relationships.yaml"]
    if run_dir:
        scanned += [f"{pathlib.Path(run_dir).name}/{n}" for n in
                    ("query.txt", "analysis_plan.md", "analysis_code.py",
                     "result.csv", "context.md", "takeaways.md")]

    model = CotModel(mode="run" if run_dir else "engine", generated=generated,
                     schema_status=status, rules=rules, workflow=workflow,
                     relationships=rels, run=run,
                     governing_rule_ids=governing, examples=examples, scanned=scanned)
    html = cot_render.render_html(model)
    qa = cot_render.structural_qa(html)
    out_path.write_text(html, encoding="utf-8")
    return {"html": html, "path": out_path, "qa_errors": qa}


def _latest_run():
    runs = sorted((ROOT / "output").glob("run_*"))
    runs = [r for r in runs if (r / "result.csv").exists()]
    return runs[-1] if runs else None


def main(argv):
    run_dir = argv[1] if len(argv) > 1 else None
    result = build(run_dir)
    print(f"wrote {result['path']}")
    if result["qa_errors"]:
        print("STRUCTURAL QA FAILED:")
        for e in result["qa_errors"]:
            print(f"  - {e}")
        return 1
    print("structural QA: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_build_cot.py -v`
Expected: PASS (4 passed — run mode + engine mode, each with its CLI test).
Then run the full suite: `py -3 -m pytest tests/ -v`
Expected: PASS (all tasks' tests green).

- [ ] **Step 5: Checkpoint** — tests green. *(git msg: `feat: build_cot CLI orchestrator`)*

---

### Task 10: Documentation — CLAUDE.md (§4 template + Step 9) and MEMORY.md

**Files:**
- Modify: `CLAUDE.md`
- Modify: `MEMORY.md`
- Test: `tests/test_build_cot.py` (append a docs-presence check)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_build_cot.py  (append)
def test_docs_document_cot():
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "rationale:" in claude                     # §4 template updated
    assert "Step 9" in claude and "Chain-of-Thought" in claude
    memory = (ROOT / "MEMORY.md").read_text(encoding="utf-8")
    assert "build_cot.py" in memory
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_build_cot.py::test_docs_document_cot -v`
Expected: FAIL — strings absent.

- [ ] **Step 3: Edit the docs.**

In `CLAUDE.md` §4 "Semantic rule format", add the `rationale` line so the template reads (insert between `caveats` and `provenance`):
```markdown
- caveats: <limits, precision, exceptions>
- rationale: <why this rule exists and the trade-off it accepts; powers the Chain-of-Thought report>
- provenance: seeded | auto-saved | <date> | <user> [| run_id=<id>]
```

In `CLAUDE.md`, after the Step 8 block, add:
```markdown
### Step 9 — Chain-of-Thought report (HTML reasoning ledger) — ONLY on explicit user request
Trigger: the user runs `py -3 scripts/build_cot.py [output/<run_id>]`, or asks in plain English — "build the chain-of-thought report", "make the CoT doc", "explain the reasoning for this run". Never run this stage unprompted; it is opt-in like the deck and is NOT part of the mandatory 6-file contract.
- Run mode (`output/<run_id>`): renders the five-act story (Request → Context → Plan & Rule → Code → Worked example) into `output/<run_id>/chain_of_thought.html`, with the governing business rule(s) and the computed worked example as the two heroes.
- Engine mode (no arg): renders the reasoning path + full rule catalogue into `docs/chain_of_thought.html`.
- The builder scans live files every run (CLAUDE.md, semantic/, metadata/, the run folder), so the report never drifts. All numbers are read from `result.csv` / computed via pandas — never hand-written. A missing rule `rationale` shows a "⚠ why pending" badge. Builder details + spec: `docs/superpowers/specs/2026-06-08-chain-of-thought-documentation-design.md`.
- QA: the build runs a structural pass (balanced tags, required sections, numeric reconciliation). If LibreOffice/a browser is unavailable (per MEMORY.md), that structural pass is the QA; note the visual render could not run.
```

In `MEMORY.md`, under "Pipeline output → slides", add a new bullet:
```markdown
## Chain-of-Thought report (opt-in HTML)
- **`py -3 scripts/build_cot.py [output/<run_id>]`** renders a DataZymes-coloured HTML reasoning report. Run mode → `output/<run_id>/chain_of_thought.html` (five-act story: Request→Context→Plan&Rule→Code→Worked example; rule + worked example are heroes). Engine mode (no arg) → `docs/chain_of_thought.html` (reasoning path + full rule catalogue).
- Deterministic: scans `semantic/`, `metadata/`, `CLAUDE.md`, run folder each build; numbers from `result.csv` / pandas (never hand-written); rule "why" comes from a new `rationale:` field in each rule (missing → "⚠ why pending" badge). Modules: `scripts/{cot_model,cot_scan,cot_examples,cot_render}.py` + `cot_template.html`. Optional `cot_trace.json` (emitted by a run's analysis_code.py) supplies intermediates; else a reconciled recompute. Opt-in (CLAUDE.md Step 9), not in the 6-file contract.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_build_cot.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint** — tests green. *(git msg: `docs: document CoT report (CLAUDE Step 9 + MEMORY)`)*

---

### Task 11: End-to-end acceptance

**Files:** none (verification only)

- [ ] **Step 1: Full suite**

Run: `py -3 -m pytest tests/ -v`
Expected: ALL PASS.

- [ ] **Step 2: Generate run-mode report and eyeball it**

Run: `py -3 scripts/build_cot.py output/run_2026-06-04_002`
Expected: `wrote ...chain_of_thought.html` + `structural QA: PASS`.
Open `output/run_2026-06-04_002/chain_of_thought.html` in a browser. Confirm against the spec §8 acceptance: heroes present (rule + worked example), UC 3,121 / CD 3,905 / total 7,026 shown and reconciling, all three rules present, no "why pending" badge, DataZymes footer, ▶ spine visible.

- [ ] **Step 3: Generate engine-mode report**

Run: `py -3 scripts/build_cot.py`
Expected: `wrote ...docs/chain_of_thought.html` + `structural QA: PASS` (exit 0). Confirm the engine **reasoning path** renders — the "How the engine reasons" heading, the workflow steps parsed from CLAUDE.md, and the Feasible / With assumptions / Not feasible fork — alongside the full rule catalogue (RULE-003/004/301 with rationale). (Now also asserted by `test_build_engine_mode_writes_reasoning_path` / `test_cli_engine_mode`.)

- [ ] **Step 4: Self-update proof**

Temporarily append a dummy `## RULE-999: scratch` block (with a `rationale:`) to `semantic/filters.md`, re-run `py -3 scripts/build_cot.py`, confirm RULE-999 appears in the catalogue, then remove it and re-run to confirm it disappears — no code edits needed.

- [ ] **Step 5: Accessibility acceptance (spec §4 / §8)** — stdlib only, no new deps. Confirm the two a11y guarantees against the just-built `output/run_2026-06-04_002/chain_of_thought.html`:
  1. **Amber as fill only, never as text** on the ivory paper. Run: `py -3 -c "import re,pathlib; h=pathlib.Path('output/run_2026-06-04_002/chain_of_thought.html').read_text(encoding='utf-8'); print('amber-as-text:', re.findall(r'color\s*:\s*#?FFC000', h, re.I))"` and confirm the printed list is empty (FFC000 must appear only as `background`/fill with dark text on top).
  2. **No colour-only meaning:** eyeball that every infographic carries its numeric equivalent — worked-example step values rendered as text (e.g. `UC 0.4442 · CD 0.5558`), the reconciliation line `3,121 + 3,905 = 7,026`, and the pipeline/catalogue labels — and spot-check that navy/ink-on-ivory body text meets WCAG AA contrast.

- [ ] **Step 6: Checkpoint** — acceptance complete. *(git msg: `test: CoT report end-to-end acceptance`)*

---

## Self-Review (plan author + multi-agent audit pass, 2026-06-08)

**Spec coverage:** §1 purpose → Tasks 7–9. §3.1 scan + the "scanned →" audit strip → Tasks 2–3 (scan) and `_scan_strip` / `CotModel.scanned` (Tasks 1, 8, 9). §3.2 rationale → Tasks 1, 4, 10. §3.3 + §3.3.1 example precedence/trace → Tasks 5–6 (finals rounded to whole TRx, matching the trace contract; reconciliation asserted). §3.4 modes → Task 9 — run **and** engine, both tested (`test_build_engine_mode_writes_reasoning_path` / `test_cli_engine_mode`). §3.5 verifiable status (no "in sync") → `schema_status` Task 3, rendered Task 8. §4 design/sections → Tasks 7–8: **all ten run-mode sections** emitted (hero, scanned strip, run-pipeline infographic, §01 Request, §02 Context, §03 Plan & rules, §04 Code panel with ❶❷❸ markers, §05 Worked-example hero, rule catalogue, footer) plus the **engine reasoning-path** infographic; a11y (amber-as-fill check + numeric equivalents) → Task 11 Step 5. §5 decisions → reflected throughout. §6 surface → all files present. §7 trigger → Task 10 Step 9. §8 validation → mode-aware `structural_qa` (balanced tags, required section anchors, non-empty hero) Task 8 + Task 11 acceptance + reconciliation in Task 5. §9 deferred (PDF, embed-fonts, non-004 recompute) → correctly out of scope.

**Placeholder scan:** No "TBD/TODO/handle edge cases". Every code step shows complete, correct code — no deliberately-wrong lines remain (the former Task 8 stub is gone; its per-step annotation is now guarded by `assert "0.4442" in html`).

**Type consistency:** `example_for(rule, source)` signature consistent across Tasks 5/8/9. `Example`/`ExampleStep`/`Rule`/`CotModel` field names match Task 1 everywhere (including the new `CotModel.scanned`). `render_html(model)` and `structural_qa(html)` names consistent Tasks 8–9. `build(run_dir, generated)` return dict keys (`html`, `path`, `qa_errors`) consistent Task 9 ↔ tests. Trace `code_line` ints (95/108/118 in Task 6) are illustrative anchors for the run's own file and are not asserted by tests.

**Cross-task test lifecycle (the trap the audit closed):** the Task 2 "rationale absent → None" test parses a *synthetic* rule (not live RULE-301), so Task 4 adding rationale to the three real rules does not break it; `test_parse_workflow_steps` asserts the 1–8 prefix + ascending order, so Task 10 adding `### Step 9` to CLAUDE.md does not break it. Both stay green through the full-suite runs at Task 9 Step 4 and Task 11 Step 1. The recompute test asserts the integers the impl actually returns (3121 / 3905), and the worked example renders as its own §05 section guarded by structural QA so it cannot be silently dropped.

"""
Metadata proposer. Two backends:

  - heuristic: fast, free, no LLM. Output looks like the old "AUTO-GENERATED"
    placeholders but with a bit more structure.
  - claude_cli:  spawns `claude -p ...` non-interactive (Claude Code CLI).
    Sends a JSON profile + brief context, gets back a YAML proposal.
  - anthropic_api: stub for later; requires ANTHROPIC_API_KEY.

Output shape (a dict ready to dump as YAML):
  table, fqn, source, description, grain, known_issues, columns: [...]
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


# --------------------------------------------------------------------------- #
# heuristic                                                                    #
# --------------------------------------------------------------------------- #
_ROLLUP_PAT = re.compile(r"\b(total|all|market|grand)\b", re.I)


def _yaml_type(dtype: str) -> str:
    d = dtype.lower()
    if "int" in d:
        return "integer"
    if "float" in d:
        return "float"
    if "date" in d or "time" in d:
        return "date"
    return "string"


def propose_heuristic(table: str, fqn: str, profile: dict[str, Any],
                      source: dict[str, Any]) -> dict[str, Any]:
    cols = []
    for c in profile["columns"]:
        cols.append({
            "name": c["name"],
            "type": _yaml_type(c["dtype"]),
            "description": (
                f"{c['role_guess']} -- dtype {c['dtype']}, "
                f"{c['distinct_count']:,} distinct, {c['null_pct']}% null."
            ),
            "role_guess": c["role_guess"],
            "synonyms": [],
            "sample_values": list(c["sample"])[:5],
        })
    issues = []
    for c in profile["columns"]:
        if c["role_guess"] in {"dimension", "key"}:
            for val in c["top_values"]:
                if isinstance(val, str) and _ROLLUP_PAT.search(val):
                    issues.append(
                        f"'{c['name']}' contains rollup-like values "
                        f"(e.g. '{val}') -- verify whether to exclude when aggregating."
                    )
                    break
    return {
        "table": table,
        "fqn": fqn,
        "source": source,
        "description": (
            f"AUTO-GENERATED (heuristic). Replace with a one-sentence business "
            f"description of what {table} represents."
        ),
        "grain": "AUTO-GUESS PENDING. Confirm the natural primary-key combination.",
        "row_count_at_onboard": profile["row_count"],
        "onboarded_at": datetime.now(timezone.utc).isoformat(),
        "known_issues": issues or ["(none auto-detected -- confirm with user)"],
        "columns": cols,
    }


# --------------------------------------------------------------------------- #
# claude CLI (Claude Code, headless `-p`)                                      #
# --------------------------------------------------------------------------- #
_PROMPT_TEMPLATE = """\
You are profiling a dataset for an analytics engine. Read the JSON profile below
and propose a metadata dictionary. Output ONLY valid YAML, no prose, no fences.

Required top-level keys:
  table: <string>
  fqn: <string>
  description: <one-sentence business description of what this table represents>
  grain: <one row per ...>
  known_issues:
    - <issues you suspect from the profile: rollup rows, nulls-as-zero, biosimilar traps, etc>
  columns:
    - name: <as in profile>
      type: string | integer | float | date
      description: <one short sentence of what this column represents>
      role: key | dimension | metric | date | flag
      synonyms: [<alt names a user might say>]
      caveats: <only if non-obvious>

Rules:
  - Be domain-specific: this is pharma TRx / patient-claims data.
  - Synonyms only when likely (e.g. "PRODUCT": ["brand","drug"]). Empty list OK.
  - For *_CD / *_ID columns, note the coding system if recognisable (NDC, ICD, NPI).
  - For date columns, capture format/granularity if visible (yyyymm vs yyyy-mm-dd).
  - Don't invent business rules; only flag what the profile evidences.
  - Skip top_values that are clearly noise.

Profile JSON:
{profile_json}

Source context:
  table: {table}
  fqn: {fqn}
  source: {source_json}

Now emit the YAML.
"""


def _claude_cli_available() -> bool:
    return shutil.which("claude") is not None


def propose_via_claude_cli(table: str, fqn: str, profile: dict[str, Any],
                           source: dict[str, Any], timeout: int = 240,
                           model: str | None = None) -> dict[str, Any]:
    """Call `claude -p` headless; expect YAML on stdout."""
    claude_path = shutil.which("claude")
    if not claude_path:
        raise RuntimeError("`claude` CLI not on PATH. Install Claude Code or use heuristic backend.")
    # Profile can be big -- trim columns' top_values to keep prompt manageable.
    slim = json.loads(json.dumps(profile, default=str))
    for c in slim["columns"]:
        if isinstance(c.get("top_values"), dict):
            c["top_values"] = dict(list(c["top_values"].items())[:5])
        if isinstance(c.get("sample"), list):
            c["sample"] = c["sample"][:5]
    prompt = _PROMPT_TEMPLATE.format(
        profile_json=json.dumps(slim, default=str, indent=2),
        table=table,
        fqn=fqn,
        source_json=json.dumps(source),
    )
    cmd = [claude_path, "-p", "--output-format", "text"]
    if model:
        cmd += ["--model", model]
    # Pipe the prompt over stdin to avoid Windows cmd-line escaping landmines.
    proc = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace",
        shell=(sys.platform == "win32"),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI failed (rc={proc.returncode}): {proc.stderr[:400]}")
    yaml_text = _strip_fences(proc.stdout)
    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise RuntimeError(f"claude CLI returned invalid YAML: {exc}\n--- raw ---\n{yaml_text[:1200]}")
    if not isinstance(parsed, dict) or "columns" not in parsed:
        raise RuntimeError(f"claude CLI returned unexpected shape: {str(parsed)[:400]}")
    # Stamp in the bits we know for sure
    parsed["table"] = table
    parsed["fqn"] = fqn
    parsed["source"] = source
    parsed["row_count_at_onboard"] = profile["row_count"]
    parsed["onboarded_at"] = datetime.now(timezone.utc).isoformat()
    return parsed


def _strip_fences(text: str) -> str:
    """Some CLI outputs come wrapped in ```yaml ... ``` even when asked not to."""
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        # drop first fence
        lines = lines[1:]
        # drop last fence if present
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines)
    return t


# --------------------------------------------------------------------------- #
# anthropic_api stub                                                           #
# --------------------------------------------------------------------------- #
def propose_via_anthropic_api(*args, **kwargs) -> dict[str, Any]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY not set. Use claude_cli or heuristic instead.")
    raise NotImplementedError("anthropic_api backend not wired yet -- use claude_cli for now.")


# --------------------------------------------------------------------------- #
# dispatch                                                                     #
# --------------------------------------------------------------------------- #
def propose(table: str, fqn: str, profile: dict[str, Any], source: dict[str, Any],
            backend: str = "claude_cli") -> dict[str, Any]:
    if backend == "heuristic":
        return propose_heuristic(table, fqn, profile, source)
    if backend == "claude_cli":
        try:
            return propose_via_claude_cli(table, fqn, profile, source)
        except Exception as exc:
            print(f"[warn] claude CLI failed, falling back to heuristic: {exc}", file=sys.stderr)
            return propose_heuristic(table, fqn, profile, source)
    if backend == "anthropic_api":
        return propose_via_anthropic_api(table, fqn, profile, source)
    raise ValueError(f"Unknown proposer backend {backend!r}")

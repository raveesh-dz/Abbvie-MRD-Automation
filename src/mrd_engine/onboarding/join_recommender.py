"""
Join recommender v2. Combines three heuristics + optional LLM rationale.

Heuristics:
  - name match: exact (case-insensitive) or strong substring
  - value overlap: Jaccard on stringified distincts (sample-capped)
  - cardinality: detects 1:1 / 1:N / N:1 / N:M by uniqueness on each side

Output: ranked candidates with explain strings. Writes to /metadata/relationships.yaml
when the user accepts via accept_candidates().
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


@dataclass
class JoinCandidate:
    left_table: str
    left_col: str
    right_table: str
    right_col: str
    name_match: str            # "exact" | "substring"
    jaccard: float
    overlap_pct_of_smaller: float
    left_distinct: int
    right_distinct: int
    left_unique: bool          # column is fully unique on left
    right_unique: bool
    cardinality: str           # "one_to_one" | "one_to_many" | "many_to_one" | "many_to_many"
    sample_overlap: list[str] = field(default_factory=list)
    rationale: str = ""        # LLM-written one-liner (optional)

    @property
    def score(self) -> float:
        s = 0.5 * (2.0 if self.name_match == "exact" else 1.0)
        s += 1.0 * self.overlap_pct_of_smaller
        s += 0.5 * self.jaccard
        # prefer fk-like (one_to_many / many_to_one) over many_to_many
        if self.cardinality in {"one_to_many", "many_to_one", "one_to_one"}:
            s += 0.3
        return round(s, 4)


def _string_set(s: pd.Series, cap: int = 10_000) -> set[str]:
    return set(s.dropna().astype(str).str.upper().unique()[:cap])


def _cardinality(left_unique: bool, right_unique: bool) -> str:
    if left_unique and right_unique:
        return "one_to_one"
    if left_unique and not right_unique:
        return "one_to_many"
    if right_unique and not left_unique:
        return "many_to_one"
    return "many_to_many"


def discover(tables: dict[str, pd.DataFrame],
             min_jaccard: float = 0.02,
             min_overlap: float = 0.1) -> list[JoinCandidate]:
    candidates: list[JoinCandidate] = []
    names = list(tables.keys())
    for i, lname in enumerate(names):
        for rname in names[i + 1:]:
            l, r = tables[lname], tables[rname]
            for lc in l.columns:
                for rc in r.columns:
                    name_eq = lc.lower() == rc.lower()
                    name_sub = (
                        (lc.lower() in rc.lower() or rc.lower() in lc.lower())
                        and min(len(lc), len(rc)) >= 4
                    )
                    if not (name_eq or name_sub):
                        continue
                    lset = _string_set(l[lc])
                    rset = _string_set(r[rc])
                    if not lset or not rset:
                        continue
                    inter = lset & rset
                    if not inter:
                        continue
                    jacc = len(inter) / max(len(lset | rset), 1)
                    overlap = len(inter) / max(min(len(lset), len(rset)), 1)
                    if jacc < min_jaccard and overlap < min_overlap:
                        continue
                    l_unique = l[lc].is_unique
                    r_unique = r[rc].is_unique
                    candidates.append(JoinCandidate(
                        left_table=lname, left_col=lc,
                        right_table=rname, right_col=rc,
                        name_match="exact" if name_eq else "substring",
                        jaccard=round(jacc, 4),
                        overlap_pct_of_smaller=round(overlap, 4),
                        left_distinct=len(lset),
                        right_distinct=len(rset),
                        left_unique=bool(l_unique),
                        right_unique=bool(r_unique),
                        cardinality=_cardinality(bool(l_unique), bool(r_unique)),
                        sample_overlap=list(inter)[:5],
                    ))
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


# --------------------------------------------------------------------------- #
# LLM rationale (claude CLI)                                                   #
# --------------------------------------------------------------------------- #
def add_rationales(candidates: list[JoinCandidate], context: dict[str, str] | None = None,
                   timeout: int = 120) -> None:
    claude_path = shutil.which("claude")
    if claude_path is None or not candidates:
        return
    pack = [{
        "id": i, "left": f"{c.left_table}.{c.left_col}",
        "right": f"{c.right_table}.{c.right_col}",
        "name_match": c.name_match, "jaccard": c.jaccard,
        "overlap_pct": c.overlap_pct_of_smaller,
        "cardinality": c.cardinality,
        "sample_overlap": c.sample_overlap,
    } for i, c in enumerate(candidates[:10])]
    prompt = (
        "For each candidate join below, write a 1-sentence rationale (<=140 chars) "
        "explaining what the join is likely doing in plain English. Output JSON: "
        '{"rationales": [{"id":0,"text":"..."}]} only. Context: pharma TRx / claims '
        "data with brand-aggregated and patient-claim levels.\n\nCANDIDATES:\n"
        + json.dumps(pack, indent=2)
    )
    proc = subprocess.run(
        [claude_path, "-p", "--output-format", "text"],
        input=prompt, capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace",
        shell=(sys.platform == "win32"),
    )
    if proc.returncode != 0:
        return
    try:
        txt = proc.stdout.strip()
        if txt.startswith("```"):
            lines = txt.splitlines()[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            txt = "\n".join(lines)
        data = json.loads(txt)
        for r in data.get("rationales", []):
            i = r.get("id")
            if isinstance(i, int) and 0 <= i < len(candidates):
                candidates[i].rationale = r.get("text", "")
    except (json.JSONDecodeError, KeyError, TypeError):
        pass


# --------------------------------------------------------------------------- #
# writeback to relationships.yaml                                              #
# --------------------------------------------------------------------------- #
def accept_candidates(candidates: list[JoinCandidate], relationships_path: Path) -> int:
    """Append accepted candidates to relationships.yaml. Idempotent."""
    existing = {}
    if relationships_path.exists():
        existing = yaml.safe_load(relationships_path.read_text(encoding="utf-8")) or {}
    rels: list[dict[str, Any]] = list(existing.get("relationships", []))
    keyset = {(r.get("left"), r.get("right"), r.get("type")) for r in rels}
    written = 0
    for c in candidates:
        left = f"{c.left_table}.{c.left_col}"
        right = f"{c.right_table}.{c.right_col}"
        if (left, right, c.cardinality) in keyset:
            continue
        rels.append({
            "left": left,
            "right": right,
            "type": c.cardinality,
            "notes": (
                f"auto-discovered. name_match={c.name_match}, "
                f"jaccard={c.jaccard}, overlap={c.overlap_pct_of_smaller}. "
                + (c.rationale or "")
            ).strip(),
        })
        written += 1
    relationships_path.parent.mkdir(parents=True, exist_ok=True)
    relationships_path.write_text(
        yaml.safe_dump({"relationships": rels}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return written


def to_jsonable(candidates: list[JoinCandidate]) -> list[dict[str, Any]]:
    return [asdict(c) | {"score": c.score} for c in candidates]

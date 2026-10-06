"""
Stage 4 — let the user define custom join edges discovery missed.

Simple Q&A form. Composite keys NOT supported here (note this and direct user to
hand-edit relationships.yaml for complex edges).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from mrd_engine.onboarding.join_recommender import JoinCandidate, accept_candidates
from mrd_engine.wizard import prompts, scan, state as state_mod
from mrd_engine.wizard.state import WizardState


_CARDINALITIES = ["one_to_one", "one_to_many", "many_to_one", "many_to_many"]


def _list_tables_and_columns(repo: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for ymf in (repo / "metadata").glob("*.yaml"):
        if ymf.name in {"relationships.yaml", "_TEMPLATE.yaml"}:
            continue
        d = yaml.safe_load(ymf.read_text(encoding="utf-8")) or {}
        tname = d.get("table") or ymf.stem
        out[tname] = [c["name"] for c in d.get("columns", []) if "name" in c]
    return out


def run(repo: Path, state: WizardState) -> str:
    prompts.rule("Stage 4 — manual edges (optional)")
    state.stage = "s4_manual_edges"

    if not prompts.yesno("define any custom joins discovery missed?", default=False):
        return "s5_validate"

    tables = _list_tables_and_columns(repo)
    if len(tables) < 2:
        prompts.warn("need at least 2 onboarded tables.")
        return "s5_validate"

    while True:
        prompts.info(f"available tables: {sorted(tables)}")
        prompts.info("composite/multi-column keys not supported here — "
                     "hand-edit relationships.yaml afterwards if needed.")
        l_tbl = prompts.choice("left table", sorted(tables))
        l_col = prompts.choice(f"left column ({l_tbl})", tables[l_tbl])
        r_tbl = prompts.choice("right table", sorted(tables))
        r_col = prompts.choice(f"right column ({r_tbl})", tables[r_tbl])
        card = prompts.choice("cardinality", _CARDINALITIES, default="many_to_one")
        notes = prompts.text("notes (free text, optional)", default="manual", allow_empty=True)

        edge = JoinCandidate(
            left_table=l_tbl, left_col=l_col,
            right_table=r_tbl, right_col=r_col,
            name_match="manual",
            jaccard=0.0, overlap_pct_of_smaller=0.0,
            left_distinct=0, right_distinct=0,
            left_unique=False, right_unique=False,
            cardinality=card,
            sample_overlap=[],
            rationale=notes,
        )
        prompts.render_yaml(
            yaml.safe_dump([{
                "left": f"{l_tbl}.{l_col}",
                "right": f"{r_tbl}.{r_col}",
                "type": card,
                "notes": f"manual. {notes}",
            }], sort_keys=False),
            title="edge to append",
        )
        if prompts.yesno("append to relationships.yaml?", default=True):
            n = accept_candidates([edge], repo / "metadata" / "relationships.yaml")
            prompts.ok(f"appended {n} edge")
            state.manual_edges.append({
                "left": f"{l_tbl}.{l_col}", "right": f"{r_tbl}.{r_col}",
                "type": card, "notes": notes,
            })
            state.accepted_edges.append((f"{l_tbl}.{l_col}", f"{r_tbl}.{r_col}", card))
            state_mod.save(repo, state)
        if not prompts.yesno("add another manual edge?", default=False):
            break

    return "s5_validate"

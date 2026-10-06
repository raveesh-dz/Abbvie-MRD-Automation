"""
Stage 3 — join discovery + cherry-pick. Uses sampled mode for big tables.
Writes a backup of relationships.yaml before any modification.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml
from rich.console import Console
from rich.table import Table

from mrd_engine.loader import load
from mrd_engine.onboarding.join_recommender import (
    JoinCandidate, accept_candidates, add_rationales, discover, to_jsonable,
)
from mrd_engine.wizard import prompts, scan, state as state_mod
from mrd_engine.wizard.state import WizardState

console = Console()
SAMPLE_ROWS = 100_000   # cap per table for discovery to keep memory bounded


def _load_sampled(table: str, max_rows: int = SAMPLE_ROWS) -> pd.DataFrame:
    df = load(table)
    if len(df) > max_rows:
        return df.sample(n=max_rows, random_state=42).reset_index(drop=True)
    return df


def _backup_relationships(repo: Path) -> Path | None:
    rel = repo / "metadata" / "relationships.yaml"
    if not rel.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = rel.with_name(f"relationships.yaml.{ts}.bak")
    shutil.copy2(rel, bak)
    return bak


def _render_candidates(cands: list[JoinCandidate]) -> None:
    tbl = Table(title="Candidate joins (ranked)", header_style="bold cyan")
    for c in ("#", "left", "right", "match", "card", "jacc", "ovl%", "score", "rationale"):
        tbl.add_column(c)
    for i, c in enumerate(cands):
        rat = (c.rationale[:80] + ("..." if len(c.rationale) > 80 else "")) if c.rationale else ""
        tbl.add_row(
            str(i),
            f"{c.left_table}.{c.left_col}",
            f"{c.right_table}.{c.right_col}",
            c.name_match, c.cardinality,
            f"{c.jaccard:.3f}",
            f"{c.overlap_pct_of_smaller*100:.1f}",
            f"{c.score:.3f}",
            rat,
        )
    console.print(tbl)


def _detail(cands: list[JoinCandidate], idx: int) -> None:
    c = cands[idx]
    console.print(f"\n[bold]candidate #{idx}[/bold]")
    console.print(f"  left           : {c.left_table}.{c.left_col} (distinct={c.left_distinct})")
    console.print(f"  right          : {c.right_table}.{c.right_col} (distinct={c.right_distinct})")
    console.print(f"  name match     : {c.name_match}")
    console.print(f"  cardinality    : {c.cardinality}")
    console.print(f"  jaccard        : {c.jaccard}")
    console.print(f"  overlap-of-min : {c.overlap_pct_of_smaller}")
    console.print(f"  sample overlap : {c.sample_overlap}")
    console.print(f"  rationale      : {c.rationale or '(none)'}")


def run(repo: Path, state: WizardState, *, no_rationales: bool = False) -> str:
    prompts.rule("Stage 3 — discover joins")
    state.stage = "s3_joins"

    inv = scan.classify(repo)
    tables = scan.usable_tables(inv)
    if len(tables) < 2:
        prompts.warn("need at least 2 onboarded tables to discover joins.")
        return "s5_validate"

    if not prompts.yesno(f"discover joins across {len(tables)} table(s): {tables}?",
                         default=True):
        return "s4_manual_edges"

    prompts.info(f"loading sampled data (cap {SAMPLE_ROWS:,} rows per table)...")
    dfs: dict[str, pd.DataFrame] = {}
    for t in tables:
        try:
            dfs[t] = _load_sampled(t)
            prompts.ok(f"  {t}: {dfs[t].shape}")
        except Exception as exc:
            prompts.err(f"  {t}: {exc}")

    prompts.info("scoring candidates...")
    cands = discover(dfs)
    prompts.ok(f"{len(cands)} candidate(s)")
    if not cands:
        return "s4_manual_edges"

    if not no_rationales and prompts.yesno("ask claude CLI for one-line rationales?",
                                            default=True):
        add_rationales(cands)

    _render_candidates(cands)

    # cherry-pick loop
    while True:
        raw = prompts.text(
            "pick indices [e.g. '0 2 4'], 'all', 'none', 'detail <n>', or 'done'",
            default="none",
        ).strip().lower()
        if raw in {"", "none", "done", "skip"}:
            break
        if raw.startswith("detail "):
            try:
                _detail(cands, int(raw.split()[1]))
            except (ValueError, IndexError):
                prompts.warn("usage: detail <index>")
            continue
        picks = _parse_picks(raw, len(cands))
        if not picks:
            prompts.warn("nothing picked.")
            continue
        chosen = [cands[i] for i in picks]
        bak = _backup_relationships(repo)
        if bak:
            prompts.info(f"backup -> {bak.relative_to(repo)}")
        n = accept_candidates(chosen, repo / "metadata" / "relationships.yaml")
        prompts.ok(f"appended {n} edge(s) to relationships.yaml")
        for c in chosen:
            state.accepted_edges.append((f"{c.left_table}.{c.left_col}",
                                         f"{c.right_table}.{c.right_col}",
                                         c.cardinality))
        rejected_idxs = [i for i in range(len(cands)) if i not in picks]
        for i in rejected_idxs:
            c = cands[i]
            state.rejected_edges.append((f"{c.left_table}.{c.left_col}",
                                         f"{c.right_table}.{c.right_col}",
                                         c.cardinality))
        state_mod.save(repo, state)
        break

    return "s4_manual_edges"


def _parse_picks(raw: str, max_index: int) -> list[int]:
    picked: set[int] = set()
    if raw in {"all", "accept-all"}:
        return list(range(max_index))
    for chunk in raw.replace(",", " ").split():
        if "-" in chunk:
            try:
                lo, hi = chunk.split("-", 1)
                for i in range(int(lo), int(hi) + 1):
                    if 0 <= i < max_index:
                        picked.add(i)
            except ValueError:
                continue
        else:
            try:
                i = int(chunk)
                if 0 <= i < max_index:
                    picked.add(i)
            except ValueError:
                continue
    return sorted(picked)

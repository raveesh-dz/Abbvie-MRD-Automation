"""
Stage 2 — review metadata proposals. Three modes: inline, editor, auto.

Inline mode:
  - top fields (description, grain, known_issues) walked one by one
  - columns: bulk-accept; offer "spot-check N flagged columns" rather than walking all
  - diff displayed if an existing .yaml is being overwritten
"""
from __future__ import annotations

import difflib
import random
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.syntax import Syntax

from mrd_engine.wizard import prompts, state as state_mod
from mrd_engine.wizard.state import WizardState

console = Console()


def _load_or_none(p: Path) -> dict[str, Any] | None:
    if not p.exists():
        return None
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _show_full_preview(doc: dict[str, Any]) -> None:
    """Render the full proposed YAML for at-a-glance review (capped to 80 lines)."""
    text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    lines = text.splitlines()
    if len(lines) > 80:
        text = "\n".join(lines[:80]) + f"\n... ({len(lines) - 80} more lines)"
    prompts.render_yaml(text, title="proposed metadata (preview)")


def _show_diff(old: dict[str, Any], new: dict[str, Any]) -> None:
    a = yaml.safe_dump(old, sort_keys=False, allow_unicode=True).splitlines()
    b = yaml.safe_dump(new, sort_keys=False, allow_unicode=True).splitlines()
    diff = list(difflib.unified_diff(a, b, fromfile="existing.yaml",
                                     tofile="proposed.yaml", n=2))
    if not diff:
        prompts.info("no differences vs existing dict.")
        return
    prompts.render_yaml("\n".join(diff[:200]), title="diff (existing -> proposed)")


def _review_top_fields(proposed: dict[str, Any]) -> dict[str, Any]:
    for field in ("description", "grain", "known_issues"):
        v = proposed.get(field)
        console.print(f"\n[bold]{field}[/bold]: {yaml.safe_dump({field: v}).rstrip()}")
        ans = prompts.choice(f"{field}: (a)ccept / (e)dit / (s)kip",
                             options=["a", "e", "s"], default="a")
        if ans == "e":
            new_val = prompts.text(f"new {field} (YAML scalar / JSON; empty = keep)",
                                   allow_empty=True)
            if new_val.strip():
                try:
                    proposed[field] = yaml.safe_load(new_val)
                except yaml.YAMLError as exc:
                    prompts.warn(f"bad YAML, keeping: {exc}")
    return proposed


def _flagged_columns(cols: list[dict]) -> list[dict]:
    """Columns worth spot-checking: ambiguous role, caveats present, all-null, all-distinct."""
    flagged = []
    for c in cols:
        reasons = []
        if c.get("caveats"):
            reasons.append("has caveats")
        if c.get("role_guess") == "?" or c.get("role") == "?":
            reasons.append("role unknown")
        if c.get("null_pct", 0) and float(c["null_pct"]) > 50:
            reasons.append(f"{c['null_pct']}% null")
        if reasons:
            c2 = dict(c)
            c2["_flagged"] = ", ".join(reasons)
            flagged.append(c2)
    return flagged


def _spot_check_columns(proposed: dict[str, Any]) -> None:
    cols = proposed.get("columns", [])
    flagged = _flagged_columns(cols)
    n_total = len(cols)
    console.print(f"\ncolumns: {n_total} total, {len(flagged)} flagged")
    if not flagged:
        if n_total > 30 and prompts.yesno(
                f"spot-check {min(5, n_total)} random columns instead?", default=False):
            sample = random.sample(cols, min(5, n_total))
            for c in sample:
                prompts.render_yaml(yaml.safe_dump([c], sort_keys=False), title=c["name"])
        return
    if prompts.yesno(f"review the {len(flagged)} flagged column(s)?", default=True):
        for c in flagged[:20]:   # cap
            prompts.render_yaml(yaml.safe_dump([c], sort_keys=False), title=c["name"])


def _review_one(repo: Path, table: str, *, mode: str) -> bool:
    proposed_path = repo / "metadata" / f"{table}.yaml.proposed"
    target_path = repo / "metadata" / f"{table}.yaml"
    proposed = _load_or_none(proposed_path)
    if proposed is None:
        prompts.err(f"missing {proposed_path}")
        return False
    existing = _load_or_none(target_path)

    prompts.rule(f"review: {table}  (mode={mode})")

    if mode == "auto":
        target_path.write_text(
            yaml.safe_dump(proposed, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        prompts.ok(f"auto-accepted -> {target_path.relative_to(repo)}")
        return True

    if mode == "editor":
        prompts.open_in_editor(proposed_path)
        # reload after editor save
        proposed = _load_or_none(proposed_path) or proposed
        if existing:
            _show_diff(existing, proposed)
        if not prompts.yesno("promote edited file?", default=True):
            return False
        target_path.write_text(
            yaml.safe_dump(proposed, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        prompts.ok(f"promoted -> {target_path.relative_to(repo)}")
        return True

    # inline (default)
    _show_full_preview(proposed)
    if existing:
        _show_diff(existing, proposed)
        if not prompts.yesno("an existing .yaml differs — proceed with review?", default=True):
            return False
    proposed = _review_top_fields(proposed)
    _spot_check_columns(proposed)

    if prompts.yesno("promote to <table>.yaml?", default=True):
        target_path.write_text(
            yaml.safe_dump(proposed, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        prompts.ok(f"promoted -> {target_path.relative_to(repo)}")
        return True
    prompts.warn("review aborted — proposal left intact.")
    return False


def run(repo: Path, state: WizardState, *, mode: str = "inline") -> str:
    prompts.rule("Stage 2 — review proposed metadata")
    state.stage = "s2_review"
    pending = list(state.pending_review)
    if not pending:
        prompts.info("no tables awaiting review.")
        return "s3_joins"
    for table in pending:
        if _review_one(repo, table, mode=mode):
            state.reviewed_this_session.append(table)
            state.pending_review.remove(table)
            state_mod.save(repo, state)
        else:
            prompts.warn(f"left {table} as .yaml.proposed for later review.")
    return "s3_joins"

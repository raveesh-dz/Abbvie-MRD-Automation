"""
Final session log + summary renderer. Writes output/setup_<timestamp>.log on completion.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from mrd_engine.wizard.state import WizardState

console = Console()


def render_session(state: WizardState, repo: Path) -> str:
    """Build a plain-text session summary."""
    lines = []
    lines.append(f"mrd init session log")
    lines.append(f"=" * 60)
    lines.append(f"started   : {state.started_at}")
    lines.append(f"completed : {state.completed_at or '(in progress)'}")
    lines.append(f"final stage: {state.stage}")
    lines.append("")
    lines.append(f"Onboarded this session ({len(state.onboarded_this_session)}):")
    for t in state.onboarded_this_session:
        lines.append(f"  - {t}")
    lines.append("")
    lines.append(f"Reviewed/promoted ({len(state.reviewed_this_session)}):")
    for t in state.reviewed_this_session:
        lines.append(f"  - {t}")
    lines.append("")
    lines.append(f"Accepted joins ({len(state.accepted_edges)}):")
    for l, r, c in state.accepted_edges:
        lines.append(f"  + {l}  <->  {r}   ({c})")
    if state.rejected_edges:
        lines.append("")
        lines.append(f"Rejected joins ({len(state.rejected_edges)}):")
        for l, r, c in state.rejected_edges:
            lines.append(f"  - {l}  <->  {r}   ({c})")
    if state.manual_edges:
        lines.append("")
        lines.append(f"Manual edges added ({len(state.manual_edges)}):")
        for e in state.manual_edges:
            lines.append(f"  * {e.get('left')}  <->  {e.get('right')}   ({e.get('type')})")
    lines.append("")
    if state.validation_summary:
        lines.append("Validation:")
        for k, v in state.validation_summary.items():
            lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append(f"User choices (audit trail, {len(state.user_choices)} events):")
    for c in state.user_choices:
        lines.append(f"  [{c['at']}] {c['stage']} :: {c['key']} = {c['value']}")
    return "\n".join(lines)


def write_log(state: WizardState, repo: Path) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    out = repo / "output" / f"setup_{ts}.log"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_session(state, repo), encoding="utf-8")
    return out


def print_final_summary(state: WizardState) -> None:
    tbl = Table(title="Session summary", show_header=True, header_style="bold cyan")
    tbl.add_column("counter")
    tbl.add_column("value", justify="right")
    tbl.add_row("tables onboarded",   str(len(state.onboarded_this_session)))
    tbl.add_row("tables reviewed",    str(len(state.reviewed_this_session)))
    tbl.add_row("joins accepted",     str(len(state.accepted_edges)))
    tbl.add_row("joins rejected",     str(len(state.rejected_edges)))
    tbl.add_row("manual edges added", str(len(state.manual_edges)))
    v = state.validation_summary or {}
    tbl.add_row("validation active",  str(v.get("active", "-")))
    tbl.add_row("validation warnings",str(v.get("warnings", "-")))
    tbl.add_row("validation errors",  str(v.get("errors", "-")))
    console.print(tbl)

"""
Interactive metadata review. Diffs <table>.yaml.proposed against <table>.yaml
(if it exists) and lets the user accept/edit/reject per top-level field.

For non-interactive runs (CI / scripted), pass auto_accept=True.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.prompt import Prompt
from rich.syntax import Syntax

console = Console()


def _load(p: Path) -> dict[str, Any] | None:
    if not p.exists():
        return None
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def review(proposed_path: Path, target_path: Path, auto_accept: bool = False) -> bool:
    """Return True if a final YAML was written, False if user aborted."""
    proposed = _load(proposed_path)
    if proposed is None:
        console.print(f"[red]proposed file missing: {proposed_path}[/red]")
        return False
    existing = _load(target_path) or {}

    console.rule(f"Review {target_path.name}")
    if auto_accept:
        target_path.write_text(yaml.safe_dump(proposed, sort_keys=False, allow_unicode=True),
                               encoding="utf-8")
        console.print(f"[green]auto-accepted -> {target_path}[/green]")
        return True

    # quick column-count sanity
    nprop = len(proposed.get("columns", []))
    nexist = len(existing.get("columns", []))
    console.print(f"columns: existing={nexist}, proposed={nprop}")

    # show top fields
    top_fields = ["description", "grain", "known_issues"]
    for f in top_fields:
        console.print(f"\n[bold]{f}[/bold]")
        console.print(yaml.safe_dump({f: proposed.get(f)}, allow_unicode=True))
        ans = Prompt.ask("accept this field? [y/n/edit]", choices=["y", "n", "edit"], default="y")
        if ans == "n":
            proposed[f] = existing.get(f, proposed.get(f))
        elif ans == "edit":
            console.print("paste a single-line replacement value (YAML scalar or JSON):")
            line = input("> ").strip()
            try:
                proposed[f] = yaml.safe_load(line) if line else proposed[f]
            except yaml.YAMLError as exc:
                console.print(f"[red]bad YAML, keeping proposed: {exc}[/red]")

    # column-level review (lighter -- accept all unless user asks otherwise)
    ans = Prompt.ask("review every column individually? [y/n]", choices=["y", "n"], default="n")
    if ans == "y":
        for col in proposed.get("columns", []):
            console.print()
            console.print(Syntax(yaml.safe_dump([col], sort_keys=False), "yaml"))
            sub = Prompt.ask(
                f"keep '{col['name']}'? [y/skip]", choices=["y", "skip"], default="y"
            )
            if sub == "skip":
                col["description"] = col.get("description", "") + "  [USER MARKED FOR REVISION]"

    target_path.write_text(yaml.safe_dump(proposed, sort_keys=False, allow_unicode=True),
                           encoding="utf-8")
    console.print(f"\n[green]wrote {target_path}[/green]")
    return True

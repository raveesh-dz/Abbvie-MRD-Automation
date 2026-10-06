"""
Stage 0 — inventory existing data layer state + top-level menu.

Returns next-stage name ("s1_onboard" | "s3_joins" | "done" | "reset" | "resume").
"""
from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table

from mrd_engine.wizard import prompts, scan, state as state_mod
from mrd_engine.wizard.state import WizardState

console = Console()


def _render_inventory(inv: scan.Inventory) -> None:
    if not inv.tables and not inv.untracked_csvs and not inv.orphan_caches:
        prompts.info("data layer is empty — no dictionaries yet.")
        return
    tbl = Table(title="Data layer inventory", header_style="bold cyan")
    for c in ("status", "table", "connector", "object", "rows", "fetched", "note"):
        tbl.add_column(c)
    status_colour = {
        "READY": "green", "LEGACY": "blue", "PENDING": "yellow",
        "STALE": "magenta", "MISSING": "red", "ORPHAN": "dim",
    }
    for r in sorted(inv.tables, key=lambda x: (x.status, x.table)):
        col = status_colour.get(r.status, "white")
        tbl.add_row(
            f"[{col}]{r.status}[/{col}]",
            r.table, r.connector,
            (r.source_object or "")[:40],
            str(r.row_count) if r.row_count >= 0 else "-",
            r.fetched_at, r.note,
        )
    console.print(tbl)

    prompts.info(
        f"relationships.yaml: {inv.relationships_count} edge(s) "
        f"({inv.hand_curated_edges} hand-curated, {inv.auto_discovered_edges} auto-discovered)"
    )
    if inv.untracked_csvs:
        prompts.warn(f"untracked CSVs in /data/ (no dict): {inv.untracked_csvs}")
    if inv.orphan_caches:
        prompts.warn(f"orphan parquet caches (no dict): {inv.orphan_caches}")


def run(repo: Path, state: WizardState, *, dry_run: bool = False) -> str:
    prompts.rule("Stage 0 — inventory")
    inv = scan.classify(repo)
    _render_inventory(inv)

    has_resume = state_mod._state_path(repo).exists() and not state.completed_at
    has_pending = bool(scan.pending_tables(inv))
    has_stale = bool(scan.stale_tables(inv))
    has_data = bool(scan.usable_tables(inv))

    if has_pending:
        prompts.warn(f"pending review (will skip on 'continue'): {scan.pending_tables(inv)}")

    options = []
    if has_data:
        options.append(("1", "Continue with existing data (jump to joins / validate)"))
    options.append(("2", "Add more tables (onboard new sources)"))
    if has_pending:
        options.append(("3", "Resume pending metadata reviews"))
    if has_stale:
        options.append(("4", "Refresh stale tables (re-fetch from source)"))
    options.append(("5", "Start fresh — reset generated artifacts (DESTRUCTIVE)"))
    options.append(("q", "Quit"))

    choice = prompts.menu("What do you want to do?", options,
                          default="1" if has_data else "2")
    state.record_choice("s0_inventory", "menu", choice)
    state.stage = "s0_inventory"
    state_mod.save(repo, state)

    if choice == "q":
        return "done"
    if choice == "1":
        return "s3_joins"        # straight to joins (and validate)
    if choice == "2":
        return "s1_onboard"
    if choice == "3":
        # treat pending as the onboard-list and route through review
        state.pending_review = scan.pending_tables(inv)
        return "s2_review"
    if choice == "4":
        return "s1_onboard_refresh"
    if choice == "5":
        if _confirm_reset(repo, inv, dry_run=dry_run):
            return "s0_inventory"   # re-render after reset
        return "s0_inventory"
    return "done"


def _confirm_reset(repo: Path, inv: scan.Inventory, *, dry_run: bool) -> bool:
    targets = _reset_targets(repo, inv)
    prompts.rule("Start fresh — files that will be deleted")
    for f in targets["delete"]:
        console.print(f"  [red]delete[/red] {f}")
    for f in targets["preserve"]:
        console.print(f"  [dim]preserve[/dim] {f}")
    if not prompts.confirm_destructive(
        f"Delete {len(targets['delete'])} generated file(s)? "
        f"Legacy dicts + curated relationships are preserved.",
        magic_word="RESET",
    ):
        prompts.warn("reset aborted.")
        return False
    if dry_run:
        prompts.warn("dry-run — nothing deleted.")
        return True
    for f in targets["delete"]:
        p = repo / f
        if p.exists():
            try:
                p.unlink()
            except IsADirectoryError:
                import shutil
                shutil.rmtree(p)
    # Strip auto-discovered edges from relationships.yaml, keep hand-curated.
    _prune_auto_edges(repo)
    prompts.ok("reset complete.")
    return True


def _reset_targets(repo: Path, inv: scan.Inventory) -> dict[str, list[str]]:
    delete: list[str] = []
    preserve: list[str] = []
    cache_dir = repo / "data" / "_cache"
    if cache_dir.exists():
        for f in cache_dir.glob("*"):
            delete.append(str(f.relative_to(repo)))
    prof = repo / "profiles"
    if prof.exists():
        for f in prof.glob("*"):
            if f.is_file():
                delete.append(str(f.relative_to(repo)))
    # dicts with source block (i.e. wizard-onboarded) -> delete; legacy dicts -> preserve
    for r in inv.tables:
        ymf = repo / "metadata" / f"{r.table}.yaml"
        if not ymf.exists():
            continue
        if r.status == "LEGACY":
            preserve.append(str(ymf.relative_to(repo)))
        else:
            delete.append(str(ymf.relative_to(repo)))
    # .yaml.proposed
    for p in (repo / "metadata").glob("*.yaml.proposed"):
        delete.append(str(p.relative_to(repo)))
    preserve.append("metadata/relationships.yaml (hand-curated edges kept, auto-discovered pruned)")
    preserve.append(".env, connectors/*.yaml, semantic/*.md")
    return {"delete": sorted(delete), "preserve": sorted(set(preserve))}


def _prune_auto_edges(repo: Path) -> None:
    import yaml
    rel = repo / "metadata" / "relationships.yaml"
    if not rel.exists():
        return
    doc = yaml.safe_load(rel.read_text(encoding="utf-8")) or {}
    edges = doc.get("relationships", [])
    kept = [e for e in edges if "auto-discovered" not in (e.get("notes") or "").lower()]
    doc["relationships"] = kept
    backup = rel.with_suffix(rel.suffix + ".bak")
    backup.write_text(rel.read_text(encoding="utf-8"), encoding="utf-8")
    rel.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    prompts.ok(f"pruned auto-discovered edges. backup -> {backup.relative_to(repo)}")

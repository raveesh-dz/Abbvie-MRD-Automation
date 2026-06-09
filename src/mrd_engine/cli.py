"""
mrd -- Typer CLI for the data layer.

Subcommands:
  mrd handshake <connector>          probe a source
  mrd onboard <connector> <object>   fetch + profile + propose metadata
  mrd review <table>                 promote .yaml.proposed -> .yaml
  mrd joins recommend                discover candidate joins across cached tables
  mrd validate                       extended schema gate
  mrd load <table>                   smoke-test the loader (prints shape + dtypes)
  mrd status                         show tables + sources + cache freshness
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import typer
import yaml
from rich.console import Console
from rich.table import Table

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from mrd_engine.envloader import load_env
load_env(REPO / ".env")

from mrd_engine.connectors import get_connector
from mrd_engine.loader import load as load_table_df
from mrd_engine.metadata.reviewer import review as review_metadata
from mrd_engine.onboarding.join_recommender import (
    accept_candidates, add_rationales, discover, to_jsonable,
)
from mrd_engine.onboarding.orchestrator import onboard as orchestrate

app = typer.Typer(help="mrd -- data layer CLI", no_args_is_help=True)
joins_app = typer.Typer(help="join discovery & writeback", no_args_is_help=True)
app.add_typer(joins_app, name="joins")
console = Console()


def _load_connector_cfg(name: str) -> dict:
    p = REPO / "connectors" / f"{name}.yaml"
    if not p.exists():
        console.print(f"[red]connectors/{name}.yaml not found[/red]")
        raise typer.Exit(1)
    return yaml.safe_load(p.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
@app.command()
def handshake(connector: str = typer.Argument(..., help="connector name (e.g. snowflake_dz)")):
    """Probe a source. For Snowflake, opens SSO browser if needed."""
    cfg = _load_connector_cfg(connector)
    conn = get_connector(cfg["type"], REPO)
    info = conn.handshake()
    console.print_json(data=info)
    if hasattr(conn, "close"):
        conn.close()


# --------------------------------------------------------------------------- #
@app.command()
def onboard(
    connector: str = typer.Argument(..., help="connector name (e.g. snowflake_dz, csv_local)"),
    source_object: str = typer.Argument(..., help="DB.SCHEMA.TABLE for snowflake, filename for csv"),
    table: str = typer.Option(None, help="override the derived table name"),
    backend: str = typer.Option("claude_cli", help="claude_cli | heuristic | anthropic_api"),
    row_cap: int = typer.Option(10_000_000, help="abort if source has more rows than this"),
):
    """Fetch -> profile -> propose metadata. Writes .yaml.proposed for review."""
    result = orchestrate(REPO, connector, source_object, table_name=table,
                         backend=backend, row_cap=row_cap)
    console.print(f"\n[green]onboarded {result['table']}[/green]")
    console.print(f"  proposed metadata: {Path(result['proposed_metadata_path']).relative_to(REPO)}")
    console.print(f"  profile:           {Path(result['profile_path']).relative_to(REPO)}")
    console.print(f"  cache:             {Path(result['cache_path']).relative_to(REPO)}")
    console.print(f"\nNext: [bold]mrd review {result['table']}[/bold]")


# --------------------------------------------------------------------------- #
@app.command()
def review(
    table: str = typer.Argument(..., help="table name (matches metadata/<table>.yaml.proposed)"),
    auto_accept: bool = typer.Option(False, "--auto", help="non-interactive accept"),
):
    """Interactive review of <table>.yaml.proposed -> <table>.yaml."""
    proposed = REPO / "metadata" / f"{table}.yaml.proposed"
    target = REPO / "metadata" / f"{table}.yaml"
    ok = review_metadata(proposed, target, auto_accept=auto_accept)
    raise typer.Exit(0 if ok else 1)


# --------------------------------------------------------------------------- #
@joins_app.command("recommend")
def joins_recommend(
    tables: list[str] = typer.Option(None, "--table", "-t",
        help="restrict to specific tables (default = all in metadata/)"),
    accept_all: bool = typer.Option(False, "--accept-all",
        help="write all candidates above default threshold to relationships.yaml"),
    rationales: bool = typer.Option(True, help="ask claude CLI for one-line rationales"),
    out: str = typer.Option("profiles/join_candidates.json", help="json dump path"),
):
    """Discover candidate joins across cached tables."""
    if not tables:
        names = []
        for p in (REPO / "metadata").glob("*.yaml"):
            if p.name == "relationships.yaml" or p.name.startswith("_"):
                continue
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            tname = doc.get("table") or p.stem
            if tname and tname != "my_table_name":
                names.append(tname)
        tables = sorted(set(names))
    dfs: dict[str, pd.DataFrame] = {}
    for t in tables:
        try:
            dfs[t] = load_table_df(t)
        except FileNotFoundError as exc:
            console.print(f"[yellow]skip {t}: {exc}[/yellow]")
    console.print(f"discovering joins across {len(dfs)} table(s): {list(dfs)}")
    cands = discover(dfs)
    if rationales:
        add_rationales(cands)
    console.print(f"found {len(cands)} candidate(s)")
    tbl = Table(title="Top candidate joins")
    for col in ("left", "right", "name", "card", "jacc", "ovl%", "score", "why"):
        tbl.add_column(col)
    for c in cands[:15]:
        tbl.add_row(
            f"{c.left_table}.{c.left_col}",
            f"{c.right_table}.{c.right_col}",
            c.name_match, c.cardinality,
            f"{c.jaccard:.3f}", f"{c.overlap_pct_of_smaller*100:.1f}",
            f"{c.score:.3f}", (c.rationale[:60] + ("..." if len(c.rationale) > 60 else "")) if c.rationale else "",
        )
    console.print(tbl)

    out_path = REPO / out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(to_jsonable(cands), indent=2), encoding="utf-8")
    console.print(f"\nwrote {out_path.relative_to(REPO)}")

    if accept_all and cands:
        rel_path = REPO / "metadata" / "relationships.yaml"
        n = accept_candidates(cands, rel_path)
        console.print(f"[green]appended {n} edge(s) to {rel_path.relative_to(REPO)}[/green]")


@joins_app.command("accept")
def joins_accept(
    ids: list[int] = typer.Argument(..., help="indices into profiles/join_candidates.json"),
):
    """Accept specific candidates by index (from `mrd joins recommend` output)."""
    src = REPO / "profiles" / "join_candidates.json"
    if not src.exists():
        console.print("[red]no candidates file. Run `mrd joins recommend` first.[/red]")
        raise typer.Exit(1)
    raw = json.loads(src.read_text(encoding="utf-8"))
    from mrd_engine.onboarding.join_recommender import JoinCandidate
    cands = [JoinCandidate(**{k: v for k, v in r.items() if k != "score"}) for r in raw]
    pick = [cands[i] for i in ids if 0 <= i < len(cands)]
    rel_path = REPO / "metadata" / "relationships.yaml"
    n = accept_candidates(pick, rel_path)
    console.print(f"[green]appended {n} edge(s)[/green]")


# --------------------------------------------------------------------------- #
@app.command()
def validate():
    """Run the (extended) schema gate."""
    import subprocess
    rc = subprocess.call(["py", "-3", str(REPO / "scripts" / "validate_schema.py"),
                          "--root", str(REPO)])
    raise typer.Exit(rc)


# --------------------------------------------------------------------------- #
@app.command()
def load(table: str):
    """Load a table via the engine loader and print shape + dtypes."""
    df = load_table_df(table)
    console.print(f"[bold]{table}[/bold]  shape={df.shape}")
    console.print(df.dtypes.to_string())
    console.print(df.head(5).to_string())


# --------------------------------------------------------------------------- #
@app.command()
def status():
    """Show all tables, sources, and cache freshness."""
    tbl = Table(title="mrd data-layer status")
    for col in ("table", "connector", "object", "rows", "fetched", "cache"):
        tbl.add_column(col)
    for ymf in sorted((REPO / "metadata").glob("*.yaml")):
        if ymf.name in {"relationships.yaml", "_TEMPLATE.yaml"}:
            continue
        m = yaml.safe_load(ymf.read_text(encoding="utf-8")) or {}
        src = m.get("source", {})
        cache_p = REPO / src.get("cache_path", "") if src.get("cache_path") else None
        tbl.add_row(
            m.get("table", ymf.stem),
            src.get("connector", "?"),
            str(src.get("object", "")),
            str(src.get("row_count_at_onboard", "?")),
            str(src.get("fetched_at", "?"))[:19],
            "OK" if (cache_p and cache_p.exists()) else "missing",
        )
    console.print(tbl)


if __name__ == "__main__":
    app()

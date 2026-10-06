"""
Scan the data layer and classify each table by status. Used by Stage 0 inventory.

Classifications:
  READY    — .yaml exists, source.cache_path resolves on disk
  LEGACY   — .yaml exists with no source block, /data/<table>.csv resolves
  PENDING  — .yaml.proposed exists, .yaml missing (review never promoted)
  STALE    — .yaml exists, source.cache_path missing on disk
  MISSING  — .yaml exists, neither cache nor legacy CSV resolves
  ORPHAN   — parquet in /data/_cache/ with no matching .yaml
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class TableRow:
    table: str
    status: str
    connector: str = "?"
    source_object: str = ""
    cache_path: str | None = None
    fetched_at: str = ""
    row_count: int = -1
    note: str = ""


@dataclass
class Inventory:
    repo: Path
    tables: list[TableRow] = field(default_factory=list)
    untracked_csvs: list[str] = field(default_factory=list)   # CSVs in /data/ with no dict
    orphan_caches: list[str] = field(default_factory=list)    # parquet caches with no dict
    relationships_count: int = 0
    auto_discovered_edges: int = 0
    hand_curated_edges: int = 0


def _load_yaml(p: Path) -> dict[str, Any]:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def classify(repo: Path) -> Inventory:
    meta_dir = repo / "metadata"
    data_dir = repo / "data"
    cache_dir = data_dir / "_cache"
    inv = Inventory(repo=repo)

    seen_tables: set[str] = set()
    # 1. Inspect every dictionary YAML
    for ymf in sorted(meta_dir.glob("*.yaml")):
        if ymf.name in {"relationships.yaml", "_TEMPLATE.yaml"} or ymf.name.startswith("_"):
            continue
        m = _load_yaml(ymf)
        table = m.get("table") or ymf.stem
        seen_tables.add(table)
        src = m.get("source") or {}
        row = TableRow(
            table=table,
            status="MISSING",
            connector=src.get("connector", "?"),
            source_object=str(src.get("object", "")),
            cache_path=src.get("cache_path"),
            fetched_at=str(src.get("fetched_at", ""))[:19],
            row_count=int(src.get("row_count_at_onboard", -1) or -1),
        )
        if src.get("cache_path"):
            cp = repo / src["cache_path"]
            row.status = "READY" if cp.exists() else "STALE"
        else:
            csv = data_dir / f"{table}.csv"
            if csv.exists():
                row.status = "LEGACY"
                row.connector = "csv_legacy"
                row.source_object = str(csv.relative_to(repo))
            else:
                row.status = "MISSING"
        inv.tables.append(row)

    # 2. Inspect orphan .yaml.proposed (no .yaml yet)
    for prop in sorted(meta_dir.glob("*.yaml.proposed")):
        table = prop.stem.rsplit(".", 1)[0] if prop.stem.endswith(".yaml") else prop.stem
        # .yaml.proposed -> stem is "<table>.yaml" -> strip ".yaml"
        table = prop.name[: -len(".yaml.proposed")]
        target = meta_dir / f"{table}.yaml"
        if target.exists():
            continue
        seen_tables.add(table)
        inv.tables.append(TableRow(
            table=table,
            status="PENDING",
            connector="?",
            note="awaiting `mrd review`",
        ))

    # 3. Orphan caches
    if cache_dir.exists():
        for pq in sorted(cache_dir.glob("*.parquet")):
            tname = pq.stem
            if tname not in seen_tables:
                inv.orphan_caches.append(str(pq.relative_to(repo)))

    # 4. Untracked CSVs in /data/
    for csv in sorted(data_dir.glob("*.csv")):
        stem = csv.stem
        if stem not in seen_tables and stem.lower() != "readme":
            inv.untracked_csvs.append(str(csv.relative_to(repo)))

    # 5. relationships.yaml stats
    rel = meta_dir / "relationships.yaml"
    if rel.exists():
        rdoc = _load_yaml(rel)
        edges = rdoc.get("relationships", [])
        inv.relationships_count = len(edges)
        for e in edges:
            notes = (e.get("notes") or "").lower()
            if "auto-discovered" in notes:
                inv.auto_discovered_edges += 1
            else:
                inv.hand_curated_edges += 1

    return inv


def usable_tables(inv: Inventory) -> list[str]:
    """Tables the engine can actually load."""
    return [t.table for t in inv.tables if t.status in {"READY", "LEGACY"}]


def pending_tables(inv: Inventory) -> list[str]:
    return [t.table for t in inv.tables if t.status == "PENDING"]


def stale_tables(inv: Inventory) -> list[str]:
    return [t.table for t in inv.tables if t.status == "STALE"]

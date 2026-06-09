"""
Single load(table) helper. Resolves a table by metadata/<table>.yaml,
returns a DataFrame regardless of source. Engine code calls this instead of
direct pd.read_csv / pd.read_parquet.

Resolution order:
  1. metadata/<table>.yaml -> source block -> cache_path under data/_cache/
  2. fallback to data/<table>.csv (legacy)
  3. fallback to data/<table>.parquet
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _meta(table: str) -> dict | None:
    p = _repo_root() / "metadata" / f"{table}.yaml"
    if not p.exists():
        return None
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def cache_path(table: str) -> Path | None:
    """Return the local parquet path declared in metadata, or None."""
    m = _meta(table)
    if not m:
        return None
    src = m.get("source") or {}
    cp = src.get("cache_path")
    if cp:
        return _repo_root() / cp
    return None


def load(table: str) -> pd.DataFrame:
    """Load a table by name. Tries cache_path -> data/<table>.csv -> .parquet."""
    cp = cache_path(table)
    if cp and cp.exists():
        if cp.suffix == ".parquet":
            return pd.read_parquet(cp)
        return pd.read_csv(cp)
    repo = _repo_root()
    csv = repo / "data" / f"{table}.csv"
    if csv.exists():
        return pd.read_csv(csv)
    pq = repo / "data" / f"{table}.parquet"
    if pq.exists():
        return pd.read_parquet(pq)
    raise FileNotFoundError(
        f"load({table!r}): no cache, csv, or parquet found. "
        f"Run `mrd onboard {table}` first."
    )

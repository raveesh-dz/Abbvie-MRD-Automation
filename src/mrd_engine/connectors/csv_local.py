"""
csv_local connector. Treats a local CSV (or parquet) file as a "source".

The engine onboards CSV-on-disk through the same code path as Snowflake tables --
profile, propose metadata, manifest, schema gate. Difference: fetch is just a copy
(or a no-op if the file already lives in /data/).
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from mrd_engine.connectors.base import Column, Manifest, column_hash


class CSVLocalConnector:
    name = "csv_local"

    def __init__(self, repo_root: Path):
        self.repo = repo_root

    # ---- protocol surface ------------------------------------------------- #
    def handshake(self) -> dict[str, Any]:
        return {"connector": self.name, "data_dir": str(self.repo / "data")}

    def describe(self, source_object: str) -> list[Column]:
        df = pd.read_csv(self._resolve(source_object), nrows=0)
        return [Column(name=c, type=_infer_type(c, df), nullable=True) for c in df.columns]

    def row_count(self, source_object: str) -> int:
        # Cheap for CSV: read row by row counts are O(n); use a stream count.
        p = self._resolve(source_object)
        if p.suffix == ".parquet":
            return int(pd.read_parquet(p).shape[0])
        n = 0
        with open(p, "rb") as f:
            for _ in f:
                n += 1
        return max(n - 1, 0)  # subtract header

    def fetch(
        self,
        source_object: str,
        target_path: Path,
        row_cap: int | None = 10_000_000,
    ) -> Manifest:
        src = self._resolve(source_object)
        if src.suffix == ".parquet":
            df = pd.read_parquet(src)
        else:
            df = pd.read_csv(src)
        if row_cap and len(df) > row_cap:
            raise RuntimeError(
                f"{source_object} has {len(df):,} rows (> row_cap {row_cap:,})."
            )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(target_path, index=False)
        return Manifest(
            table=src.stem,
            connector=self.name,
            source_object=str(src.relative_to(self.repo)),
            fetched_at=Manifest.now_iso(),
            row_count=len(df),
            column_count=len(df.columns),
            columns=list(df.columns),
            column_hash=column_hash(list(df.columns)),
            cache_path=str(target_path.relative_to(self.repo)),
        )

    # ---- helpers ---------------------------------------------------------- #
    def _resolve(self, source_object: str) -> Path:
        """Accept absolute path, repo-relative path, or bare filename in /data/."""
        p = Path(source_object)
        if p.is_absolute() and p.exists():
            return p
        cand = self.repo / source_object
        if cand.exists():
            return cand
        cand = self.repo / "data" / source_object
        if cand.exists():
            return cand
        # Try with .csv suffix
        cand = self.repo / "data" / f"{source_object}.csv"
        if cand.exists():
            return cand
        raise FileNotFoundError(f"csv_local: cannot resolve {source_object!r}")


def _infer_type(col: str, df: pd.DataFrame) -> str:
    # Header-only DataFrame: fall back to name hints; actual dtypes come from profile.
    lname = col.lower()
    if "date" in lname or "time" in lname or "_dt" in lname:
        return "date"
    return "string"

"""
Connector base interface. Every source type (csv_local, snowflake, ...) implements this.

Why: lets the engine treat data sources uniformly. Onboarding, schema gate, loader,
and run manifests all call the same surface regardless of where the bytes come from.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


@dataclass
class Column:
    name: str
    type: str          # "string" | "integer" | "float" | "date"
    nullable: bool = True


@dataclass
class Manifest:
    table: str
    connector: str
    source_object: str          # e.g. "DB.SCHEMA.TABLE" or "data/file.csv"
    fetched_at: str             # ISO timestamp UTC
    row_count: int
    column_count: int
    columns: list[str]
    column_hash: str            # sha256 over sorted column names
    cache_path: str             # local file the engine actually reads
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def now_iso(cls) -> str:
        return datetime.now(timezone.utc).isoformat()


class Connector(Protocol):
    """Anything that can fetch a table to a local cache file."""

    name: str

    def handshake(self) -> dict[str, Any]:
        """Cheap sanity check. Returns context (account/path/etc)."""
        ...

    def describe(self, source_object: str) -> list[Column]:
        """Column schema from the source side, for drift detection."""
        ...

    def row_count(self, source_object: str) -> int:
        ...

    def fetch(
        self,
        source_object: str,
        target_path: Path,
        row_cap: int | None = 10_000_000,
    ) -> Manifest:
        """Pull source_object into target_path (parquet) and return a manifest."""
        ...


def column_hash(columns: list[str]) -> str:
    """Stable hash over column names (drift detection)."""
    import hashlib
    return "sha256:" + hashlib.sha256(
        "|".join(sorted(columns)).encode("utf-8")
    ).hexdigest()

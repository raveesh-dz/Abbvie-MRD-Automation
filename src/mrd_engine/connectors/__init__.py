"""Connector registry. Resolves connector name -> instance."""
from __future__ import annotations

from pathlib import Path

from mrd_engine.connectors.base import Column, Connector, Manifest, column_hash
from mrd_engine.connectors.csv_local import CSVLocalConnector
from mrd_engine.connectors.snowflake import SnowflakeConnector


_REGISTRY = {
    "csv_local": CSVLocalConnector,
    "snowflake": SnowflakeConnector,
}


def get_connector(name: str, repo_root: Path):
    """Resolve a connector by its `type` field (csv_local / snowflake / ...)."""
    if name not in _REGISTRY:
        raise KeyError(f"Unknown connector type {name!r}. Known: {sorted(_REGISTRY)}")
    return _REGISTRY[name](repo_root)


__all__ = [
    "Column", "Connector", "Manifest", "column_hash",
    "CSVLocalConnector", "SnowflakeConnector", "get_connector",
]

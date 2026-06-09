"""
Snowflake connector. Implements the Connector protocol (mrd_engine.connectors.base).

Auth:
  - externalbrowser (dev SSO) -- opens a browser
  - snowflake_jwt (prod RSA key-pair) -- non-interactive
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
import snowflake.connector

from mrd_engine.connectors.base import Column, Manifest, column_hash


# --------------------------------------------------------------------------- #
# legacy module-level helpers (used by earlier scripts) -- kept for back-compat #
# --------------------------------------------------------------------------- #
def _params_from_env() -> dict[str, Any]:
    keys = ["account", "user", "authenticator", "role", "warehouse", "database", "schema"]
    p = {k: os.environ.get(f"SNOWFLAKE_{k.upper()}") for k in keys}
    return {k: v for k, v in p.items() if v}


def connect(**overrides: Any) -> snowflake.connector.SnowflakeConnection:
    params = _params_from_env()
    params.update({k: v for k, v in overrides.items() if v is not None})
    if not params.get("account") or not params.get("user"):
        raise RuntimeError("SNOWFLAKE_ACCOUNT and SNOWFLAKE_USER must be set in .env")
    return snowflake.connector.connect(**params)


def _fetch_one(conn, sql: str) -> Any:
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()


def _fetch_all(conn, sql: str) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def handshake(conn=None) -> dict[str, Any]:
    own = conn is None
    conn = conn or connect()
    try:
        row = _fetch_one(
            conn,
            "SELECT CURRENT_ACCOUNT(), CURRENT_USER(), CURRENT_ROLE(), "
            "CURRENT_WAREHOUSE(), CURRENT_DATABASE(), CURRENT_SCHEMA()",
        )
    finally:
        if own:
            conn.close()
    return dict(zip(["account", "user", "role", "warehouse", "database", "schema"], row))


def list_warehouses(conn=None) -> list[str]:
    own = conn is None
    conn = conn or connect()
    try:
        return [r[0] for r in _fetch_all(conn, "SHOW WAREHOUSES")]
    finally:
        if own:
            conn.close()


def describe_table(fqn: str, conn=None) -> list[dict[str, Any]]:
    own = conn is None
    conn = conn or connect()
    try:
        rows = _fetch_all(conn, f"DESCRIBE TABLE {fqn}")
    finally:
        if own:
            conn.close()
    return [{"name": r[0], "type": r[1], "nullable": r[3] == "Y"} for r in rows]


def row_count(fqn: str, conn=None) -> int:
    own = conn is None
    conn = conn or connect()
    try:
        return int(_fetch_one(conn, f"SELECT COUNT(*) FROM {fqn}")[0])
    finally:
        if own:
            conn.close()


def sample_table(fqn: str, n: int = 1000, conn=None) -> pd.DataFrame:
    own = conn is None
    conn = conn or connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {fqn} SAMPLE ({n} ROWS)")
            return cur.fetch_pandas_all()
    finally:
        if own:
            conn.close()


def fetch_table(fqn: str, target_path: Path, row_cap: int | None = 10_000_000,
                conn=None) -> dict[str, Any]:
    own = conn is None
    conn = conn or connect()
    try:
        rc = row_count(fqn, conn=conn)
        if row_cap and rc > row_cap:
            raise RuntimeError(
                f"{fqn} has {rc:,} rows (> row_cap {row_cap:,})."
            )
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {fqn}")
            df = cur.fetch_pandas_all()
    finally:
        if own:
            conn.close()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(target_path, index=False)
    return {
        "fqn": fqn,
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": list(df.columns),
        "target": str(target_path),
    }


# --------------------------------------------------------------------------- #
# Connector protocol class                                                     #
# --------------------------------------------------------------------------- #
class SnowflakeConnector:
    name = "snowflake"

    def __init__(self, repo_root: Path):
        self.repo = repo_root
        self._conn: snowflake.connector.SnowflakeConnection | None = None

    def _get_conn(self):
        if self._conn is None or self._conn.is_closed():
            self._conn = connect()
        return self._conn

    def close(self):
        if self._conn and not self._conn.is_closed():
            self._conn.close()
            self._conn = None

    def handshake(self) -> dict[str, Any]:
        return handshake(conn=self._get_conn())

    def describe(self, source_object: str) -> list[Column]:
        rows = describe_table(source_object, conn=self._get_conn())
        return [Column(name=r["name"], type=_yaml_type(r["type"]), nullable=r["nullable"])
                for r in rows]

    def row_count(self, source_object: str) -> int:
        return row_count(source_object, conn=self._get_conn())

    def fetch(self, source_object: str, target_path: Path,
              row_cap: int | None = 10_000_000) -> Manifest:
        result = fetch_table(source_object, target_path, row_cap=row_cap, conn=self._get_conn())
        return Manifest(
            table=source_object.split(".")[-1],
            connector=self.name,
            source_object=source_object,
            fetched_at=Manifest.now_iso(),
            row_count=result["row_count"],
            column_count=result["column_count"],
            columns=result["columns"],
            column_hash=column_hash(result["columns"]),
            cache_path=str(target_path.relative_to(self.repo)),
        )


def _yaml_type(sf_type: str) -> str:
    t = sf_type.upper()
    if any(x in t for x in ("INT", "NUMBER", "DECIMAL", "NUMERIC")):
        return "integer" if "INT" in t else "float"
    if "FLOAT" in t or "REAL" in t or "DOUBLE" in t:
        return "float"
    if "DATE" in t or "TIMESTAMP" in t or "TIME" in t:
        return "date"
    return "string"

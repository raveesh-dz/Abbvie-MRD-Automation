"""
Snowflake connector for the MRD data layer.

Reads connection params from environment (loaded by caller from .env).
Supports two auth modes:
  - externalbrowser (dev, SSO) — opens a browser for the user to sign in
  - snowflake_jwt (prod, RSA key-pair) — non-interactive

Public surface:
  - connect(env_overrides=None) -> snowflake.connector.SnowflakeConnection
  - handshake() -> dict with current_account/role/warehouse/db/schema
  - list_warehouses() / list_databases() / list_schemas() / list_tables()
  - describe_table(fqn) -> list of {name, type, nullable}
  - sample_table(fqn, n=1000) -> pandas.DataFrame
  - row_count(fqn) -> int
  - fetch_table(fqn, target_path, row_cap=None) -> manifest dict
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
import snowflake.connector


def _params_from_env() -> dict[str, Any]:
    keys = ["account", "user", "authenticator", "role", "warehouse", "database", "schema"]
    p = {k: os.environ.get(f"SNOWFLAKE_{k.upper()}") for k in keys}
    # Drop blanks so Snowflake uses user defaults where unset
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
        row = cur.fetchone()
    return row


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
    keys = ["account", "user", "role", "warehouse", "database", "schema"]
    return dict(zip(keys, row))


def list_warehouses(conn=None) -> list[str]:
    own = conn is None
    conn = conn or connect()
    try:
        rows = _fetch_all(conn, "SHOW WAREHOUSES")
    finally:
        if own:
            conn.close()
    # SHOW WAREHOUSES returns name in column 0
    return [r[0] for r in rows]


def describe_table(fqn: str, conn=None) -> list[dict[str, Any]]:
    own = conn is None
    conn = conn or connect()
    try:
        rows = _fetch_all(conn, f"DESCRIBE TABLE {fqn}")
    finally:
        if own:
            conn.close()
    # columns: name, type, kind, null?, default, primary key, unique key, ...
    return [{"name": r[0], "type": r[1], "nullable": r[3] == "Y"} for r in rows]


def row_count(fqn: str, conn=None) -> int:
    own = conn is None
    conn = conn or connect()
    try:
        n = _fetch_one(conn, f"SELECT COUNT(*) FROM {fqn}")[0]
    finally:
        if own:
            conn.close()
    return int(n)


def sample_table(fqn: str, n: int = 1000, conn=None) -> pd.DataFrame:
    own = conn is None
    conn = conn or connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {fqn} SAMPLE ({n} ROWS)")
            df = cur.fetch_pandas_all()
    finally:
        if own:
            conn.close()
    return df


def fetch_table(
    fqn: str,
    target_path: Path,
    row_cap: int | None = 10_000_000,
    conn=None,
) -> dict[str, Any]:
    """Pull full table (up to row_cap) into a parquet file on disk."""
    own = conn is None
    conn = conn or connect()
    try:
        rc = row_count(fqn, conn=conn)
        if row_cap and rc > row_cap:
            raise RuntimeError(
                f"{fqn} has {rc:,} rows (> row_cap {row_cap:,}). "
                f"Raise row_cap explicitly to proceed."
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

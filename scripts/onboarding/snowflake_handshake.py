"""
Sanity check: load .env, connect to Snowflake via externalbrowser SSO,
report current account/role/warehouse/db/schema, list warehouses + databases.

Usage:  py -3 scripts/onboarding/snowflake_handshake.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))


def load_env(path: Path) -> None:
    if not path.exists():
        print(f"[ERROR] {path} not found.")
        sys.exit(1)
    for line in path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    load_env(REPO / ".env")
    from mrd_engine.connectors import snowflake as sf

    print(f"Connecting to Snowflake (account={os.environ.get('SNOWFLAKE_ACCOUNT')}, "
          f"user={os.environ.get('SNOWFLAKE_USER')}, auth=externalbrowser)...")
    print("A browser window should open for SSO. Approve it.")
    conn = sf.connect()
    try:
        info = sf.handshake(conn=conn)
        print("\nSession context:")
        for k, v in info.items():
            print(f"  {k:12} = {v}")

        print("\nAvailable warehouses:")
        for w in sf.list_warehouses(conn=conn):
            print(f"  - {w}")

        # If a database is set, confirm the target table is visible
        target = "SNDBX_DB.ADHOC.ADHOC_FINAL_TABLE"
        try:
            rc = sf.row_count(target, conn=conn)
            print(f"\n{target} row_count = {rc:,}")
        except Exception as exc:
            print(f"\n[WARN] Could not read {target}: {exc}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

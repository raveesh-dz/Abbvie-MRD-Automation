"""
Test write access on the Snowflake account used in .env.

Tries (in order):
  1. CREATE OR REPLACE TEMPORARY TABLE in current schema
  2. CREATE OR REPLACE TABLE <db>.<schema>.MRD_WRITE_TEST + INSERT row + DROP TABLE
  3. PUT a tiny CSV onto a temporary internal stage + COPY INTO a temp table

Reports which capabilities are available, so we know whether we can ingest
CSVs directly into Snowflake later.
"""
from __future__ import annotations

import os
import sys
import tempfile
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


def _exec(conn, sql: str, label: str) -> tuple[bool, str]:
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        print(f"  [OK]   {label}")
        return True, ""
    except Exception as exc:
        msg = str(exc).splitlines()[0]
        print(f"  [FAIL] {label}: {msg}")
        return False, msg


def main() -> int:
    load_env(REPO / ".env")
    from mrd_engine.connectors import snowflake as sf

    conn = sf.connect()
    info = sf.handshake(conn=conn)
    db, schema = info["database"], info["schema"]
    fqn = f"{db}.{schema}.MRD_WRITE_TEST"
    stage = f"{db}.{schema}.MRD_TEST_STAGE"

    print(f"\nContext: db={db}, schema={schema}, role={info['role']}, wh={info['warehouse']}\n")

    print("== Temporary table (session-scoped, never persists) ==")
    _exec(conn, "CREATE OR REPLACE TEMPORARY TABLE MRD_TMP_TEST (x INT)", "create temp table")
    _exec(conn, "INSERT INTO MRD_TMP_TEST VALUES (1),(2),(3)", "insert into temp")
    _exec(conn, "SELECT COUNT(*) FROM MRD_TMP_TEST", "select from temp")
    _exec(conn, "DROP TABLE IF EXISTS MRD_TMP_TEST", "drop temp")

    print(f"\n== Persistent table in {db}.{schema} ==")
    create_ok, _ = _exec(
        conn,
        f"CREATE OR REPLACE TABLE {fqn} (k STRING, v INT)",
        f"create {fqn}",
    )
    if create_ok:
        _exec(conn, f"INSERT INTO {fqn} VALUES ('a', 1),('b', 2)", "insert")
        _exec(conn, f"SELECT COUNT(*) FROM {fqn}", "select")
        _exec(conn, f"DROP TABLE IF EXISTS {fqn}", "drop")

    print(f"\n== Internal stage upload (PUT + COPY INTO) ==")
    # write a tiny CSV to local temp
    tmp_csv = Path(tempfile.gettempdir()) / "mrd_test_upload.csv"
    tmp_csv.write_text("k,v\nfoo,1\nbar,2\nbaz,3\n")
    stage_ok, _ = _exec(
        conn,
        f"CREATE OR REPLACE TEMPORARY STAGE MRD_TMP_STAGE",
        "create temp stage",
    )
    if stage_ok:
        put_sql = f"PUT 'file://{tmp_csv.as_posix()}' @MRD_TMP_STAGE OVERWRITE=TRUE"
        _exec(conn, put_sql, "PUT csv to stage")
        _exec(
            conn,
            "CREATE OR REPLACE TEMPORARY TABLE MRD_UPLOAD_TARGET (k STRING, v INT)",
            "create target temp table",
        )
        _exec(
            conn,
            "COPY INTO MRD_UPLOAD_TARGET FROM @MRD_TMP_STAGE/mrd_test_upload.csv "
            "FILE_FORMAT=(TYPE=CSV SKIP_HEADER=1)",
            "COPY INTO from stage",
        )
        _exec(conn, "SELECT COUNT(*) FROM MRD_UPLOAD_TARGET", "select from uploaded")

    conn.close()
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Onboarding orchestrator. End-to-end:

  1. Resolve connector (csv_local | snowflake | ...) for a source_object
  2. Fetch -> /data/_cache/<table>.parquet, write Manifest
  3. Profile -> /profiles/<table>.json
  4. Propose metadata (claude_cli backend, falling back to heuristic) -> .yaml.proposed
  5. (caller invokes reviewer.review() to promote to .yaml)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from mrd_engine.connectors import get_connector
from mrd_engine.connectors.base import Manifest
from mrd_engine.metadata.profiler import profile_table
from mrd_engine.metadata.proposer import propose


def _load_connector_yaml(repo: Path, name: str) -> dict[str, Any]:
    p = repo / "connectors" / f"{name}.yaml"
    if not p.exists():
        raise FileNotFoundError(f"missing connectors/{name}.yaml")
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def onboard(
    repo: Path,
    connector_name: str,
    source_object: str,
    table_name: str | None = None,
    backend: str = "claude_cli",
    row_cap: int = 10_000_000,
) -> dict[str, Any]:
    conn_cfg = _load_connector_yaml(repo, connector_name)
    ctype = conn_cfg["type"]
    conn = get_connector(ctype, repo)

    # Resolve table name. Snowflake form is DB.SCHEMA.TABLE (no slashes, no .csv).
    # File form is a filename (with extension) or a relative path.
    if not table_name:
        if source_object.lower().endswith((".csv", ".parquet", ".tsv", ".json")) \
                or "/" in source_object or "\\" in source_object:
            table_name = Path(source_object).stem
        else:
            table_name = source_object.split(".")[-1]

    target = repo / "data" / "_cache" / f"{table_name}.parquet"
    print(f"[1/4] {ctype} fetch -> {target.relative_to(repo)}")
    manifest: Manifest = conn.fetch(source_object, target, row_cap=row_cap)
    if hasattr(conn, "close"):
        conn.close()
    print(f"      rows={manifest.row_count:,}, cols={manifest.column_count}")

    profile_path = repo / "profiles" / f"{table_name}.json"
    print(f"[2/4] profiling -> {profile_path.relative_to(repo)}")
    profile = profile_table(target, profile_path)

    source_block = {
        "connector": connector_name,
        "type": ctype,
        "object": source_object,
        "cache_path": str(target.relative_to(repo)),
        "fetched_at": manifest.fetched_at,
        "row_count_at_onboard": manifest.row_count,
        "column_hash": manifest.column_hash,
    }

    proposed_path = repo / "metadata" / f"{table_name}.yaml.proposed"
    print(f"[3/4] proposing metadata ({backend}) -> {proposed_path.relative_to(repo)}")
    fqn = source_object if ctype == "snowflake" else str(Path(source_object).name)
    proposal = propose(table_name, fqn, profile, source_block, backend=backend)
    proposed_path.write_text(
        yaml.safe_dump(proposal, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    manifest_dump_path = repo / "profiles" / f"{table_name}.manifest.json"
    manifest_dump_path.write_text(json.dumps({
        "table": manifest.table, "connector": manifest.connector,
        "source_object": manifest.source_object, "fetched_at": manifest.fetched_at,
        "row_count": manifest.row_count, "column_count": manifest.column_count,
        "columns": manifest.columns, "column_hash": manifest.column_hash,
        "cache_path": manifest.cache_path,
    }, indent=2), encoding="utf-8")
    print(f"[4/4] manifest written -> {manifest_dump_path.relative_to(repo)}")

    return {
        "table": table_name,
        "cache_path": str(target),
        "profile_path": str(profile_path),
        "proposed_metadata_path": str(proposed_path),
        "manifest_path": str(manifest_dump_path),
        "manifest": manifest,
    }

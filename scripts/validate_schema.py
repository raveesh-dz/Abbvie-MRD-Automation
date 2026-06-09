#!/usr/bin/env python3
"""
validate_schema.py — Gate 0 of the workflow.

For every dictionary in /metadata (excluding relationships.yaml):
  - If the dictionary has a `source` block (new path):
      check the declared cache_path exists and the on-disk column hash matches.
  - Else (legacy path):
      require a matching CSV in /data/ with column names that line up.

Always:
  - Dtype spot-check on a 500-row sample (date/int/float parse cleanly).
  - relationships.yaml integrity: every referenced table.column must exist.

Optional:
  - --include-remote: handshake Snowflake sources and diff remote schema vs dictionary.

Exit codes: 0 all clear, 1 halt, 2 warnings only.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import pandas as pd
import yaml

DTYPE_CHECKS = {
    "integer": lambda s: pd.to_numeric(s, errors="coerce"),
    "float": lambda s: pd.to_numeric(s, errors="coerce"),
    "date": lambda s: pd.to_datetime(s, errors="coerce"),
}


def _column_hash(cols: list[str]) -> str:
    return "sha256:" + hashlib.sha256("|".join(sorted(cols)).encode("utf-8")).hexdigest()


def _read_header(path: Path) -> list[str]:
    if path.suffix == ".parquet":
        return list(pd.read_parquet(path).columns)
    return list(pd.read_csv(path, nrows=0).columns)


def _read_sample(path: Path, n: int = 500) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path).head(n)
    return pd.read_csv(path, nrows=n)


def load_dictionaries(meta_dir: Path):
    dicts = {}
    for f in sorted(meta_dir.glob("*.yaml")):
        if f.name == "relationships.yaml" or f.name.startswith("_"):
            continue
        with open(f, encoding="utf-8") as fh:
            d = yaml.safe_load(fh)
        if not d or "table" not in d or "columns" not in d:
            print(f"  [ERROR] {f.name}: missing required keys 'table'/'columns'")
            dicts[f.stem] = None
            continue
        dicts[d["table"]] = d
    return dicts


def _validate_source_block(root: Path, name: str, d: dict,
                           errors: list, warnings: list) -> Path | None:
    """For dictionaries that declare source.cache_path, verify cache + columns."""
    src = d.get("source") or {}
    cache_rel = src.get("cache_path")
    if not cache_rel:
        return None
    cache = root / cache_rel
    if not cache.exists():
        errors.append(f"'{name}': source.cache_path {cache_rel} does not exist on disk.")
        return None
    header = _read_header(cache)
    dict_cols = [c["name"] for c in d["columns"]]
    missing = set(dict_cols) - set(header)
    extra = set(header) - set(dict_cols)
    if missing:
        errors.append(f"'{name}': in dict but NOT in cache: {sorted(missing)}")
    if extra:
        warnings.append(f"'{name}': in cache but NOT in dict: {sorted(extra)}")
    declared = src.get("column_hash")
    actual = _column_hash(header)
    if declared and declared != actual:
        warnings.append(
            f"'{name}': column_hash drift since onboarding "
            f"(declared={declared[:16]}..., actual={actual[:16]}...)"
        )
    return cache


def _validate_legacy_csv(root: Path, name: str, d: dict,
                        errors: list, warnings: list) -> Path | None:
    data_dir = root / "data"
    csv = data_dir / f"{name}.csv"
    if not csv.exists():
        warnings.append(
            f"EXCLUDED: '{name}.csv' not found in /data/ and no source.cache_path declared."
        )
        return None
    header = _read_header(csv)
    dict_cols = [c["name"] for c in d["columns"]]
    missing = set(dict_cols) - set(header)
    extra = set(header) - set(dict_cols)
    if missing:
        errors.append(f"'{name}': columns in dict but NOT in CSV: {sorted(missing)}")
    if extra:
        errors.append(f"'{name}': columns in CSV but NOT in dict: {sorted(extra)}")
    return csv if not (missing or extra) else None


def _dtype_spotcheck(name: str, d: dict, source_path: Path, errors: list) -> None:
    try:
        sample = _read_sample(source_path)
    except Exception as exc:
        errors.append(f"'{name}': failed to read sample from {source_path}: {exc}")
        return
    for col in d["columns"]:
        ctype = col.get("type", "string")
        if ctype not in DTYPE_CHECKS or col["name"] not in sample.columns:
            continue
        series = sample[col["name"]].dropna()
        if len(series) == 0:
            continue
        parsed = DTYPE_CHECKS[ctype](series)
        bad = parsed.isna().sum()
        if bad / len(series) > 0.05:
            errors.append(
                f"'{name}.{col['name']}': declared {ctype}, but "
                f"{bad}/{len(series)} sampled values fail to parse."
            )


def _validate_relationships(meta_dir: Path, dicts: dict, errors: list, warnings: list) -> None:
    rel_path = meta_dir / "relationships.yaml"
    if not rel_path.exists():
        warnings.append("metadata/relationships.yaml not found. Multi-table joins disabled.")
        return
    rels = (yaml.safe_load(rel_path.read_text(encoding="utf-8")) or {}).get("relationships", [])
    valid_cols = {
        f"{t}.{c['name']}" for t, d in dicts.items() for c in d["columns"]
    }
    for r in rels:
        for side in ("left", "right"):
            for ref in str(r.get(side, "")).split("+"):
                ref = ref.strip()
                if "." in ref:
                    tbl = ref.split(".")[0]
                    if tbl in dicts and ref not in valid_cols:
                        errors.append(
                            f"relationships.yaml: '{ref}' not found in any dictionary."
                        )


def _remote_drift_check(root: Path, dicts: dict, warnings: list) -> None:
    """Optional: handshake snowflake sources, diff remote schema vs dict."""
    sys.path.insert(0, str(root / "src"))
    try:
        from mrd_engine.envloader import load_env
        from mrd_engine.connectors import get_connector
        load_env(root / ".env")
    except ImportError as exc:
        warnings.append(f"remote drift check skipped: {exc}")
        return

    snowflake_conn = None
    for name, d in dicts.items():
        src = d.get("source") or {}
        if src.get("type") != "snowflake":
            continue
        try:
            if snowflake_conn is None:
                snowflake_conn = get_connector("snowflake", root)
            remote = snowflake_conn.describe(src["object"])
            remote_names = {c.name for c in remote}
            dict_names = {c["name"] for c in d["columns"]}
            missing = dict_names - remote_names
            extra = remote_names - dict_names
            if missing or extra:
                warnings.append(
                    f"REMOTE DRIFT '{name}': missing-from-source={sorted(missing) or 'none'}; "
                    f"new-in-source={sorted(extra) or 'none'}"
                )
        except Exception as exc:
            warnings.append(f"remote check '{name}': {exc}")
    if snowflake_conn and hasattr(snowflake_conn, "close"):
        snowflake_conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".", help="project root")
    ap.add_argument("--include-remote", action="store_true",
                    help="handshake remote sources (Snowflake) and diff schema")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    meta_dir = root / "metadata"

    errors, warnings = [], []
    dicts = load_dictionaries(meta_dir)
    if any(v is None for v in dicts.values()):
        errors.append("One or more dictionaries are malformed (see above).")
    dicts = {k: v for k, v in dicts.items() if v is not None}

    active: list[str] = []
    excluded: list[str] = []
    for name, d in dicts.items():
        # Prefer source block when present
        path = _validate_source_block(root, name, d, errors, warnings)
        if path is None and not (d.get("source") or {}).get("cache_path"):
            path = _validate_legacy_csv(root, name, d, errors, warnings)
        if path is None:
            excluded.append(name)
            continue
        _dtype_spotcheck(name, d, path, errors)
        if not any(name in e for e in errors):
            active.append(name)

    _validate_relationships(meta_dir, dicts, errors, warnings)
    if args.include_remote:
        _remote_drift_check(root, dicts, warnings)

    print("=" * 60)
    print("SCHEMA VALIDATION REPORT")
    print("=" * 60)
    print(f"Tables active for analysis : {sorted(active) or 'NONE'}")
    print(f"Tables excluded            : {sorted(excluded) or 'none'}")
    for w in warnings:
        print(f"  [WARN]  {w}")
    for e in errors:
        print(f"  [ERROR] {e}")

    if errors:
        print("\nRESULT: HALT — fix errors before any analysis.")
        sys.exit(1)
    if warnings:
        print("\nRESULT: PROCEED with warnings (excluded tables are invisible).")
        sys.exit(2)
    print("\nRESULT: ALL CLEAR.")
    sys.exit(0)


if __name__ == "__main__":
    main()

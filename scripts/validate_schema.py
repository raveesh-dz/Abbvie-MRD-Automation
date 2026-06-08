#!/usr/bin/env python3
"""
validate_schema.py — Gate 0 of the query-to-slide workflow.

For every dictionary in /metadata (excluding relationships.yaml):
  1. The matching CSV must exist in /data        -> else: dictionary orphaned (warn)
For every CSV in /data:
  2. A matching dictionary must exist            -> else: table EXCLUDED from analysis
  3. CSV header must match dictionary columns exactly (names + order-insensitive)
  4. Dtype spot-check on a 500-row sample (date/int/float columns parse cleanly)

Also validates relationships.yaml: every referenced table.column must exist
in a dictionary.

Exit codes: 0 = all clear, 1 = drift/errors found (HALT the session),
            2 = warnings only (excluded tables; proceed without them).

Usage: python scripts/validate_schema.py [--root <project_root>]
"""
import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

DTYPE_CHECKS = {
    "integer": lambda s: pd.to_numeric(s, errors="coerce"),
    "float": lambda s: pd.to_numeric(s, errors="coerce"),
    "date": lambda s: pd.to_datetime(s, errors="coerce"),
}


def load_dictionaries(meta_dir: Path):
    dicts = {}
    for f in sorted(meta_dir.glob("*.yaml")):
        if f.name == "relationships.yaml" or f.name.startswith("_"):
            continue
        with open(f) as fh:
            d = yaml.safe_load(fh)
        if not d or "table" not in d or "columns" not in d:
            print(f"  [ERROR] {f.name}: missing required keys 'table'/'columns'")
            dicts[f.stem] = None
            continue
        dicts[d["table"]] = d
    return dicts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".", help="project root")
    args = ap.parse_args()
    root = Path(args.root)
    data_dir, meta_dir = root / "data", root / "metadata"

    errors, warnings = [], []
    dicts = load_dictionaries(meta_dir)
    if any(v is None for v in dicts.values()):
        errors.append("One or more dictionaries are malformed (see above).")
    dicts = {k: v for k, v in dicts.items() if v is not None}

    csvs = {f.stem: f for f in sorted(data_dir.glob("*.csv"))}

    # 1. Orphaned dictionaries
    for t in dicts:
        if t not in csvs:
            warnings.append(f"Dictionary '{t}.yaml' has no matching CSV in /data.")

    # 2-4. Per-CSV checks
    excluded = []
    for name, path in csvs.items():
        if name not in dicts:
            excluded.append(name)
            warnings.append(
                f"EXCLUDED: '{name}.csv' has no data dictionary. "
                f"It will not be part of any analysis until metadata/{name}.yaml exists."
            )
            continue
        d = dicts[name]
        dict_cols = [c["name"] for c in d["columns"]]
        header = list(pd.read_csv(path, nrows=0).columns)

        missing = set(dict_cols) - set(header)
        extra = set(header) - set(dict_cols)
        if missing:
            errors.append(f"'{name}': columns in dictionary but NOT in CSV: {sorted(missing)}")
        if extra:
            errors.append(f"'{name}': columns in CSV but NOT in dictionary: {sorted(extra)}")
        if missing or extra:
            continue

        sample = pd.read_csv(path, nrows=500)
        for col in d["columns"]:
            ctype = col.get("type", "string")
            if ctype in DTYPE_CHECKS and col["name"] in sample.columns:
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

    # 5. relationships.yaml integrity
    rel_path = meta_dir / "relationships.yaml"
    if rel_path.exists():
        with open(rel_path) as fh:
            rels = (yaml.safe_load(fh) or {}).get("relationships", [])
        valid_cols = {
            f"{t}.{c['name']}" for t, d in dicts.items() for c in d["columns"]
        }
        for r in rels:
            for side in ("left", "right"):
                for ref in str(r.get(side, "")).split("+"):
                    ref = ref.strip()
                    # allow "table.col" refs; composite "a.x + a.y" handled by split
                    if "." in ref:
                        tbl = ref.split(".")[0]
                        if tbl in dicts and ref not in valid_cols:
                            errors.append(
                                f"relationships.yaml: '{ref}' not found in any dictionary."
                            )
    else:
        warnings.append("metadata/relationships.yaml not found. Multi-table joins are disabled.")

    # Report
    print("=" * 60)
    print("SCHEMA VALIDATION REPORT")
    print("=" * 60)
    active = [t for t in csvs if t in dicts and not any(t in e for e in errors)]
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

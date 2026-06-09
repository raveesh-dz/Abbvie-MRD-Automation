"""
Onboard a Snowflake table:
  1. Pull the full table (up to row_cap) to /data/_cache/<table>.parquet
  2. Profile every column (dtype, null %, distinct count, top-K, min/max, sample)
  3. Write profile to /profiles/<table>.json
  4. Propose a /metadata/<table>.yaml dictionary (description, role, known_issues)
  5. Discover candidate joins against any existing /data/*.csv tables (name + value overlap)

Usage:
  py -3 scripts/onboarding/onboard_snowflake_table.py SNDBX_DB.ADHOC.ADHOC_FINAL_TABLE
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

DATA_DIR = REPO / "data"
CACHE_DIR = DATA_DIR / "_cache"
META_DIR = REPO / "metadata"
PROFILE_DIR = REPO / "profiles"


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


# ----------------------- profiling ----------------------------------------- #
def _column_role(series: pd.Series, name: str) -> str:
    n = len(series)
    nun = series.nunique(dropna=True)
    dtype = str(series.dtype)
    lname = name.lower()
    if "date" in dtype or "time" in dtype:
        return "date"
    if any(tok in lname for tok in ("_id", "_key", "npi", "code")) and nun / max(n, 1) > 0.5:
        return "key"
    if "int" in dtype or "float" in dtype:
        # heuristic: low-cardinality numerics are dimensions (e.g. year)
        if nun <= 50:
            return "dimension"
        return "metric"
    if nun / max(n, 1) > 0.95:
        return "key"
    return "dimension"


def profile_dataframe(df: pd.DataFrame, sample_n: int = 5) -> dict:
    out = {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "columns": [],
    }
    for col in df.columns:
        s = df[col]
        nun = int(s.nunique(dropna=True))
        nulls = int(s.isna().sum())
        top = (
            s.dropna().astype(str).value_counts().head(10).to_dict()
            if nun > 0
            else {}
        )
        col_info = {
            "name": col,
            "dtype": str(s.dtype),
            "null_count": nulls,
            "null_pct": round(nulls / max(len(s), 1) * 100, 2),
            "distinct_count": nun,
            "distinct_pct": round(nun / max(len(s), 1) * 100, 2),
            "top_values": top,
            "sample": s.dropna().astype(str).head(sample_n).tolist(),
            "role_guess": _column_role(s, col),
        }
        if pd.api.types.is_numeric_dtype(s) and s.dropna().size:
            col_info["min"] = float(s.min())
            col_info["max"] = float(s.max())
            col_info["mean"] = float(s.mean())
        if pd.api.types.is_datetime64_any_dtype(s) and s.dropna().size:
            col_info["min"] = str(s.min())
            col_info["max"] = str(s.max())
        out["columns"].append(col_info)
    return out


# ----------------------- metadata proposal --------------------------------- #
def propose_metadata(fqn: str, profile: dict, source_connector: str) -> dict:
    table_name = fqn.split(".")[-1]
    cols_yaml = []
    for c in profile["columns"]:
        desc = (
            f"{c['role_guess']} — dtype {c['dtype']}, "
            f"{c['distinct_count']:,} distinct, "
            f"{c['null_pct']}% null."
        )
        col_yaml = {
            "name": c["name"],
            "type": _yaml_type(c["dtype"]),
            "description": desc,
            "role_guess": c["role_guess"],
            "sample_values": list(c["sample"])[:5],
        }
        cols_yaml.append(col_yaml)
    issues = []
    # Flag potential rollup rows in dimension columns
    for c in profile["columns"]:
        if c["role_guess"] in {"dimension", "key"}:
            for val in c["top_values"]:
                if isinstance(val, str) and re.search(
                    r"\b(total|all|market|grand)\b", val, re.I
                ):
                    issues.append(
                        f"'{c['name']}' contains rollup-like values "
                        f"(e.g. '{val}') — verify whether to exclude when aggregating."
                    )
                    break
    return {
        "table": table_name,
        "fqn": fqn,
        "source": {
            "connector": source_connector,
            "object": fqn,
        },
        "description": f"AUTO-GENERATED. Replace this with a one-sentence business description of what {table_name} represents.",
        "grain": "AUTO-GUESS PENDING. Confirm the natural primary-key combination after review.",
        "row_count_at_onboard": profile["row_count"],
        "onboarded_at": datetime.now(timezone.utc).isoformat(),
        "known_issues": issues or ["(none auto-detected — confirm with user)"],
        "columns": cols_yaml,
    }


def _yaml_type(dtype: str) -> str:
    d = dtype.lower()
    if "int" in d:
        return "integer"
    if "float" in d:
        return "float"
    if "date" in d or "time" in d:
        return "date"
    return "string"


# ----------------------- join discovery ------------------------------------ #
def discover_joins(new_df: pd.DataFrame, new_table: str) -> list[dict]:
    """Score candidate joins between new_df and every existing /data/*.csv."""
    candidates = []
    for csv_path in sorted(DATA_DIR.glob("*.csv")):
        try:
            other = pd.read_csv(csv_path, nrows=50_000)
        except Exception as exc:
            print(f"  [warn] could not read {csv_path.name}: {exc}")
            continue
        other_name = csv_path.stem
        for lc in new_df.columns:
            for rc in other.columns:
                # name match (case-insensitive equality or strong substring)
                name_eq = lc.lower() == rc.lower()
                name_sub = (
                    lc.lower() in rc.lower() or rc.lower() in lc.lower()
                ) and min(len(lc), len(rc)) >= 4
                if not (name_eq or name_sub):
                    continue
                # value overlap (Jaccard on stringified distincts)
                lset = set(new_df[lc].dropna().astype(str).str.upper().unique()[:5000])
                rset = set(other[rc].dropna().astype(str).str.upper().unique()[:5000])
                if not lset or not rset:
                    continue
                inter = lset & rset
                union = lset | rset
                jacc = len(inter) / max(len(union), 1)
                overlap_pct = len(inter) / max(min(len(lset), len(rset)), 1)
                if jacc < 0.02 and overlap_pct < 0.1:
                    continue
                candidates.append({
                    "left_table": new_table,
                    "left_col": lc,
                    "right_table": other_name,
                    "right_col": rc,
                    "name_match": "exact" if name_eq else "substring",
                    "jaccard": round(jacc, 4),
                    "overlap_pct_of_smaller": round(overlap_pct, 4),
                    "sample_overlap": list(inter)[:5],
                    "left_distinct": len(lset),
                    "right_distinct": len(rset),
                })
    # rank: name-match + overlap
    def _score(c):
        return (
            (2 if c["name_match"] == "exact" else 1) * 0.5
            + c["overlap_pct_of_smaller"] * 1.0
            + c["jaccard"] * 0.5
        )
    candidates.sort(key=_score, reverse=True)
    return candidates


# ----------------------- main ---------------------------------------------- #
def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: onboard_snowflake_table.py <DB.SCHEMA.TABLE>")
        return 2
    fqn = sys.argv[1]
    load_env(REPO / ".env")
    from mrd_engine.connectors import snowflake as sf

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    META_DIR.mkdir(parents=True, exist_ok=True)

    table_name = fqn.split(".")[-1]
    target = CACHE_DIR / f"{table_name}.parquet"

    print(f"\n=== Onboarding {fqn} ===")
    print(f"[1/4] Fetching to {target.relative_to(REPO)} ...")
    manifest = sf.fetch_table(fqn, target, row_cap=10_000_000)
    print(f"      rows={manifest['row_count']:,}, cols={manifest['column_count']}")

    df = pd.read_parquet(target)

    print(f"[2/4] Profiling {len(df.columns)} columns ...")
    profile = profile_dataframe(df)
    profile_path = PROFILE_DIR / f"{table_name}.json"
    profile_path.write_text(json.dumps(profile, indent=2, default=str))
    print(f"      wrote {profile_path.relative_to(REPO)}")

    print(f"[3/4] Proposing metadata dictionary ...")
    proposal = propose_metadata(fqn, profile, source_connector="snowflake_dz")
    import yaml
    meta_proposed_path = META_DIR / f"{table_name}.yaml.proposed"
    meta_proposed_path.write_text(yaml.safe_dump(proposal, sort_keys=False, allow_unicode=True))
    print(f"      wrote {meta_proposed_path.relative_to(REPO)}")

    print(f"[4/4] Discovering candidate joins against /data/*.csv ...")
    joins = discover_joins(df, new_table=table_name)
    if not joins:
        print("      no plausible joins found.")
    else:
        print(f"      {len(joins)} candidate(s) found (top 10 shown):")
        for j in joins[:10]:
            print(
                f"        - {j['left_table']}.{j['left_col']}  <->  "
                f"{j['right_table']}.{j['right_col']}  "
                f"({j['name_match']}, jaccard={j['jaccard']}, "
                f"overlap={j['overlap_pct_of_smaller']*100:.1f}%, "
                f"sample={j['sample_overlap'][:3]})"
            )
    joins_path = PROFILE_DIR / f"{table_name}.joins.json"
    joins_path.write_text(json.dumps(joins, indent=2, default=str))
    print(f"      wrote {joins_path.relative_to(REPO)}")

    print("\nDone. Review:")
    print(f"  - {meta_proposed_path.relative_to(REPO)}  (rename to .yaml after editing)")
    print(f"  - {profile_path.relative_to(REPO)}")
    print(f"  - {joins_path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

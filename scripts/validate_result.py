#!/usr/bin/env python3
"""
validate_result.py — Step 5 of the query-to-slide workflow.

Checks a run folder's result.csv against its analysis_plan.md:
  1. result.csv exists and is non-empty
  2. Row count vs expected_row_count in the plan (if numeric)
  3. Slide-size convention: warn if > 15 rows (unless plan says full grain)
  4. Null audit on numeric (metric) columns
  5. Duplicate-row check at full grain

Usage: python scripts/validate_result.py output/<run_id> [--max-rows 15]
Exit codes: 0 = pass, 1 = fail (do NOT deliver), 2 = pass with warnings.
"""
import argparse
import re
import sys
from pathlib import Path

import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_folder")
    ap.add_argument("--max-rows", type=int, default=15)
    args = ap.parse_args()
    run = Path(args.run_folder)

    errors, warnings = [], []

    result_path = run / "result.csv"
    if not result_path.exists():
        print(f"[ERROR] {result_path} does not exist.")
        sys.exit(1)
    df = pd.read_csv(result_path)
    if df.empty:
        print("[ERROR] result.csv is empty.")
        sys.exit(1)

    # Expected row count from plan
    plan_path = run / "analysis_plan.md"
    full_grain = False
    if plan_path.exists():
        plan = plan_path.read_text()
        full_grain = "full grain" in plan.lower()
        m = re.search(r"expected_row_count:\s*(\d+)", plan)
        if m:
            expected = int(m.group(1))
            if len(df) != expected:
                errors.append(
                    f"Row count {len(df)} != expected_row_count {expected} in plan."
                )
    else:
        warnings.append("analysis_plan.md not found in run folder; plan checks skipped.")

    # Slide-size convention
    if len(df) > args.max_rows and not full_grain:
        warnings.append(
            f"{len(df)} rows exceeds slide-size default ({args.max_rows}). "
            f"Use top-N + 'Other' rollup, or state 'full grain' in the plan."
        )

    # Null audit on numeric columns
    for col in df.select_dtypes("number").columns:
        n = df[col].isna().sum()
        if n:
            errors.append(f"Metric column '{col}' has {n} null value(s).")

    # Duplicate rows
    dups = df.duplicated().sum()
    if dups:
        errors.append(f"{dups} fully duplicated row(s) — likely a join fan-out.")

    print("=" * 60)
    print(f"RESULT VALIDATION — {run.name}")
    print("=" * 60)
    print(f"Rows: {len(df)} | Columns: {list(df.columns)}")
    for w in warnings:
        print(f"  [WARN]  {w}")
    for e in errors:
        print(f"  [ERROR] {e}")

    if errors:
        print("\nRESULT: FAIL — do not deliver.")
        sys.exit(1)
    if warnings:
        print("\nRESULT: PASS with warnings.")
        sys.exit(2)
    print("\nRESULT: PASS.")
    sys.exit(0)


if __name__ == "__main__":
    main()

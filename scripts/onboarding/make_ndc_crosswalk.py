"""
Build a synthetic NDC -> brand crosswalk so the patient-claims Snowflake table
(SNDBX_DB.ADHOC.ADHOC_FINAL_TABLE) can be joined to the IQVIA brand-aggregated CSVs.

Strategy:
  1. Pull the top-N most frequent NDC_CD values from the Snowflake parquet cache.
  2. Round-robin map them to real IQVIA brand names found in Weekly_Data_Tabular.csv.
  3. Write data/ndc_brand_crosswalk.csv with columns NDC_CD, PRODUCT.
  4. Optionally also stamp the parquet cache with a PRODUCT column joined in-line,
     so the engine can demo a direct join immediately.

This is SYNTHETIC test data — not a real NDC dictionary. Replace with a real
NDC -> brand reference (e.g. from FDA's NDC directory) before production use.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
SEED = 42
TOP_N = 60          # how many NDCs to seed the crosswalk with
random.seed(SEED)


def main() -> int:
    claims_path = REPO / "data" / "_cache" / "ADHOC_FINAL_TABLE.parquet"
    if not claims_path.exists():
        print(f"[ERROR] missing {claims_path}. Run onboard_snowflake_table.py first.")
        return 1

    print(f"[1/3] Loading {claims_path.relative_to(REPO)} ...")
    claims = pd.read_parquet(claims_path, columns=["NDC_CD"])
    top_ndcs = (
        claims["NDC_CD"].dropna().astype(str).value_counts().head(TOP_N).index.tolist()
    )
    print(f"      took top {len(top_ndcs)} NDCs by claim count")

    print(f"[2/3] Reading IQVIA brand list from Weekly_Data_Tabular.csv ...")
    weekly = pd.read_csv(REPO / "data" / "Weekly_Data_Tabular.csv")
    brands = sorted(
        b for b in weekly.loc[weekly["ROW_TYPE"] == "PRODUCT", "PRODUCT"].unique()
        if not b.lower().startswith("total")  # skip rollups
    )
    print(f"      {len(brands)} real IQVIA brands available")

    # Round-robin assignment with a sprinkle of randomness so distribution isn't uniform
    print(f"[3/3] Building synthetic NDC -> PRODUCT crosswalk ...")
    rows = []
    rng = random.Random(SEED)
    for i, ndc in enumerate(top_ndcs):
        # weight a few flagship brands a bit heavier so joins have meaningful row counts
        favored = ["TREMFYA", "SKYRIZI", "SKYRIZI OBI", "HUMIRA (Including Citrate Free)", "RINVOQ", "STELARA SQ"]
        if rng.random() < 0.5 and favored:
            brand = rng.choice(favored)
        else:
            brand = brands[i % len(brands)]
        rows.append({"NDC_CD": ndc, "PRODUCT": brand})

    cross = pd.DataFrame(rows)
    out = REPO / "data" / "ndc_brand_crosswalk.csv"
    cross.to_csv(out, index=False)
    print(f"      wrote {out.relative_to(REPO)}  ({len(cross)} rows)")
    print()
    print(cross.head(15).to_string(index=False))
    print(f"\nDistinct brands assigned: {cross['PRODUCT'].nunique()}")
    print(f"Rows: {len(cross)}")

    # Quick join-coverage estimate: how many claim rows would now be brand-tagged?
    covered = claims["NDC_CD"].isin(set(top_ndcs)).sum()
    pct = covered / len(claims) * 100
    print(f"\nClaim-row coverage after join: {covered:,} / {len(claims):,} ({pct:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

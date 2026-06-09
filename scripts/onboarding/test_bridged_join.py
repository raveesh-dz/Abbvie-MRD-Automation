"""
Demo end-to-end bridged join across the three datasets:

  ADHOC_FINAL_TABLE  --(NDC_CD)-->  ndc_brand_crosswalk  --(PRODUCT)-->  Weekly_Data_Tabular
                                                                  \---->  Monthly_Data_Tabular

Outputs:
  - Per-brand claim counts (claims rolled up by NDC -> brand)
  - Side-by-side brand-level reconciliation: claims vs IQVIA weekly TRx (latest week)
  - Aggregated monthly view: claims per brand-month vs IQVIA Monthly TRx_VOLUME (PRODUCT rows, summed across indications)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    claims = pd.read_parquet(REPO / "data" / "_cache" / "ADHOC_FINAL_TABLE.parquet",
                             columns=["NDC_CD", "SRVC_DT", "YEAR_MONTH"])
    cross = pd.read_csv(REPO / "data" / "ndc_brand_crosswalk.csv", dtype={"NDC_CD": str})
    weekly = pd.read_csv(REPO / "data" / "Weekly_Data_Tabular.csv", parse_dates=["WEEK_ENDING"])
    monthly = pd.read_csv(REPO / "data" / "Monthly_Data_Tabular.csv", parse_dates=["MONTH_DATE"])

    claims["NDC_CD"] = claims["NDC_CD"].astype(str)

    print(f"Inputs:")
    print(f"  claims                 : {len(claims):>9,} rows, {claims['NDC_CD'].nunique():>5,} NDCs")
    print(f"  ndc_brand_crosswalk    : {len(cross):>9,} rows, {cross['PRODUCT'].nunique():>5,} brands")
    print(f"  Weekly_Data_Tabular    : {len(weekly):>9,} rows")
    print(f"  Monthly_Data_Tabular   : {len(monthly):>9,} rows")
    print()

    # ---- step 1: tag claims with brand via the crosswalk ----
    tagged = claims.merge(cross, on="NDC_CD", how="left")
    matched = tagged["PRODUCT"].notna().sum()
    print(f"[1] Claims tagged with brand via NDC_CD : {matched:,} of {len(tagged):,} "
          f"({matched/len(tagged)*100:.1f}%)")

    # ---- step 2: claim counts per brand ----
    by_brand = (
        tagged.dropna(subset=["PRODUCT"])
        .groupby("PRODUCT")
        .size()
        .reset_index(name="CLAIM_COUNT")
        .sort_values("CLAIM_COUNT", ascending=False)
    )
    print(f"\n[2] Claim count per brand (top 10):")
    print(by_brand.head(10).to_string(index=False))

    # ---- step 3: reconcile against IQVIA Weekly latest week ----
    latest_wk = weekly["WEEK_ENDING"].max()
    iqvia_latest = (
        weekly.loc[
            (weekly["WEEK_ENDING"] == latest_wk) & (weekly["ROW_TYPE"] == "PRODUCT"),
            ["PRODUCT", "TRX_ADJUSTED"],
        ]
        .rename(columns={"TRX_ADJUSTED": "IQVIA_WEEKLY_TRX_LATEST"})
    )
    side_by_side = by_brand.merge(iqvia_latest, on="PRODUCT", how="left")
    print(f"\n[3] Brand-level reconciliation (claims_count <-> IQVIA weekly TRx on {latest_wk.date()}):")
    print(side_by_side.head(15).to_string(index=False))

    # ---- step 4: monthly bridge: claim YEAR_MONTH (yyyymm) -> IQVIA MONTH_DATE ----
    tagged_m = tagged.dropna(subset=["PRODUCT"]).copy()
    tagged_m["MONTH_DATE"] = pd.to_datetime(tagged_m["YEAR_MONTH"].astype(str) + "01",
                                            format="%Y%m%d", errors="coerce")
    claims_pm = (
        tagged_m.groupby(["PRODUCT", "MONTH_DATE"])
        .size()
        .reset_index(name="CLAIM_COUNT")
    )
    iqvia_pm = (
        monthly.loc[monthly["ROW_TYPE"] == "PRODUCT"]
        .groupby(["PRODUCT", "MONTH_DATE"])["TRX_VOLUME"]
        .sum()
        .reset_index()
    )
    joined = claims_pm.merge(iqvia_pm, on=["PRODUCT", "MONTH_DATE"], how="inner")
    print(f"\n[4] Brand-month rows where BOTH claims and IQVIA Monthly have data : {len(joined):,}")
    print(joined.sort_values("CLAIM_COUNT", ascending=False).head(10).to_string(index=False))

    # ---- write demo result ----
    out = REPO / "data" / "_cache" / "bridged_join_demo.csv"
    side_by_side.to_csv(out, index=False)
    print(f"\nWrote demo output to {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

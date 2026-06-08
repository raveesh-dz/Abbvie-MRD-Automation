"""
analysis_code.py - run_2026-06-04_002

Split TREMFYA's total weekly TRx across the IBD / GI indications (UC, CD).
The weekly panel is IBD-only (RULE-301), so the full weekly total is IBD volume.

Business rule - RULE-004 (revised 2026-06-04, "renormalise within reported set"):
    The weekly table holds TREMFYA's total weekly TRx but no indication
    breakdown. To split that total across a chosen set of indications we:
      1. roll the monthly TREMFYA dose/form rows up to the brand (RULE-003),
      2. take the brand's monthly TRx for each *reported* indication,
      3. renormalise those across the reported set so the shares sum to 1.0,
      4. apply the matching month's shares to each week's total.
    The full weekly total is therefore distributed across the reported
    indications - they sum back to the weekly total.

    Example: weekly TREMFYA = 100 and the monthly UC:CD ratio is 40:60
             ->  UC = 40,  CD = 60.

Standalone & re-runnable:  py -3 analysis_code.py
Reads only from /data; writes result.csv next to this file.
"""
from pathlib import Path

import pandas as pd

# --------------------------------------------------------------------------- #
# Configuration (see analysis_plan.md)                                        #
# --------------------------------------------------------------------------- #
PROJECT_ROOT = Path(__file__).resolve().parents[2]   # output/<run>/ -> root
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_CSV = Path(__file__).resolve().parent / "result.csv"

WEEKLY_BRAND = "TREMFYA"

# RULE-003 crosswalk: the single weekly "TREMFYA" line == these monthly SQ dose
# rows (SQ only; IV is excluded because the weekly line is SQ).
MONTHLY_BRAND_ROWS = [
    "TREMFYA SQ 100MG",
    "TREMFYA SQ 200MG",
    "TREMFYA SQ INDUCTION",
]

# The indications to split the weekly total across (the IBD / GI market).
REPORTED_INDICATIONS = ["UC", "CD"]


# --------------------------------------------------------------------------- #
# Step 1 - load                                                               #
# --------------------------------------------------------------------------- #
def load_tables():
    """Load the weekly and monthly extracts with parsed date columns."""
    weekly = pd.read_csv(DATA_DIR / "Weekly_Data_Tabular.csv",
                         parse_dates=["WEEK_ENDING"])
    monthly = pd.read_csv(DATA_DIR / "Monthly_Data_Tabular.csv",
                          parse_dates=["MONTH_DATE"])
    return weekly, monthly


# --------------------------------------------------------------------------- #
# Step 2 - weekly TREMFYA total per week                                      #
# --------------------------------------------------------------------------- #
def weekly_brand_totals(weekly):
    """One row per week holding TREMFYA's total weekly TRx (PRODUCT rows only).

    Adds a `month` column (first day of the WEEK_ENDING month) so each week can
    be lined up with the monthly indication mix.
    """
    brand = weekly[(weekly["ROW_TYPE"] == "PRODUCT")
                   & (weekly["PRODUCT"] == WEEKLY_BRAND)]
    totals = (brand.groupby("WEEK_ENDING", as_index=False)["TRX_ADJUSTED"]
                   .sum()
                   .rename(columns={"TRX_ADJUSTED": "TREMFYA_TRx_total"}))
    totals["month"] = totals["WEEK_ENDING"].dt.to_period("M").dt.to_timestamp()
    return totals


# --------------------------------------------------------------------------- #
# Step 3 - monthly indication mix, renormalised to the reported set           #
# --------------------------------------------------------------------------- #
def monthly_indication_shares(monthly):
    """Renormalised monthly indication mix for the reported indications.

    Returns a DataFrame indexed by MONTH_DATE with one column per reported
    indication; each row sums to 1.0. A month with no reported-indication
    volume sums to 0.0 (its weekly total cannot be split and will show 0).
    """
    brand = monthly[(monthly["ROW_TYPE"] == "PRODUCT")
                    & (monthly["PRODUCT"].isin(MONTHLY_BRAND_ROWS))
                    & (monthly["INDICATION"].isin(REPORTED_INDICATIONS))]

    # Roll the crosswalked dose/form rows up to one TRx per indication-month,
    # then lay the reported indications out as columns.
    monthly_trx = (brand.groupby(["MONTH_DATE", "INDICATION"])["TRX_VOLUME"]
                        .sum()
                        .unstack(fill_value=0.0)
                        .reindex(columns=REPORTED_INDICATIONS, fill_value=0.0))

    # Renormalise across the reported indications so each month sums to 1.0.
    month_total = monthly_trx.sum(axis=1)
    shares = monthly_trx.div(month_total.where(month_total > 0), axis=0)
    return shares.fillna(0.0)


# --------------------------------------------------------------------------- #
# Step 4 - align each week to a month's shares (with carry-forward)           #
# --------------------------------------------------------------------------- #
def shares_per_week(weeks, shares):
    """Return the share row to use for each week, in week order.

    Weeks past the last month in the monthly extract reuse the latest available
    month's mix (carry-forward), per RULE-004.
    """
    available_months = shares.index.sort_values()

    def resolve_month(month):
        eligible = available_months[available_months <= month]
        return eligible.max() if len(eligible) else available_months.min()

    mix_month = weeks["month"].map(resolve_month)
    return shares.loc[mix_month].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Step 5 - allocate the weekly total across the reported indications          #
# --------------------------------------------------------------------------- #
def allocate(weeks, week_shares):
    """Multiply each week's total by its renormalised indication shares."""
    result = weeks[["WEEK_ENDING", "TREMFYA_TRx_total"]].reset_index(drop=True)
    for indication in REPORTED_INDICATIONS:
        result[indication] = (result["TREMFYA_TRx_total"]
                              * week_shares[indication]).round(6)
    return result


# --------------------------------------------------------------------------- #
# Run                                                                          #
# --------------------------------------------------------------------------- #
def main():
    weekly, monthly = load_tables()

    weeks = weekly_brand_totals(weekly)            # weekly TREMFYA totals
    shares = monthly_indication_shares(monthly)    # renormalised monthly mix
    week_shares = shares_per_week(weeks, shares)   # mix aligned to each week
    result = allocate(weeks, week_shares)          # total -> UC / CD

    # Indications first, total kept alongside as a reconciliation column
    # (UC + CD == TREMFYA_TRx_total in every week that has IBD volume).
    ordered = ["WEEK_ENDING"] + REPORTED_INDICATIONS + ["TREMFYA_TRx_total"]
    result = result[ordered].sort_values("WEEK_ENDING")
    result["WEEK_ENDING"] = result["WEEK_ENDING"].dt.strftime("%Y-%m-%d")

    result.to_csv(OUTPUT_CSV, index=False)
    print(f"wrote {len(result)} rows -> {OUTPUT_CSV}")


if __name__ == "__main__":
    main()

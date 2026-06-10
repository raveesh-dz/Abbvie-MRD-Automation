#!/usr/bin/env python3
"""
run_2026-06-10_001 — Monthly TRx for HUMIRA split by indication, latest 6 months.

Standalone, re-runnable. Reads only /data/, writes result.csv into this folder.
Plan: output/run_2026-06-10_001/analysis_plan.md
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RUN = Path(__file__).resolve().parent

HUMIRA = "HUMIRA (Including Citrate Free)"
N_MONTHS = 6


def load() -> pd.DataFrame:
    df = pd.read_csv(ROOT / "data" / "Monthly_Data_Tabular.csv")
    df["MONTH_DATE"] = pd.to_datetime(df["MONTH_DATE"])
    return df


def filter_humira(df: pd.DataFrame) -> pd.DataFrame:
    # Standing filters: none defined in semantic/filters.md.
    # PRODUCT rows only (MARKET_TOTAL double-counts) and the Total PsA rollup
    # excluded (it duplicates PsA (Derm) + PsA (Rheum)).
    out = df[
        (df["PRODUCT"] == HUMIRA)
        & (df["ROW_TYPE"] == "PRODUCT")
        & (df["INDICATION"] != "Total PsA")
    ].copy()
    return out


def latest_months(df: pd.DataFrame, n: int) -> list:
    return sorted(df["MONTH_DATE"].unique())[-n:]


def compute(df: pd.DataFrame, months: list) -> pd.DataFrame:
    win = df[df["MONTH_DATE"].isin(months)]
    wide = (
        win.pivot_table(
            index="MONTH_DATE",
            columns="INDICATION",
            values="TRX_VOLUME",
            aggfunc="sum",
        )
        .sort_index()
    )
    # Absent row in source = no data, not zero; but for a wide slide table a
    # missing cell would fail the null audit — fill with 0 only if any appear.
    wide = wide.fillna(0.0)
    # Order columns by latest-month volume, largest first.
    order = wide.iloc[-1].sort_values(ascending=False).index.tolist()
    wide = wide[order].round(2)
    wide.index = wide.index.strftime("%Y-%m-%d")
    wide.index.name = "MONTH_DATE"
    return wide.reset_index()


def main():
    df = load()
    humira = filter_humira(df)
    months = latest_months(df, N_MONTHS)

    result = compute(humira, months)
    result.to_csv(RUN / "result.csv", index=False)

    # Audit prints
    print(f"window: {months[0].date()} .. {months[-1].date()}")
    print(f"rows: {len(result)}  columns: {list(result.columns)}")
    print(f"humira rows in window: {len(humira[humira['MONTH_DATE'].isin(months)])}")
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()

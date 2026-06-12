#!/usr/bin/env python3
"""
perturb_data.py — randomly perturb every TRx value by +/-7%, reversibly.

Each numeric cell is multiplied by an independent random factor U(low, high)
(default [0.93, 1.07]). Seeded -> reproducible. Values never go negative.

Weekly (clean 2-level rollups) are kept consistent by recomputing the totals
from the perturbed leaves:
    Total Non-Approved Volume (flag N)  = sum(flag-Y PRODUCT rows)
    MARKET_TOTAL ("SI Market + Oral")   = sum(flag-N PRODUCT rows, incl. the above)
A per-week guard asserts the identity held on the ORIGINAL data first; weeks
that don't match are perturbed leaf-only and logged (no silently-wrong total).

Monthly rollups are NOT recomputed: the monthly hierarchy (per-indication
MARKET_TOTAL, brand "(Total)" lines, "Total PsA", biosimilar TOTALs) is
undeclared and MARKET_TOTAL != sum(products). Every monthly row is perturbed
independently; internal monthly totals will NOT reconcile afterwards. No active
analysis reads a monthly rollup row (all use PRODUCT-grain UC/CD only).

Backups: current CSVs are copied to data/_pre_perturb/ before writing. The
true pre-refresh source in data/_original/ is never touched.

Usage:  py -3 scripts/perturb_data.py [--seed 20260610] [--low 0.93] [--high 1.07]
"""
import argparse
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BACKUP = DATA / "_pre_perturb"
TOL = 0.005  # 0.5% identity tolerance on original data
TNAV = "Total Non-Approved Volume"


def backup():
    BACKUP.mkdir(exist_ok=True)
    for name in ("Weekly_Data_Tabular.csv", "Monthly_Data_Tabular.csv"):
        shutil.copy2(DATA / name, BACKUP / name)
    print(f"[backup] current CSVs -> {BACKUP}")


def perturb_weekly(rng, lo, hi):
    path = DATA / "Weekly_Data_Tabular.csv"
    df = pd.read_csv(path)
    col = "TRX_ADJUSTED"

    is_prod = df["ROW_TYPE"] == "PRODUCT"
    is_mt = df["ROW_TYPE"] == "MARKET_TOTAL"
    is_tnav = is_prod & (df["PRODUCT"] == TNAV)

    # --- 1. original per-week identity check (BEFORE perturb) ---
    good_weeks = {}
    for wk, g in df.groupby("WEEK_ENDING"):
        gp = g[g["ROW_TYPE"] == "PRODUCT"]
        flagY = gp[gp["NON_APPROVED_FLAG"] == "Y"][col].sum()
        flagN = gp[gp["NON_APPROVED_FLAG"] == "N"][col].sum()
        tnav = gp[gp["PRODUCT"] == TNAV][col].sum()
        mt = g[g["ROW_TYPE"] == "MARKET_TOTAL"][col].sum()
        tnav_ok = abs(tnav - flagY) <= TOL * max(flagY, 1.0)
        mt_ok = abs(mt - flagN) <= TOL * max(flagN, 1.0)
        good_weeks[wk] = tnav_ok and mt_ok

    n_bad = sum(1 for v in good_weeks.values() if not v)

    # --- 2. perturb leaves (all PRODUCT rows except the TNAV rollup) ---
    leaf_idx = df.index[is_prod & (df["PRODUCT"] != TNAV)]
    factors = rng.uniform(lo, hi, size=len(leaf_idx))
    df.loc[leaf_idx, col] = np.clip(
        df.loc[leaf_idx, col].to_numpy(dtype=float) * factors, 0.0, None
    )

    # --- 3. recompute rollups per good week ---
    for wk, g in df.groupby("WEEK_ENDING"):
        if not good_weeks[wk]:
            continue
        gp_idx = g.index[g["ROW_TYPE"] == "PRODUCT"]
        # Total Non-Approved Volume = sum(flag-Y product rows)
        y_idx = [i for i in gp_idx if df.at[i, "NON_APPROVED_FLAG"] == "Y"]
        tnav_val = df.loc[y_idx, col].sum()
        tnav_row = g.index[(g["ROW_TYPE"] == "PRODUCT") & (g["PRODUCT"] == TNAV)]
        df.loc[tnav_row, col] = tnav_val
        # MARKET_TOTAL = sum(flag-N product rows incl. recomputed TNAV)
        n_idx = [i for i in gp_idx if df.at[i, "NON_APPROVED_FLAG"] == "N"]
        mt_val = df.loc[n_idx, col].sum()
        df.loc[g.index[g["ROW_TYPE"] == "MARKET_TOTAL"], col] = mt_val

    df.to_csv(path, index=False)

    # --- audit ---
    print(f"[weekly] rows: {len(df)} | leaves perturbed: {len(leaf_idx)} | "
          f"weeks: {len(good_weeks)} | recomputed: {len(good_weeks)-n_bad} | "
          f"leaf-only (identity failed): {n_bad}")
    if n_bad:
        bad = [w for w, ok in good_weeks.items() if not ok]
        print(f"[weekly] WARN leaf-only weeks: {bad}")
    # re-verify a recomputed week
    sample = next(w for w, ok in good_weeks.items() if ok)
    g = df[df["WEEK_ENDING"] == sample]
    gp = g[g["ROW_TYPE"] == "PRODUCT"]
    mt = g[g["ROW_TYPE"] == "MARKET_TOTAL"][col].sum()
    nsum = gp[gp["NON_APPROVED_FLAG"] == "N"][col].sum()
    print(f"[weekly] post-recompute check {sample}: MARKET_TOTAL={mt:.2f} "
          f"vs sum(flagN)={nsum:.2f} diff={mt-nsum:.2e}")
    print(f"[weekly] min value: {df[col].min():.4f}  (>=0 ok: {df[col].min()>=0})")


def perturb_monthly(rng, lo, hi):
    path = DATA / "Monthly_Data_Tabular.csv"
    df = pd.read_csv(path)
    col = "TRX_VOLUME"
    factors = rng.uniform(lo, hi, size=len(df))
    df[col] = np.clip(df[col].to_numpy(dtype=float) * factors, 0.0, None)
    df.to_csv(path, index=False)
    print(f"[monthly] rows perturbed (all, independent): {len(df)} | "
          f"min value: {df[col].min():.4f}  (>=0 ok: {df[col].min()>=0})")
    print("[monthly] NOTE rollup identities (MARKET_TOTAL, *(Total), Total PsA, "
          "biosimilar TOTALs) intentionally NOT preserved.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260610)
    ap.add_argument("--low", type=float, default=0.93)
    ap.add_argument("--high", type=float, default=1.07)
    args = ap.parse_args()

    pct = round((args.high - 1.0) * 100)
    print(f"[perturb] seed={args.seed} factor=U({args.low},{args.high})  (+/-{pct}%)")
    rng = np.random.default_rng(args.seed)
    backup()
    perturb_weekly(rng, args.low, args.high)
    perturb_monthly(rng, args.low, args.high)
    print("[done] data perturbed. Backup in data/_pre_perturb/. "
          "Re-run analyses next.")


if __name__ == "__main__":
    main()

"""
Analysis — run_2026-06-26_001
Holdout classification: have doctors shifted CD new prescribing from STELARA to SKYRIZI?

Standalone. Reads only from /data/. Writes result.csv into this run folder.
Re-runnable without the session. All arithmetic is in pandas (engine never hand-calcs).

Sections mirror analysis_plan.md: load -> filter -> compute -> classify -> output.
"""
import os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "data")

GASTRO = os.path.join(DATA, "sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl.csv")
UNIVERSE = os.path.join(DATA, "Holdout_HCP_Universe.csv")

ID = "abv_customer_id"
FRX_13 = [f"frx{i}" for i in range(1, 14)]   # cur_13wk = frx1..frx13 (RULE-006/007/401)
RATIO_THRESHOLD = 0.5


def load():
    df = pd.read_csv(GASTRO, low_memory=False)
    uni = pd.read_csv(UNIVERSE)
    return df, uni


def brand_13wk(df, brand):
    """Per-HCP cur_13wk NBRx sum for one CD brand slice. RULE-005 (NBRx stored,
    selected by filter) + RULE-007 (cur_13wk = sum frx1..13). product_brand
    matched EXACTLY (no _IV, no biosimilars) per user scope choice."""
    slice_ = df[
        (df["data_type"] == "NBRx")
        & (df["indication_code"] == "CD")
        & (df["product_brand"] == brand)
    ].copy()
    slice_["nbrx_13wk"] = slice_[FRX_13].sum(axis=1)
    # one HCP could in principle have >1 row for a (brand,indication,data_type)
    # slice; sum to be safe (RULE-005 says 1:1, this is a guard, not a join).
    out = slice_.groupby(ID, as_index=False)["nbrx_13wk"].sum()
    return out


def main():
    df, uni = load()

    # --- scope: restrict to holdout universe (RULE-102). Build the spine from the
    # universe so every in-scope HCP appears, incl. doctors with no CD NBRx. ---
    spine = uni.rename(columns={"abbott_customer_id": ID})[[ID]].drop_duplicates()
    n_spine = len(spine)

    # --- per-brand 13wk NBRx ---
    sky = brand_13wk(df, "SKYRIZI").rename(columns={"nbrx_13wk": "skyrizi_cd_nbrx_13wk"})
    stel = brand_13wk(df, "STELARA").rename(columns={"nbrx_13wk": "stelara_cd_nbrx_13wk"})

    # left-join onto spine; HCPs absent from a brand slice = no NBRx = 0
    res = spine.merge(sky, on=ID, how="left").merge(stel, on=ID, how="left")
    res["skyrizi_cd_nbrx_13wk"] = res["skyrizi_cd_nbrx_13wk"].fillna(0.0)
    res["stelara_cd_nbrx_13wk"] = res["stelara_cd_nbrx_13wk"].fillna(0.0)

    # --- numeric ratio: defined only when SKYRIZI > 0 (else undefined / NaN) ---
    # Kept internally for classification; NOT emitted as a numeric column because a
    # NaN there reads as a bad-join signal to the gate. It is undefined-by-design
    # (denominator 0), so we surface it as a labeled string column instead.
    sky_pos = res["skyrizi_cd_nbrx_13wk"] > 0
    res["_ratio_num"] = pd.NA
    res.loc[sky_pos, "_ratio_num"] = (
        res.loc[sky_pos, "stelara_cd_nbrx_13wk"] / res.loc[sky_pos, "skyrizi_cd_nbrx_13wk"]
    )

    # --- classify (RULE-010) ---
    def group(row):
        sk, st, ra = row["skyrizi_cd_nbrx_13wk"], row["stelara_cd_nbrx_13wk"], row["_ratio_num"]
        if sk == 0 and st == 0:
            return "no_cd_nbrx"
        if sk == 0 and st > 0:
            return "stelara_only"
        if st == 0 and sk > 0:
            return "skyrizi_only"
        # both > 0
        return "both_lean_stelara" if ra >= RATIO_THRESHOLD else "both_lean_skyrizi"

    res["classification_group"] = res.apply(group, axis=1)

    # --- ratio as an explicit, fully-populated display column (string) ---
    # defined rows -> the rounded number as text; undefined rows -> a labeled reason
    # so the table is self-documenting and carries no ambiguous numeric nulls.
    def ratio_str(row):
        sk, st, ra = row["skyrizi_cd_nbrx_13wk"], row["stelara_cd_nbrx_13wk"], row["_ratio_num"]
        if sk > 0:
            return f"{ra:.4f}"
        if st > 0:
            return "undefined_stelara_only"   # STELARA present, no SKYRIZI denominator
        return "undefined_no_cd_nbrx"          # neither brand -> 0/0
    res["stelara_to_skyrizi_ratio"] = res.apply(ratio_str, axis=1)

    holdout_groups = {"no_cd_nbrx", "stelara_only", "both_lean_stelara"}
    res["holdout_status"] = res["classification_group"].apply(
        lambda g: "Holdout" if g in holdout_groups else "Non-Holdout"
    )

    # --- output (computation columns only, user choice) ---
    res = res.rename(columns={ID: "abbott_customer_id"})
    res = res[[
        "abbott_customer_id",
        "skyrizi_cd_nbrx_13wk",
        "stelara_cd_nbrx_13wk",
        "stelara_to_skyrizi_ratio",
        "classification_group",
        "holdout_status",
    ]].sort_values("abbott_customer_id").reset_index(drop=True)

    out_path = os.path.join(HERE, "result.csv")
    res.to_csv(out_path, index=False)

    # --- console audit (not part of contract) ---
    print(f"spine HCPs (universe): {n_spine}")
    print(f"result rows: {len(res)}")
    print("group counts:\n", res["classification_group"].value_counts())
    print("holdout status:\n", res["holdout_status"].value_counts())
    print("wrote", out_path)


if __name__ == "__main__":
    main()

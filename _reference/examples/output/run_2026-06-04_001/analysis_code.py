"""Generated for run_2026-06-04_001 — standalone, re-runnable."""
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # examples/
rx = pd.read_csv(ROOT / "data/rx_transactions.csv", parse_dates=["week_ending"])
hcp = pd.read_csv(ROOT / "data/hcp_master.csv")

# --- standing filters (filters.md) ---
# RULE-102: drop 2 provisional weeks -> anchor date
weeks = sorted(rx.week_ending.unique())
anchor = weeks[-3]
rx = rx[rx.week_ending <= anchor]

# --- time window: R13W back from anchor (RULE-201/202) ---
start = pd.Timestamp(anchor) - pd.Timedelta(weeks=12)
rx = rx[rx.week_ending >= start]

# --- join (relationships.yaml: many-to-one, inner) ---
n_before = len(rx)
df = rx.merge(hcp[["hcp_id", "specialty"]], on="hcp_id", how="inner")
assert len(df) == n_before, "join fan-out detected"

# --- compute share per RULE-002 ---
g = df.groupby(["week_ending", "specialty", "product"], as_index=False).trx.sum()
piv = g.pivot_table(index=["week_ending", "specialty"], columns="product",
                    values="trx", fill_value=0).reset_index()
piv["product_a_share_pct"] = (100 * piv["PRODUCT_A"]
                              / (piv["PRODUCT_A"] + piv["COMPETITOR_X"])).round(1)
out = piv[["week_ending", "specialty", "PRODUCT_A", "COMPETITOR_X", "product_a_share_pct"]]
out.columns = ["week_ending", "specialty", "product_a_trx", "competitor_x_trx", "product_a_share_pct"]
out.to_csv(Path(__file__).parent / "result.csv", index=False)
print(f"rows={len(out)}")

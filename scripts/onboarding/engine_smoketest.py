"""
End-to-end smoke test: pretend a user query lands. Uses ONLY public surfaces:

  mrd_engine.loader.load(table)        -> DataFrame (source-agnostic)
  mrd_engine.runs.manifest.write_manifest(...)

Workflow simulated:
  1. Load ADHOC_FINAL_TABLE, ndc_brand_crosswalk, Weekly_Data_Tabular via loader
  2. Bridge: claims -> NDC -> brand
  3. Aggregate claim counts vs latest IQVIA weekly TRx by brand
  4. Write result.csv + source_manifest.json into output/run_test_<id>/

This validates the data-layer surface that the existing analytics engine will use.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

import pandas as pd
import yaml

from mrd_engine.loader import load
from mrd_engine.connectors.base import Manifest, column_hash
from mrd_engine.runs.manifest import write_manifest


def manifest_from_metadata(table: str) -> Manifest | None:
    p = REPO / "metadata" / f"{table}.yaml"
    if not p.exists():
        return None
    m = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    src = m.get("source") or {}
    # If no source block (legacy CSV path), synthesize one from disk
    if not src:
        csv = REPO / "data" / f"{table}.csv"
        if not csv.exists():
            return None
        cols = list(pd.read_csv(csv, nrows=0).columns)
        return Manifest(
            table=table, connector="csv_legacy",
            source_object=str(csv.relative_to(REPO)),
            fetched_at=Manifest.now_iso(),
            row_count=-1, column_count=len(cols), columns=cols,
            column_hash=column_hash(cols), cache_path=str(csv.relative_to(REPO)),
        )
    return Manifest(
        table=table,
        connector=src.get("connector", "?"),
        source_object=src.get("object", ""),
        fetched_at=src.get("fetched_at", Manifest.now_iso()),
        row_count=src.get("row_count_at_onboard", -1),
        column_count=len(m.get("columns", [])),
        columns=[c["name"] for c in m.get("columns", [])],
        column_hash=src.get("column_hash", ""),
        cache_path=src.get("cache_path", ""),
    )


def main() -> int:
    print("=== engine smoke test: bridged join via mrd loader ===\n")

    print("[1] loading three tables via mrd_engine.loader.load() ...")
    claims = load("ADHOC_FINAL_TABLE")
    cross  = load("ndc_brand_crosswalk")
    weekly = load("Weekly_Data_Tabular")
    print(f"    claims = {claims.shape}, crosswalk = {cross.shape}, weekly = {weekly.shape}")

    print("\n[2] bridging claims -> NDC -> brand ...")
    claims["NDC_CD"] = claims["NDC_CD"].astype(str)
    cross["NDC_CD"]  = cross["NDC_CD"].astype(str)
    tagged = claims.merge(cross, on="NDC_CD", how="left")
    matched = tagged["PRODUCT"].notna().sum()
    print(f"    {matched:,} of {len(tagged):,} claim rows tagged ({matched/len(tagged)*100:.1f}%)")

    print("\n[3] aggregating + reconciling vs IQVIA latest week ...")
    by_brand = (
        tagged.dropna(subset=["PRODUCT"])
        .groupby("PRODUCT").size().reset_index(name="CLAIM_COUNT")
    )
    weekly["WEEK_ENDING"] = pd.to_datetime(weekly["WEEK_ENDING"])
    latest = weekly["WEEK_ENDING"].max()
    iqvia_latest = (
        weekly.loc[(weekly["WEEK_ENDING"] == latest) & (weekly["ROW_TYPE"] == "PRODUCT"),
                   ["PRODUCT", "TRX_ADJUSTED"]]
        .rename(columns={"TRX_ADJUSTED": f"IQVIA_TRX_{latest.date()}"})
    )
    result = (by_brand.merge(iqvia_latest, on="PRODUCT", how="left")
              .sort_values("CLAIM_COUNT", ascending=False))
    print(f"    {len(result)} brand rows in result")

    print("\n[4] writing run folder ...")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_dir = REPO / "output" / f"run_{ts}_smoke"
    run_dir.mkdir(parents=True, exist_ok=True)
    out_csv = run_dir / "result.csv"
    result.to_csv(out_csv, index=False)
    print(f"    wrote {out_csv.relative_to(REPO)}")

    mans = [m for m in (
        manifest_from_metadata("ADHOC_FINAL_TABLE"),
        manifest_from_metadata("ndc_brand_crosswalk"),
        manifest_from_metadata("Weekly_Data_Tabular"),
    ) if m is not None]
    out_manifest = write_manifest(run_dir, mans)
    print(f"    wrote {out_manifest.relative_to(REPO)}")

    print("\n=== result (top 8) ===")
    print(result.head(8).to_string(index=False))
    print("\n=== source_manifest.json ===")
    print(out_manifest.read_text()[:600])
    return 0


if __name__ == "__main__":
    sys.exit(main())

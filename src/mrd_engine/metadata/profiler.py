"""
Statistical profiler. Reads a parquet (the cache) and emits a profile JSON
that grounds downstream metadata proposal.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def _role_guess(s: pd.Series, name: str) -> str:
    n = max(len(s), 1)
    nun = s.nunique(dropna=True)
    dtype = str(s.dtype)
    lname = name.lower()
    if "date" in dtype or "time" in dtype:
        return "date"
    if any(tok in lname for tok in ("_id", "_key", "npi", "code", "ndc")) and nun / n > 0.5:
        return "key"
    if "int" in dtype or "float" in dtype:
        return "dimension" if nun <= 50 else "metric"
    if nun / n > 0.95:
        return "key"
    return "dimension"


def profile_dataframe(df: pd.DataFrame, sample_n: int = 5) -> dict[str, Any]:
    out: dict[str, Any] = {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "columns": [],
    }
    for col in df.columns:
        s = df[col]
        nun = int(s.nunique(dropna=True))
        nulls = int(s.isna().sum())
        info: dict[str, Any] = {
            "name": col,
            "dtype": str(s.dtype),
            "null_count": nulls,
            "null_pct": round(nulls / max(len(s), 1) * 100, 2),
            "distinct_count": nun,
            "distinct_pct": round(nun / max(len(s), 1) * 100, 2),
            "top_values": (
                s.dropna().astype(str).value_counts().head(10).to_dict() if nun > 0 else {}
            ),
            "sample": s.dropna().astype(str).head(sample_n).tolist(),
            "role_guess": _role_guess(s, col),
        }
        if pd.api.types.is_numeric_dtype(s) and s.dropna().size:
            info["min"] = float(s.min())
            info["max"] = float(s.max())
            info["mean"] = float(s.mean())
        if pd.api.types.is_datetime64_any_dtype(s) and s.dropna().size:
            info["min"] = str(s.min())
            info["max"] = str(s.max())
        out["columns"].append(info)
    return out


def profile_table(parquet_path: Path, out_json: Path) -> dict[str, Any]:
    df = pd.read_parquet(parquet_path)
    prof = profile_dataframe(df)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(prof, indent=2, default=str))
    return prof

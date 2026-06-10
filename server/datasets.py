"""Read each table's data dictionary + CSV and report grain, date range, rows."""
import pandas as pd
import yaml

from . import config

DATE_TYPE = "date"


def _load_dict(name: str) -> dict:
    with open(config.metadata_dir() / f"{name}.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def date_column(d: dict):
    for c in d.get("columns", []):
        if c.get("type") == DATE_TYPE:
            return c["name"]
    return None


def table_names() -> list:
    names = []
    for f in sorted(config.metadata_dir().glob("*.yaml")):
        if f.name == "relationships.yaml" or f.name.startswith("_"):
            continue
        names.append(f.stem)
    return names


def table_info(name: str) -> dict:
    d = _load_dict(name)
    df = pd.read_csv(config.data_dir() / f"{name}.csv")
    dcol = date_column(d)
    dates = pd.to_datetime(df[dcol], errors="coerce") if dcol else None
    num = df.select_dtypes("number")
    info_extra = {
        "metric_nulls": int(num.isna().sum().sum()),
        "periods": int(dates.nunique()) if dcol else None,
    }
    return {
        "name": d.get("table", name),
        "description": d.get("description", ""),
        "grain": d.get("grain", ""),
        "refresh": d.get("refresh", ""),
        "date_column": dcol,
        "min_date": dates.min().strftime("%Y-%m-%d") if dcol else None,
        "max_date": dates.max().strftime("%Y-%m-%d") if dcol else None,
        "row_count": int(len(df)),
        **info_extra,
    }


def all_tables() -> list:
    return [table_info(n) for n in table_names()]

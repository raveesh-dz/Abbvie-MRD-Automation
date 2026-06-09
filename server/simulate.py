"""Demo helper: append a cloned 'next period' to both CSVs (reversible).

Cloning the latest period's rows preserves MARKET_TOTAL rows, NON_APPROVED
flags and every product/indication automatically — no per-row synthesis.
The untouched originals are backed up on first use so reset() restores them
byte-for-byte."""
import shutil

import pandas as pd

from . import config

WEEKLY = "Weekly_Data_Tabular"
MONTHLY = "Monthly_Data_Tabular"
GROWTH = 1.02  # per-period multiplier on the cloned numeric column


def _csv(name):
    return config.data_dir() / f"{name}.csv"


def ensure_backup() -> None:
    bdir = config.original_backup_dir()
    bdir.mkdir(exist_ok=True)
    for name in (WEEKLY, MONTHLY):
        dst = bdir / f"{name}.csv"
        if not dst.exists():
            shutil.copy2(_csv(name), dst)


def has_backup() -> bool:
    bdir = config.original_backup_dir()
    return all((bdir / f"{n}.csv").exists() for n in (WEEKLY, MONTHLY))


def _append(name, date_col, value_col, new_dates):
    df = pd.read_csv(_csv(name))
    dts = pd.to_datetime(df[date_col])
    latest = df[dts == dts.max()].copy()
    frames = [df]
    for k, new_dt in enumerate(new_dates(dts.max()), start=1):
        blk = latest.copy()
        blk[date_col] = new_dt.strftime("%Y-%m-%d")
        blk[value_col] = (pd.to_numeric(blk[value_col], errors="coerce")
                          * (GROWTH ** k)).round(6)
        frames.append(blk)
    pd.concat(frames, ignore_index=True).to_csv(_csv(name), index=False)


def simulate() -> dict:
    ensure_backup()
    _append(WEEKLY, "WEEK_ENDING", "TRX_ADJUSTED",
            lambda m: [m + pd.Timedelta(days=7 * k) for k in range(1, 5)])
    _append(MONTHLY, "MONTH_DATE", "TRX_VOLUME",
            lambda m: [m + pd.offsets.MonthBegin(1)])
    # The frontend immediately calls refreshAll()/refresh-check, which re-reads
    # min/max via datasets.all_tables(); no need to re-parse both CSVs here.
    return {"ok": True}


def reset() -> bool:
    if not has_backup():
        return False
    bdir = config.original_backup_dir()
    for name in (WEEKLY, MONTHLY):
        shutil.copy2(bdir / f"{name}.csv", _csv(name))
    return True

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


def _append(name, date_col, value_col, new_dates) -> list:
    df = pd.read_csv(_csv(name))
    dts = pd.to_datetime(df[date_col])
    latest = df[dts == dts.max()].copy()
    frames, added = [df], []
    for k, new_dt in enumerate(new_dates(dts.max()), start=1):
        blk = latest.copy()
        stamp = new_dt.strftime("%Y-%m-%d")
        blk[date_col] = stamp
        blk[value_col] = (pd.to_numeric(blk[value_col], errors="coerce")
                          * (GROWTH ** k)).round(6)
        frames.append(blk)
        added.append(stamp)
    pd.concat(frames, ignore_index=True).to_csv(_csv(name), index=False)
    return added


def simulate(weeks: int = 4) -> dict:
    weeks = max(1, min(int(weeks), 8))
    ensure_backup()
    wk = _append(WEEKLY, "WEEK_ENDING", "TRX_ADJUSTED",
                 lambda m: [m + pd.Timedelta(days=7 * k) for k in range(1, weeks + 1)])
    mo = _append(MONTHLY, "MONTH_DATE", "TRX_VOLUME",
                 lambda m: [m + pd.offsets.MonthBegin(1)])
    return {"ok": True, "weekly_added": wk, "monthly_added": mo}


def reset() -> bool:
    """Restore originals AND delete the backup, so has_backup() doubles as
    the 'demo data active' indicator."""
    if not has_backup():
        return False
    bdir = config.original_backup_dir()
    for name in (WEEKLY, MONTHLY):
        shutil.copy2(bdir / f"{name}.csv", _csv(name))
        (bdir / f"{name}.csv").unlink()
    return True

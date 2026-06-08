#!/usr/bin/env python3
"""Extract one sheet of an .xlsx to CSV for the APEX deck skill.

Handles the common case where the real header is not on row 1 by scanning for
the first row that looks like a header (a 'Date'-like first cell or mostly text).

Usage:
    python xlsx_to_csv.py <file.xlsx> <SheetName> <out.csv> [--header-row N]
"""
import sys, csv, argparse
import openpyxl


def find_header_row(rows):
    for i, r in enumerate(rows):
        if not r:
            continue
        first = r[0]
        if isinstance(first, str) and first.strip().lower() in ("date", "week", "period", "month"):
            return i
        # fallback: first row that is mostly non-empty strings
        nonempty = [c for c in r if c not in (None, "")]
        texty = [c for c in nonempty if isinstance(c, str)]
        if len(nonempty) >= 3 and len(texty) >= len(nonempty) // 2:
            return i
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx")
    ap.add_argument("sheet")
    ap.add_argument("out")
    ap.add_argument("--header-row", type=int, default=None,
                    help="0-indexed header row; auto-detected if omitted")
    a = ap.parse_args()

    wb = openpyxl.load_workbook(a.xlsx, data_only=True)
    if a.sheet not in wb.sheetnames:
        sys.exit(f"Sheet '{a.sheet}' not found. Available: {wb.sheetnames}")
    ws = wb[a.sheet]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]

    h = a.header_row if a.header_row is not None else find_header_row(rows)
    header = rows[h]
    # keep only columns up to the last non-empty header cell
    last = max((i for i, v in enumerate(header) if v not in (None, "")), default=len(header) - 1)
    header = header[: last + 1]

    data = [r[: last + 1] for r in rows[h + 1:] if r and r[0] not in (None, "")]

    with open(a.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([str(c) if c is not None else "" for c in header])
        for r in data:
            w.writerow([c if c is not None else "" for c in r])
    print(f"wrote {a.out}: {len(data)} rows, {len(header)} cols (header row {h})")


if __name__ == "__main__":
    main()

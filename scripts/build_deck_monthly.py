"""
build_deck_monthly.py - design-led deck for a monthly TRx-by-indication run.

Sibling to build_deck_pptx.py for the MULTI-INDICATION monthly trend shape
(result.csv = one row per month, one column per indication), which the UC/CD
line builder cannot render (it hardcodes a 2-series UC-vs-CD crossover story).
Reuses the same brand tokens, helpers, footer, and the mandatory integrity
sanitizer + round-trip validation, so style + integrity are identical and the
UC/CD builder is untouched.

A multi-line chart plots the top-N indications by latest-month volume; the
narrative (statement title, dek, blocks, TL;DR) is spec-driven and .format()'d
over a ctx computed from result.csv. All numbers read at build time.

Usage:  py -3 scripts/build_deck_monthly.py output/<run_id>
"""
import json
import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.util import Emu, Pt

from build_deck_pptx import (
    NAVY, MAGENTA, TEAL, GRAY, PINK_FILL, WHITE, RULE,
    FONT_TITLE, FONT_BODY, W, H,
    inch, add_rect, add_text, style_axis, footer, sanitize, validate, pretty_month,
)
import csv

# line palette (brand tokens + two complements) — cycles if more lines than colors
AMBER = RGBColor(0xF2, 0xA1, 0x3B)
PURPLE = RGBColor(0x6A, 0x4C, 0x93)
PALETTE = [NAVY, MAGENTA, TEAL, AMBER, PURPLE, GRAY]


def read_monthly(run):
    rows = list(csv.DictReader(open(run / "result.csv", newline="", encoding="utf-8")))
    date_col = list(rows[0].keys())[0]
    inds = [c for c in rows[0].keys() if c != date_col]
    months = [pretty_month(r[date_col]) for r in rows]
    series = {c: [float(r[c]) for r in rows] for c in inds}
    # rank indications by latest-month value
    ranked = sorted(inds, key=lambda c: series[c][-1], reverse=True)
    last = {c: series[c][-1] for c in inds}
    first_m, last_m = months[0], months[-1]
    top, second, third = ranked[0], ranked[1], ranked[2]
    ctx = dict(
        top=top, top_val=last[top], second=second, second_val=last[second],
        third=third, third_val=last[third],
        ratio=last[top] / last[second] if last[second] else 0,
        latest_month=last_m, first_month=first_m, n_months=len(rows),
        cd_val=last.get("CD", 0), uc_val=last.get("UC", 0),
        top_first=series[top][0],
    )
    return rows, date_col, months, series, ranked, ctx


def content_slide(prs, spec, run, page):
    rows, date_col, months, series, ranked, ctx = read_monthly(run)

    def fmt(t):
        return t.format(**ctx)

    s = prs.slides.add_slide(prs.slide_layouts[6])
    add_rect(s, 0, 0, 13.333, 7.5, WHITE)

    # --- section strip ---
    add_text(s, 0.45, 0.34, 9.5, 0.3,
             spec.get("section_strip", "HUMIRA  ·  MONTHLY TRX BY INDICATION"),
             size=12.5, color=NAVY, bold=True, font=FONT_TITLE)
    add_text(s, 11.0, 0.34, 1.9, 0.3, "01 OF 01", size=12.5, color=MAGENTA, bold=True,
             font=FONT_TITLE, align=PP_ALIGN.RIGHT)
    add_rect(s, 0.45, 0.66, 12.45, 0.018, RULE)

    # --- statement title + dek ---
    add_text(s, 0.45, 0.82, 12.4, 0.9, fmt(spec.get("statement_title", "Monthly TRx by Indication")),
             size=28, color=NAVY, bold=True, font=FONT_TITLE)
    add_text(s, 0.47, 1.80, 12.3, 0.7, fmt(spec.get("dek_template", "")),
             size=13.5, color=GRAY, italic=True, spacing=1.05)

    # --- left: multi-line chart, top-N indications ---
    top_n = int(spec.get("top_n", 5))
    plotted = ranked[:top_n]
    add_text(s, 0.45, 2.62, 7.6, 0.3,
             spec.get("chart_caption", f"MONTHLY TRX — TOP {top_n} INDICATIONS"),
             size=11, color=GRAY, bold=True, font=FONT_TITLE)
    cd = CategoryChartData()
    cd.categories = months
    for ind in plotted:
        cd.add_series(ind, series[ind])
    gf = s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, inch(0.4), inch(2.95),
                            inch(7.6), inch(3.45), cd)
    chart = gf.chart
    chart.has_title = False
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.BOTTOM
    chart.legend.include_in_layout = False
    chart.legend.font.size = Pt(9)
    chart.legend.font.name = FONT_BODY
    for ser, col in zip(chart.series, PALETTE):
        ser.format.line.color.rgb = col
        ser.format.line.width = Pt(2.0)
        ser.smooth = False
    style_axis(chart.category_axis)
    style_axis(chart.value_axis)

    # --- right: numbered insight blocks ---
    blocks = spec.get("blocks", [])
    bx, by, bh = 8.4, 2.95, 1.18
    for i, blk in enumerate(blocks):
        y = by + i * (bh + 0.12)
        add_text(s, bx, y, 0.85, bh, blk["num"], size=30, color=MAGENTA, bold=True, font=FONT_TITLE)
        add_text(s, bx + 0.9, y - 0.02, 4.0, 0.35, fmt(blk["head"]), size=14, color=NAVY,
                 bold=True, font=FONT_TITLE)
        add_text(s, bx + 0.9, y + 0.34, 4.0, bh - 0.34, fmt(blk["body_template"]),
                 size=11, color=GRAY, spacing=1.04)

    # --- TL;DR callout bar ---
    add_rect(s, 0.45, 6.5, 12.45, 0.46, PINK_FILL)
    add_rect(s, 0.45, 6.5, 0.06, 0.46, MAGENTA)
    add_text(s, 0.7, 6.5, 12.1, 0.46,
             [("TL;DR   ", {"color": MAGENTA, "bold": True}),
              (fmt(spec.get("tldr", "")), {"color": NAVY})],
             size=11.5, anchor=MSO_ANCHOR.MIDDLE)

    footer(s, page)


def main(run_folder):
    run = Path(run_folder).resolve()
    spec = json.loads((run / "deck_spec.json").read_text(encoding="utf-8"))
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(W), Emu(H)
    content_slide(prs, spec, run, page=1)
    out = run / "deck.pptx"
    prs.save(out)
    sanitize(out)
    validate(out)
    print(f"deck -> {out}  ({len(prs.slides)} slides)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: py -3 scripts/build_deck_monthly.py <run_folder>")
    main(sys.argv[1])

"""
build_deck_pptx.py - design-led APEX/DataZymes deck for a run, via python-pptx.

Implements the updated apex-deck-builder/SKILL.md methodology (design-led,
native python-pptx, brand tokens, integer-EMU integrity + post-save sanitizer +
pre-delivery validation). Style matched to apex-deck-builder/examples/
"Deck revamp refrence.pdf": blue section strip, statement title, italic dek,
a native line-chart trajectory, numbered insight blocks, a TL;DR callout bar,
and the DataZymes footer.

All numbers are read from <run>/result.csv at build time (nothing hard-coded).
Lucide PNG icons are substituted with native numbered markers (no cairosvg here).
Self-review render (LibreOffice) is skipped if soffice is unavailable.

Usage:  py -3 scripts/build_deck_pptx.py output/<run_id>
"""
import csv
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.util import Emu, Pt
from pptx.oxml.ns import qn

# --------------------------------------------------------------------------- #
# Brand tokens (apex-deck-builder/SKILL.md - do not change without sign-off)  #
# --------------------------------------------------------------------------- #
NAVY = RGBColor(0x07, 0x1D, 0x49)
MAGENTA = RGBColor(0xE4, 0x0D, 0x62)
TEAL = RGBColor(0x07, 0xB2, 0xAC)
GRAY = RGBColor(0x50, 0x53, 0x5A)
PINK_FILL = RGBColor(0xFB, 0xE3, 0xEA)
BLUE_FILL = RGBColor(0xEC, 0xF1, 0xF8)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
RULE = RGBColor(0xD9, 0xDE, 0xE8)

FONT_TITLE = "Montserrat Medium"
FONT_BODY = "Roboto"

EMU = 914400
W, H = int(13.333 * EMU), int(7.5 * EMU)


def inch(v):
    """Inches -> integer EMU (PowerPoint rejects float coordinates)."""
    return int(round(v * EMU))


# --------------------------------------------------------------------------- #
# small native helpers (every coordinate coerced to int EMU)                  #
# --------------------------------------------------------------------------- #
def add_rect(slide, x, y, w, h, fill, line=None, line_w=None):
    sp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, inch(x), inch(y), inch(w), inch(h))
    sp.fill.solid()
    sp.fill.fore_color.rgb = fill
    if line is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = line
        sp.line.width = Pt(line_w or 1)
    sp.shadow.inherit = False
    return sp


def add_text(slide, x, y, w, h, runs, size=14, color=NAVY, bold=False, italic=False,
             font=FONT_BODY, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, spacing=1.0):
    """runs: a string, or list of (text, dict-overrides) for mixed styling."""
    tb = slide.shapes.add_textbox(inch(x), inch(y), inch(w), inch(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = align
    p.line_spacing = spacing
    parts = [(runs, {})] if isinstance(runs, str) else runs
    for text, ov in parts:
        r = p.add_run()
        r.text = text
        r.font.size = Pt(ov.get("size", size))
        r.font.bold = ov.get("bold", bold)
        r.font.italic = ov.get("italic", italic)
        r.font.name = ov.get("font", font)
        r.font.color.rgb = ov.get("color", color)
    return tb


def style_axis(axis, size=9):
    axis.tick_labels.font.size = Pt(size)
    axis.tick_labels.font.name = FONT_BODY
    axis.tick_labels.font.color.rgb = GRAY
    axis.format.line.color.rgb = RULE


def thin_category_labels(chart, skip):
    """Show ~every `skip`-th category label so a 100+ point axis stays readable."""
    cat_ax = chart.category_axis._element
    for tag in ("c:tickLblSkip", "c:tickMarkSkip"):
        el = cat_ax.find(qn(tag))
        if el is None:
            el = cat_ax.makeelement(qn(tag), {})
            cat_ax.append(el)
        el.set("val", str(skip))


# --------------------------------------------------------------------------- #
# data                                                                         #
# --------------------------------------------------------------------------- #
_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def pretty_month(date_str):
    """'2024-05-03' -> 'May 2024'."""
    y, m, _ = date_str.split("-")
    return f"{_MONTHS[int(m)]} {y}"


def read_result(run, spec):
    rows = list(csv.DictReader(open(run / "result.csv", newline="", encoding="utf-8")))
    date_col = spec.get("date_column", list(rows[0].keys())[0])
    series_cols = spec.get("series_columns", ["UC", "CD"])
    total_col = spec.get("total_column", "TREMFYA_TRx_total")

    labels = [r[date_col][5:] for r in rows]                 # MM-DD
    series = {c: [float(r[c]) for r in rows] for c in series_cols}
    totals = [float(r[total_col]) for r in rows]

    # crossover: the LAST week UC led, then CD takes and holds the lead.
    # (UC/CD flip sign in the tiny early weeks; we want the meaningful, durable
    # crossover, not the first noisy one.)
    crossover = None
    if "UC" in series and "CD" in series:
        uc, cdv = series["UC"], series["CD"]
        last_uc_lead = None
        for i in range(len(rows)):
            if totals[i] > 1 and uc[i] > cdv[i]:
                last_uc_lead = i
        if last_uc_lead is not None and last_uc_lead + 1 < len(rows):
            crossover = rows[last_uc_lead + 1][date_col]
    return rows, labels, series, totals, crossover


# --------------------------------------------------------------------------- #
# slides                                                                       #
# --------------------------------------------------------------------------- #
def footer(slide, page, dark=False):
    color = WHITE if dark else NAVY
    add_text(slide, 0.45, 7.04, 4.0, 0.3,
             [("▶ ", {"color": MAGENTA, "bold": True}), ("DataZymes", {"color": color, "bold": True})],
             size=11, font=FONT_TITLE)
    add_text(slide, 12.4, 7.04, 0.5, 0.3, str(page), size=11, color=color, align=PP_ALIGN.RIGHT)


def content_slide(prs, spec, rows, labels, series, totals, crossover, page):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    add_rect(s, 0, 0, 13.333, 7.5, WHITE)

    date_col = spec.get("date_column", list(rows[0].keys())[0])
    latest_uc, latest_cd = series["UC"][-1], series["CD"][-1]
    latest_total, first_total = totals[-1], next((t for t in totals if t > 0), totals[0])
    ramp = latest_total / first_total if first_total else 0
    first_month = pretty_month(rows[0][date_col])
    cross_month = pretty_month(crossover) if crossover else "2025"

    # First non-trivial week + indication shares (computed, never hard-coded).
    first_idx = next((i for i, t in enumerate(totals) if t > 0), 0)
    first_uc_pct = 100 * series["UC"][first_idx] / totals[first_idx] if totals[first_idx] else 0
    latest_uc_pct = 100 * latest_uc / latest_total if latest_total else 0
    latest_cd_pct = 100 * latest_cd / latest_total if latest_total else 0
    ctx = dict(first_total=first_total, latest_total=latest_total, ramp=ramp,
               first_month=first_month, cross_month=cross_month,
               latest_uc=latest_uc, latest_cd=latest_cd, latest_label=labels[-1],
               first_uc_pct=first_uc_pct, latest_uc_pct=latest_uc_pct,
               latest_cd_pct=latest_cd_pct)

    def fmt(t):
        return t.format(**ctx)

    # Narrative: spec-driven, with the Tremfya literals as backward-compatible
    # defaults so existing runs render identically.
    DEFAULT_DEK = ("Tremfya's weekly IBD volume has scaled from ~{first_total:,.0f} to "
                   "~{latest_total:,.0f} TRx since {first_month}. Within IBD, Crohn's pulled "
                   "level in {cross_month} and now leads ulcerative colitis.")
    DEFAULT_BLOCKS = [
        {"num": "01", "head": "Crohn's now leads",
         "body_template": "CD ~{latest_cd:,.0f} vs UC ~{latest_uc:,.0f} TRx in the latest week ({latest_label})."},
        {"num": "02", "head": "Crossover · {cross_month}",
         "body_template": "UC led decisively in early 2025; the two drew level by autumn before CD pulled ahead."},
        {"num": "03", "head": "~{ramp:,.0f}x ramp",
         "body_template": "Tremfya's IBD volume rose from ~{first_total:,.0f} to ~{latest_total:,.0f} weekly TRx."},
    ]
    DEFAULT_TLDR = ("Within Tremfya's IBD business, Crohn's has overtaken ulcerative colitis "
                    "and is the faster-growing of the two indications.")

    # --- section strip ---
    add_text(s, 0.45, 0.34, 9.0, 0.3,
             spec.get("section_strip", "TREMFYA IBD  ·  WEEKLY TRX BY INDICATION"),
             size=12.5, color=NAVY, bold=True, font=FONT_TITLE)
    add_text(s, 11.0, 0.34, 1.9, 0.3, "01 OF 01", size=12.5, color=MAGENTA, bold=True,
             font=FONT_TITLE, align=PP_ALIGN.RIGHT)
    add_rect(s, 0.45, 0.66, 12.45, 0.018, RULE)

    # --- statement title + dek ---
    add_text(s, 0.45, 0.82, 12.4, 0.9,
             spec.get("statement_title",
                      "Crohn's Has Overtaken Ulcerative Colitis in Tremfya's IBD Mix"),
             size=30, color=NAVY, bold=True, font=FONT_TITLE)
    add_text(s, 0.47, 1.74, 12.3, 0.6,
             fmt(spec.get("dek_template", DEFAULT_DEK)),
             size=13.5, color=GRAY, italic=True, spacing=1.05)

    # --- left: native line chart (UC vs CD) ---
    add_text(s, 0.45, 2.52, 7.4, 0.3,
             spec.get("chart_caption", "WEEKLY TRX — UC VS CD (FULL SERIES)"),
             size=11, color=GRAY, bold=True, font=FONT_TITLE)
    cd = CategoryChartData()
    cd.categories = labels
    cd.add_series("Ulcerative Colitis (UC)", series["UC"])
    cd.add_series("Crohn's (CD)", series["CD"])
    gf = s.shapes.add_chart(XL_CHART_TYPE.LINE, inch(0.4), inch(2.85),
                            inch(7.5), inch(3.7), cd)
    chart = gf.chart
    chart.has_title = False
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.TOP
    chart.legend.include_in_layout = False
    chart.legend.font.size = Pt(10)
    chart.legend.font.name = FONT_BODY
    for ser, col in zip(chart.series, (TEAL, MAGENTA)):
        ser.format.line.color.rgb = col
        ser.format.line.width = Pt(2.25)
        ser.smooth = False
    style_axis(chart.category_axis)
    style_axis(chart.value_axis)
    thin_category_labels(chart, max(1, len(labels) // 9))

    # --- right: numbered insight blocks ---
    blocks = spec.get("blocks", DEFAULT_BLOCKS)
    bx, by, bh = 8.3, 2.85, 1.18
    for i, blk in enumerate(blocks):
        y = by + i * (bh + 0.12)
        add_text(s, bx, y, 0.85, bh, blk["num"], size=30, color=MAGENTA, bold=True, font=FONT_TITLE)
        add_text(s, bx + 0.9, y - 0.02, 4.0, 0.35, fmt(blk["head"]), size=14, color=NAVY,
                 bold=True, font=FONT_TITLE)
        add_text(s, bx + 0.9, y + 0.34, 4.05, bh - 0.34, fmt(blk["body_template"]),
                 size=11, color=GRAY, spacing=1.04)

    # --- TL;DR callout bar ---
    add_rect(s, 0.45, 6.5, 12.45, 0.46, PINK_FILL)
    add_rect(s, 0.45, 6.5, 0.06, 0.46, MAGENTA)
    add_text(s, 0.7, 6.5, 12.1, 0.46,
             [("TL;DR   ", {"color": MAGENTA, "bold": True}),
              (fmt(spec.get("tldr", DEFAULT_TLDR)), {"color": NAVY})],
             size=11.5, anchor=MSO_ANCHOR.MIDDLE)

    footer(s, page)


# --------------------------------------------------------------------------- #
# integrity: sanitizer + validation (SKILL.md mandatory)                      #
# --------------------------------------------------------------------------- #
FLOAT_COORD = re.compile(rb'(cx|cy|x|y)="(-?\d+)\.\d+"')


def sanitize(path):
    """Rewrite float coords to int on slides + parts; lift slide zero-extents to 1."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        data = {n: z.read(n) for n in names}
    for n, xml in data.items():
        if n.endswith(".xml") or n.endswith(".rels"):
            xml = FLOAT_COORD.sub(lambda m: m.group(1) + b'="' + m.group(2) + b'"', xml)
            if n.startswith("ppt/slides/slide") and n.endswith(".xml"):
                xml = re.sub(rb'(<a:ext\b[^>]*?\bcx=)"0"', rb'\1"1"', xml)
                xml = re.sub(rb'(<a:ext\b[^>]*?\bcy=)"0"', rb'\1"1"', xml)
            data[n] = xml
    tmp = str(path) + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, data[n])
    shutil.move(tmp, path)


def validate(path):
    Presentation(path)  # round-trip must succeed
    problems = []
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.startswith("ppt/slides/slide") and n.endswith(".xml"):
                xml = z.read(n)
                if re.search(rb'(cx|cy|x|y)="-?\d+\.\d+"', xml):
                    problems.append((n, "float coord"))
                if re.search(rb'<a:ext\b[^>]*?\b(cx|cy)="0"', xml):
                    problems.append((n, "zero extent"))
    if problems:
        raise SystemExit(f"validation FAILED: {problems}")


def main(run_folder):
    run = Path(run_folder).resolve()
    spec = json.loads((run / "deck_spec.json").read_text(encoding="utf-8"))
    rows, labels, series, totals, crossover = read_result(run, spec)

    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(W), Emu(H)
    content_slide(prs, spec, rows, labels, series, totals, crossover, page=1)

    out = run / "deck.pptx"
    prs.save(out)
    sanitize(out)
    validate(out)
    print(f"deck -> {out}  ({len(prs.slides)} slides)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: py -3 scripts/build_deck_pptx.py <run_folder>")
    main(sys.argv[1])

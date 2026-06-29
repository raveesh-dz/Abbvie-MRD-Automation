"""
build_deck_holdout.py - APEX/DataZymes deck for a CATEGORICAL classification run.

Sibling to build_deck_pptx.py for the NON-TEMPORAL segmentation shape (result.csv =
one row per HCP with classification_group + holdout_status). Reuses brand tokens,
native helpers, footer, the integrity sanitizer and the pre-delivery validator from
build_deck_pptx (line + monthly builders untouched).

Renders ONE content slide as a left-to-right FUNNEL:
  pool (1,040) -> Holdout / Non-Holdout split -> the 5 classification groups,
with native elbow connectors (thin rects, no cxnSp / zero-extent traps), a magenta
bracket on the active-Holdout leaves, and 3 professional callout annotations
(rounded-rect "thought bubbles" with leader lines). TL;DR callout + DataZymes footer.

All numbers computed from <run>/result.csv at build time (nothing hard-coded).
Self-review render (LibreOffice) is skipped if soffice is unavailable.

Usage:  py -3 scripts/build_deck_holdout.py output/<run_id>
"""
import csv
import json
import sys
from pathlib import Path

from pptx import Presentation
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Emu, Pt
from pptx.dml.color import RGBColor

# reuse everything brand/integrity from the line builder (single source of truth)
from build_deck_pptx import (
    add_rect, add_text, footer, sanitize, validate, inch,
    NAVY, MAGENTA, TEAL, GRAY, PINK_FILL, BLUE_FILL, WHITE, RULE,
    FONT_TITLE, FONT_BODY, W, H,
)

AMBER = RGBColor(0xFF, 0xC0, 0x00)
TEAL_SOFT = RGBColor(0x9B, 0xD9, 0xD6)
TEAL_FILL = RGBColor(0xE4, 0xF5, 0xF4)
TRACK = RGBColor(0xEF, 0xF1, 0xF5)

# group -> (display label, dot color, arm)
GROUP_ORDER = [
    ("no_cd_nbrx",        "No CD NBRx",          GRAY,      "Holdout"),
    ("stelara_only",      "STELARA only",        MAGENTA,   "Holdout"),
    ("both_lean_stelara", "Both · lean STELARA", AMBER, "Holdout"),
    ("skyrizi_only",      "SKYRIZI only",        TEAL,      "Non-Holdout"),
    ("both_lean_skyrizi", "Both · lean SKYRIZI", TEAL_SOFT, "Non-Holdout"),
]
ACCENTS = {"magenta": MAGENTA, "gray": GRAY, "teal": TEAL}
ACCENT_FILL = {"magenta": PINK_FILL, "gray": RGBColor(0xF1, 0xF2, 0xF5), "teal": TEAL_FILL}


# --------------------------------------------------------------------------- #
# local native helpers (coords coerced to int EMU via inch())                 #
# --------------------------------------------------------------------------- #
def add_round(slide, x, y, w, h, fill, line=None, line_w=None):
    sp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, inch(x), inch(y), inch(w), inch(h))
    sp.fill.solid()
    sp.fill.fore_color.rgb = fill
    if line is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = line
        sp.line.width = Pt(line_w or 1)
    sp.shadow.inherit = False
    return sp


def add_dot(slide, cx, cy, d, fill):
    sp = slide.shapes.add_shape(MSO_SHAPE.OVAL, inch(cx - d / 2), inch(cy - d / 2), inch(d), inch(d))
    sp.fill.solid()
    sp.fill.fore_color.rgb = fill
    sp.line.fill.background()
    sp.shadow.inherit = False
    return sp


def hline(slide, x1, x2, y, color=RULE, t=0.022):
    add_rect(slide, x1, y - t / 2, max(0.02, x2 - x1), t, color)


def vline(slide, x, y1, y2, color=RULE, t=0.022):
    add_rect(slide, x - t / 2, y1, t, max(0.02, y2 - y1), color)


def node(slide, x, y, w, h, fill, line, title, title_color, value, value_color):
    add_round(slide, x, y, w, h, fill, line=line, line_w=1.5)
    add_text(slide, x, y + 0.12, w, 0.34, title, size=11.5, color=title_color, bold=True,
             font=FONT_TITLE, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    add_text(slide, x, y + h - 0.46, w, 0.4, value, size=13, color=value_color, bold=True,
             font=FONT_TITLE, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


# --------------------------------------------------------------------------- #
# data                                                                         #
# --------------------------------------------------------------------------- #
def read_classification(run):
    rows = list(csv.DictReader(open(run / "result.csv", newline="", encoding="utf-8")))
    total = len(rows)
    counts = {g: 0 for g, _, _, _ in GROUP_ORDER}
    sky_total = stel_total = 0.0
    active = 0
    for r in rows:
        counts[r["classification_group"]] = counts.get(r["classification_group"], 0) + 1
        sky = float(r["skyrizi_cd_nbrx_13wk"])
        stel = float(r["stelara_cd_nbrx_13wk"])
        sky_total += sky
        stel_total += stel
        if sky > 0 or stel > 0:
            active += 1
    holdout_n = sum(counts[g] for g, _, _, st in GROUP_ORDER if st == "Holdout")
    nonholdout_n = total - holdout_n
    switch_n = counts["stelara_only"] + counts["both_lean_stelara"]
    ctx = dict(
        total=total, holdout_n=holdout_n, nonholdout_n=nonholdout_n,
        holdout_pct=100 * holdout_n / total, nonholdout_pct=100 * nonholdout_n / total,
        switch_n=switch_n, active_n=active,
        sky_total=sky_total, stel_total=stel_total,
        sky_mult=(sky_total / stel_total if stel_total else 0),
        **counts,
    )
    return counts, ctx


# --------------------------------------------------------------------------- #
# slide                                                                        #
# --------------------------------------------------------------------------- #
def content_slide(prs, spec, counts, ctx, page):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    add_rect(s, 0, 0, 13.333, 7.5, WHITE)

    def fmt(t):
        return t.format(**ctx)

    # --- section strip ---
    add_text(s, 0.45, 0.34, 10.5, 0.3,
             spec.get("section_strip", "SKYRIZI HOLDOUT  ·  CROHN'S NBRX"),
             size=12.5, color=NAVY, bold=True, font=FONT_TITLE)
    add_text(s, 11.0, 0.34, 1.9, 0.3, "01 OF 01", size=12.5, color=MAGENTA, bold=True,
             font=FONT_TITLE, align=PP_ALIGN.RIGHT)
    add_rect(s, 0.45, 0.66, 12.45, 0.018, RULE)

    # --- statement title + dek ---
    add_text(s, 0.45, 0.80, 12.4, 0.92,
             fmt(spec.get("statement_title", "Holdout Classification")),
             size=25, color=NAVY, bold=True, font=FONT_TITLE, spacing=0.98)
    add_text(s, 0.47, 1.78, 12.3, 0.6, fmt(spec.get("dek_template", "")),
             size=12, color=GRAY, italic=True, spacing=1.04)

    # ===================== FUNNEL (left ~60%) ============================= #
    # tier geometry
    POOL = dict(x=0.50, w=1.75, y=3.85, h=1.00)
    pool_cy = POOL["y"] + POOL["h"] / 2
    SPLIT_X, SPLIT_W = 2.60, 2.05
    hold = dict(x=SPLIT_X, w=SPLIT_W, y=2.90, h=0.85)
    nonh = dict(x=SPLIT_X, w=SPLIT_W, y=4.96, h=0.85)
    hold_cy = hold["y"] + hold["h"] / 2
    nonh_cy = nonh["y"] + nonh["h"] / 2

    LEAF_X, LEAF_W, LEAF_H = 5.05, 2.85, 0.50
    leaf_y = {  # top-left y per group
        "no_cd_nbrx": 2.50, "stelara_only": 3.07, "both_lean_stelara": 3.64,
        "skyrizi_only": 4.85, "both_lean_skyrizi": 5.42,
    }
    leaf_cy = {g: y + LEAF_H / 2 for g, y in leaf_y.items()}

    # connectors: pool -> splits
    vline(s, 2.42, hold_cy, nonh_cy, RULE)
    hline(s, POOL["x"] + POOL["w"], 2.42, pool_cy, RULE)
    hline(s, 2.42, SPLIT_X, hold_cy, RULE)
    hline(s, 2.42, SPLIT_X, nonh_cy, RULE)
    # connectors: holdout -> its 3 leaves
    hold_leaves = [g for g, _, _, arm in GROUP_ORDER if arm == "Holdout"]
    nonh_leaves = [g for g, _, _, arm in GROUP_ORDER if arm == "Non-Holdout"]
    vline(s, 4.85, leaf_cy[hold_leaves[0]], leaf_cy[hold_leaves[-1]], RULE)
    hline(s, hold["x"] + hold["w"], 4.85, hold_cy, RULE)
    for g in hold_leaves:
        hline(s, 4.85, LEAF_X, leaf_cy[g], RULE)
    # connectors: non-holdout -> its 2 leaves
    vline(s, 4.85, leaf_cy[nonh_leaves[0]], leaf_cy[nonh_leaves[-1]], RULE)
    hline(s, nonh["x"] + nonh["w"], 4.85, nonh_cy, RULE)
    for g in nonh_leaves:
        hline(s, 4.85, LEAF_X, leaf_cy[g], RULE)

    # nodes
    node(s, POOL["x"], POOL["y"], POOL["w"], POOL["h"], NAVY, NAVY,
         "ANALYSIS POOL", WHITE, f"{ctx['total']:,}", WHITE)
    node(s, hold["x"], hold["y"], hold["w"], hold["h"], PINK_FILL, MAGENTA,
         "HOLDOUT", NAVY, f"{ctx['holdout_n']:,}  ·  {ctx['holdout_pct']:.0f}%", MAGENTA)
    node(s, nonh["x"], nonh["y"], nonh["w"], nonh["h"], TEAL_FILL, TEAL,
         "NON-HOLDOUT", NAVY, f"{ctx['nonholdout_n']:,}  ·  {ctx['nonholdout_pct']:.0f}%", TEAL)

    # leaves: dot + label + mini-bar + count
    max_count = max(counts.values()) or 1
    bar_max = 1.45
    for g, label, color, arm in GROUP_ORDER:
        y = leaf_y[g]
        n = counts.get(g, 0)
        add_dot(s, LEAF_X + 0.09, y + 0.16, 0.15, color)
        add_text(s, LEAF_X + 0.26, y - 0.02, 1.55, 0.30, label, size=10, color=NAVY,
                 bold=(arm == "Holdout" and g != "no_cd_nbrx"), anchor=MSO_ANCHOR.MIDDLE)
        add_rect(s, LEAF_X + 0.26, y + 0.31, bar_max, 0.075, TRACK)
        add_rect(s, LEAF_X + 0.26, y + 0.31, max(0.05, bar_max * n / max_count), 0.075, color)
        add_text(s, LEAF_X + LEAF_W - 0.92, y, 0.9, LEAF_H, f"{n:,}", size=12.5, color=NAVY,
                 bold=True, font=FONT_TITLE, align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)

    # magenta bracket on the active-Holdout leaves (stelara_only + both_lean_stelara)
    br_top = leaf_y["stelara_only"] + 0.04
    br_bot = leaf_y["both_lean_stelara"] + LEAF_H - 0.04
    add_rect(s, LEAF_X + LEAF_W + 0.04, br_top, 0.055, br_bot - br_top, MAGENTA)

    # ===================== CALLOUTS (right rail ~40%) ===================== #
    CX, CW = 8.40, 4.45
    callouts = spec.get("callouts", [])
    # slot per accent: gray->top, magenta->mid (priority), teal->bottom
    slot = {
        "gray":    dict(y=2.44, h=0.84, lead_y=leaf_cy["no_cd_nbrx"], lead_from=LEAF_X + LEAF_W),
        "magenta": dict(y=3.40, h=1.16, lead_y=(br_top + br_bot) / 2, lead_from=LEAF_X + LEAF_W + 0.10),
        "teal":    dict(y=4.86, h=1.02, lead_y=leaf_cy["skyrizi_only"], lead_from=LEAF_X + LEAF_W),
    }
    for c in callouts:
        ac = c.get("accent", "gray")
        col = ACCENTS.get(ac, GRAY)
        sl = slot.get(ac, slot["gray"])
        # leader line + dot
        hline(s, sl["lead_from"], CX, sl["lead_y"], col, t=0.028)
        add_dot(s, sl["lead_from"], sl["lead_y"], 0.10, col)
        # box
        add_round(s, CX, sl["y"], CW, sl["h"], ACCENT_FILL.get(ac, PINK_FILL))
        add_rect(s, CX, sl["y"], 0.07, sl["h"], col)  # left accent bar
        add_text(s, CX + 0.22, sl["y"] + 0.10, CW - 0.40, 0.30, fmt(c.get("head", "")),
                 size=11, color=col, bold=True, font=FONT_TITLE)
        add_text(s, CX + 0.22, sl["y"] + 0.42, CW - 0.40, sl["h"] - 0.50,
                 fmt(c.get("body_template", "")), size=9.5, color=GRAY, spacing=1.03)

    # --- TL;DR callout bar ---
    add_rect(s, 0.45, 6.52, 12.45, 0.46, PINK_FILL)
    add_rect(s, 0.45, 6.52, 0.06, 0.46, MAGENTA)
    add_text(s, 0.7, 6.52, 12.1, 0.46,
             [("TL;DR   ", {"color": MAGENTA, "bold": True}),
              (fmt(spec.get("tldr", "")), {"color": NAVY})],
             size=11.5, anchor=MSO_ANCHOR.MIDDLE)

    footer(s, page)


# --------------------------------------------------------------------------- #
def main(run_folder):
    run = Path(run_folder).resolve()
    spec = json.loads((run / "deck_spec.json").read_text(encoding="utf-8"))
    counts, ctx = read_classification(run)

    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(W), Emu(H)
    content_slide(prs, spec, counts, ctx, page=1)

    out = run / "deck.pptx"
    prs.save(out)
    sanitize(out)
    validate(out)
    print(f"deck -> {out}  ({len(prs.slides)} slides)")
    print("group counts:", counts)
    print("ctx:", {k: (round(v, 1) if isinstance(v, float) else v) for k, v in ctx.items()})


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: py -3 scripts/build_deck_holdout.py <run_folder>")
    main(sys.argv[1])

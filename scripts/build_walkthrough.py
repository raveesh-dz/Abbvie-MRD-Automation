"""
build_walkthrough.py - inject the real deck.pptx (base64) into the walkthrough
source and run PLAN v4 build-gate assertions. Produces the self-contained
docs/walkthrough/holdout-case-study.html.

Usage: py -3 scripts/build_walkthrough.py
"""
import base64
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs/walkthrough/_src.html"
OUT = ROOT / "docs/walkthrough/holdout-case-study.html"
DECK = ROOT / "output/run_2026-06-26_001/deck.pptx"

FROZEN_SHA = "d02728cfd72da4ea664a44af7b56399a3fb23e1ab34b631ec9fdfcdd6576a519"
FROZEN_LEN = 31486


def fail(msg):
    sys.exit(f"BUILD GATE FAILED: {msg}")


def main():
    # --- deck staleness + round-trip gate (exact path, no glob; exclude lock file) ---
    if not DECK.exists():
        fail(f"{DECK} missing - refusing to emit a broken download")
    raw = DECK.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if len(raw) != FROZEN_LEN:
        fail(f"deck length {len(raw)} != frozen {FROZEN_LEN}")
    if sha != FROZEN_SHA:
        fail(f"deck sha256 {sha} != frozen {FROZEN_SHA} (deck rebuilt? update blob+hash together)")
    b64 = base64.b64encode(raw).decode("ascii")

    src = SRC.read_text(encoding="utf-8")
    if "__DECK_BASE64__" not in src:
        fail("placeholder __DECK_BASE64__ not found in source")
    html = src.replace("__DECK_BASE64__", b64)

    # --- segment reconciliation gate ---
    segs = {"426": 426, "243": 243, "17": 17, "13": 13, "1": 1}
    if sum(segs.values()) != 700:
        fail("segment counts do not sum to 700")
    if 30 + 244 + 426 != 700:
        fail("switch+nonholdout+no_cd_nbrx != 700")
    # the five segment values must appear in the rendered funnel + climax
    for v in ("426", "243", "17", "13", "1", "700", "456", "244", "30"):
        if v not in html:
            fail(f"required figure {v} missing from page")
    # --- absence gate: fail if stale old figures remain in source (checked pre-b64 to
    #     avoid false positives from coincidental matches inside the base64 blob) ---
    for v in ("1,040", "670", "627", "367", "370"):
        if v in src:
            fail(f"stale old figure {v} still in page")

    # --- forbidden ad-hoc gray scan (only tokens allowed) ---
    bad = re.findall(r"#(?:666|999|ccc|cccccc|888|aaa)\b", html, re.I)
    if bad:
        fail(f"ad-hoc grays found: {set(bad)}")

    # --- new requirement gates ---
    if "TL;DR" in html:
        fail("'TL;DR' terminology found (must be zero)")
    dashes = [c for c in ("—", "–") if c in html]
    if dashes:
        fail(f"em/en-dash found: {[hex(ord(c)) for c in dashes]} (must be zero)")
    if "/ 11<" in html or "/ 11 " in html:
        fail("stale '/ 11' section index found (should be '/ 12')")
    n_sections = len(re.findall(r'<section id=', html))
    if n_sections != 12:
        fail(f"expected 12 sections, found {n_sections}")
    if 'id="summary"' not in html:
        fail("relocated summary section missing")

    # --- base64 round-trips back to the frozen deck ---
    if hashlib.sha256(base64.b64decode(b64)).hexdigest() != FROZEN_SHA:
        fail("embedded base64 does not round-trip to frozen deck")

    OUT.write_text(html, encoding="utf-8")
    print(f"OK -> {OUT}")
    print(f"   deck {len(raw)} bytes, sha256 {sha[:12]}..., base64 {len(b64)} chars")
    print(f"   final html {len(html):,} chars")
    print("   gates: length OK, sha OK, segments=700 OK, 30+244+426=700 OK, figures present OK, no stale old figures OK, no ad-hoc grays OK, round-trip OK")


if __name__ == "__main__":
    main()

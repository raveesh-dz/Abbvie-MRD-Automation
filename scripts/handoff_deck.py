"""
handoff_deck.py - pipeline output stage: render a run's result.csv as an APEX deck.

This is the bridge between the analysis output contract and the apex-deck-builder
skill. It reads a run folder's result.csv plus a small deck_spec.json, writes a
deck-ready table in the column shape the deck builder expects, then calls the
skill (deterministic mode) to produce deck.pptx inside the run folder.

deck_spec.json (in the run folder):
{
  "date_column": "WEEK_ENDING",                 # which result.csv column is the x-axis
  "title": "Tremfya SQ\\nIBD Performance",       # deck / divider title (\\n wraps)
  "subtitle": "Weekly TRx split by indication",
  "priorWeeks": 4,                              # lookback for the change column
  "column_map": {                               # result.csv column -> deck column
    "UC": "UC TRx",                             # deck names start with an indication
    "CD": "CD TRx",                             # token (UC/CD/IBD) so the builder
    "TREMFYA_TRx_total": "IBD TRx"              # auto-groups them into one chart
  }
}
Columns not listed in column_map are dropped from the deck.

Usage:  py -3 scripts/handoff_deck.py output/<run_id>
"""
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DECK_SKILL = PROJECT_ROOT / "apex-deck-builder"


def build_deck_table(run, spec):
    """Reshape result.csv into the deck builder's expected CSV (Date first)."""
    df = pd.read_csv(run / "result.csv")
    date_col = spec.get("date_column", df.columns[0])

    deck_table = pd.DataFrame({"Date": df[date_col]})
    for source_col, deck_col in spec["column_map"].items():
        deck_table[deck_col] = df[source_col]

    out_path = run / "deck_table.csv"
    deck_table.to_csv(out_path, index=False)
    return out_path


def run_deck_builder(run, deck_table, spec):
    """Call apex-deck-builder: CSV -> config.json -> deck.pptx."""
    # Spec for build_config.js (the date column is now literally "Date").
    build_spec = {
        "title": spec.get("title", "Performance"),
        "subtitle": spec.get("subtitle", ""),
        "dateColumn": "Date",
        "priorWeeks": spec.get("priorWeeks", 4),
    }
    build_spec_path = run / "deck_buildspec.json"
    build_spec_path.write_text(json.dumps(build_spec, indent=2))

    config_path = run / "deck_config.json"
    pptx_path = run / "deck.pptx"

    # node resolves pptxgenjs from apex-deck-builder/node_modules (require walks
    # up from the script's directory), so the working directory does not matter.
    subprocess.run(
        ["node", str(DECK_SKILL / "scripts" / "build_config.js"),
         str(deck_table), str(build_spec_path), str(config_path)],
        check=True,
    )
    subprocess.run(
        ["node", str(DECK_SKILL / "scripts" / "apex_deck.js"),
         str(config_path), str(pptx_path)],
        check=True,
    )
    return pptx_path


def main(run_folder):
    run = Path(run_folder).resolve()
    spec_path = run / "deck_spec.json"
    if not spec_path.exists():
        sys.exit(f"missing {spec_path} - write a deck_spec.json for this run first.")

    spec = json.loads(spec_path.read_text())
    deck_table = build_deck_table(run, spec)
    pptx_path = run_deck_builder(run, deck_table, spec)
    print(f"deck -> {pptx_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: py -3 scripts/handoff_deck.py <run_folder>")
    main(sys.argv[1])

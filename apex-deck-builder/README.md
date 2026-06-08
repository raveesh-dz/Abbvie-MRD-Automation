# APEX Deck Builder — skill package

Visual/output layer for the pipeline. Give it a processed periodic table; it
returns a branded APEX-template `.pptx`. Built from scratch with `pptxgenjs`, so
it has no dependency on any source template file.

## What your pipeline does with this

Drop this folder into your pipeline's `skills/` directory. At the output stage,
the agent (or a deterministic step) calls it. Two modes:

**Deterministic** — pass a CSV (+ optional `spec.json`):
```bash
node scripts/build_config.js handoff/table.csv spec.json config.json
NODE_PATH=$(npm root -g) node scripts/apex_deck.js config.json output/deck.pptx
```

**Agentic** — pass the request + table + `context.md`; the agent decides the slide
plan, writes a `config.json` to the schema in `SKILL.md`, then runs `apex_deck.js`.
An explicit config from the pipeline always overrides agent choices.

## The handoff contract this skill expects

From the upstream phase, in a folder the skill can read:
- `table.csv` (or an .xlsx + sheet name) — date column + numeric measure columns
- `context.md` — the request, column dictionary, business rules, historical refs

If only a CSV is available, the skill still produces a sensible deck via
auto-grouping (see `SKILL.md`).

## Install

```bash
npm install            # installs pptxgenjs (see package.json)
pip install openpyxl   # only needed for xlsx_to_csv.py
# LibreOffice + poppler only needed for the QA render step
```

## Files

```
apex-deck-builder/
  SKILL.md                  # how/when Claude Code uses this (read this first)
  README.md                 # this file
  package.json
  scripts/
    apex_deck.js            # config.json -> .pptx   (renderer + CLI)
    build_config.js         # CSV (+spec) -> config.json  (auto-builder)
    xlsx_to_csv.py          # extract a sheet to CSV
  examples/
    tremfya_weekly.csv      # worked example data (Sheet3 of the Tremfya file)
    spec.json               # example spec
    config.json             # generated config
    apex_demo.pptx          # generated deck
    sample_request.md       # example natural-language request for the agentic path
```

## Worked example (reproduces examples/apex_demo.pptx)

```bash
node scripts/build_config.js examples/tremfya_weekly.csv examples/spec.json examples/config.json
NODE_PATH=$(npm root -g) node scripts/apex_deck.js examples/config.json examples/apex_demo.pptx
```

Output: a divider + three chart slides (100mg, 200mg, Induction), each with UC/CD/IBD
lines and a latest-vs-4-weeks-prior summary table.

## Notes for the demo

- The skill is scoped to weekly indication/dose tables for this demo. The renderer
  is generic (any date column + numeric columns), but the auto-grouping logic is
  tuned to the UC/CD/IBD naming. Other shapes work best via an explicit `spec.json`.
- All numbers on the slides are computed from the input table at run time — nothing
  is hard-coded. If asked to run on a different table on the call, point it at the
  new CSV and it recomputes.

# Rename Gastro Universe + Subset Holdout to 700 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the gastro HCP universe dataset to `Gastro_prod_sales_260605`, subset `Holdout_HCP_Universe` to its first 700 rows, and propagate both changes through metadata, semantic rules, the historical run, the gated case-study, and MEMORY.

**Architecture:** This is a data/config migration, not feature code. The rename is a pure string substitution + two file renames; the subset is a `head` truncation + narrative edits. Downstream artifacts (the re-run output, the gated walkthrough) are regenerated, not hand-faked. Each task ends with the repo's own gate script (`validate_schema.py`, `validate_result.py`, `build_walkthrough.py`, `pytest`) as its test.

**Tech Stack:** Python 3.14 via `py -3` (pandas, pyyaml), Git Bash `sed`/`head`, python-pptx deck builder.

**Spec:** `docs/superpowers/specs/2026-06-29-rename-gastro-universe-subset-holdout-design.md`

## Global Constraints

- Python is invoked as **`py -3`** (the bare `python` is a broken Windows Store alias).
- Old table name (verbatim): `sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl`
- New table name (verbatim): `Gastro_prod_sales_260605`
- The internal key column `abv_customer_id` is **unchanged** — only the table name changes.
- Every `/semantic/` or `/metadata/` change is its own git commit (`rule: <ID> …` for rule edits, descriptive message otherwise). Never `--amend` a published commit.
- Never hand-edit `result.csv` — regenerate it by running `analysis_code.py`.
- `holdout-case-study.html` is **generated** — never hand-edit it; edit `_src.html` + `build_walkthrough.py` and rebuild.
- Do NOT touch `_reference/`, `.playwright-mcp/`, `scratch_final_plan.md`, `apex-deck-builder/examples/` (the `670.x` floats there are unrelated chart data).
- Run all commands from the repo root: `C:\Users\RounakSuranshe\Documents\Projects\Abbvie-MRD-Automation`.

---

### Task 1: Rename the gastro universe everywhere it is a pure string swap

Renames the CSV + dictionary and swaps the table name across metadata, semantic
rules, and the historical run's code/plan. MEMORY.md is intentionally deferred to
Task 5 (edited there as one coherent narrative pass).

**Files:**
- Rename: `data/sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl.csv` → `data/Gastro_prod_sales_260605.csv`
- Rename: `metadata/sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl.yaml` → `metadata/Gastro_prod_sales_260605.yaml`
- Modify (string swap): `metadata/relationships.yaml`, `metadata/HCP_demographics.yaml`, `metadata/Holdout_HCP_Universe.yaml`, the renamed gastro `.yaml` (its `table:` field), `semantic/metrics.md`, `semantic/context.md`, `semantic/filters.md`, `semantic/time.md`, `output/run_2026-06-26_001/analysis_code.py`, `output/run_2026-06-26_001/analysis_plan.md`

**Interfaces:**
- Produces: a `data/Gastro_prod_sales_260605.csv` whose dictionary `metadata/Gastro_prod_sales_260605.yaml` has `table: Gastro_prod_sales_260605`. Consumed by Task 3's re-run (read path) and the schema gate.

- [ ] **Step 1: Swap the table name in every config + run-folder file (content edit, before the file renames)**

```bash
cd "C:/Users/RounakSuranshe/Documents/Projects/Abbvie-MRD-Automation"
OLD='sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl'
NEW='Gastro_prod_sales_260605'
for f in \
  metadata/relationships.yaml \
  metadata/HCP_demographics.yaml \
  metadata/Holdout_HCP_Universe.yaml \
  "metadata/${OLD}.yaml" \
  semantic/metrics.md \
  semantic/context.md \
  semantic/filters.md \
  semantic/time.md \
  output/run_2026-06-26_001/analysis_code.py \
  output/run_2026-06-26_001/analysis_plan.md ; do
  sed -i "s/${OLD}/${NEW}/g" "$f"
done
```

- [ ] **Step 2: Rename the CSV and the dictionary file**

```bash
git mv "data/${OLD}.csv" "data/${NEW}.csv"
git mv "metadata/${OLD}.yaml" "metadata/${NEW}.yaml"
```

- [ ] **Step 3: Verify the old name is gone from config + the gate passes**

```bash
grep -rn "$OLD" metadata/ semantic/ ; echo "exit=$?"   # expect: no matches, exit=1
grep -n "^table:" "metadata/${NEW}.yaml"                # expect: table: Gastro_prod_sales_260605
py -3 scripts/validate_schema.py
```
Expected: `validate_schema.py` prints `RESULT: ALL CLEAR.`, and the active-tables
line includes `Gastro_prod_sales_260605` (and no longer the old name). The `grep`
over `metadata/ semantic/` returns nothing (exit 1).

- [ ] **Step 4: Commit**

```bash
git add data/ metadata/ semantic/ output/run_2026-06-26_001/analysis_code.py output/run_2026-06-26_001/analysis_plan.md
git commit -m "rename: gastro HCP universe -> Gastro_prod_sales_260605"
```

---

### Task 2: Subset Holdout_HCP_Universe to the first 700 rows

Truncates the holdout membership list and rewrites the now-false "identical 1,040 /
no-op" claims in the rule, the dictionary, and the join edges. RULE-102 becomes a
real restriction.

**Files:**
- Modify (truncate): `data/Holdout_HCP_Universe.csv`
- Modify: `semantic/filters.md` (RULE-102 caveats)
- Modify: `metadata/Holdout_HCP_Universe.yaml` (known_issues)
- Modify: `metadata/relationships.yaml` (the two holdout edges + the shared-key prose)

**Interfaces:**
- Produces: a 701-line (header + 700) `Holdout_HCP_Universe.csv`. Consumed by Task 3's re-run as the analysis spine (→ 700-row result).

- [ ] **Step 1: Truncate to header + first 700 ids**

```bash
cd "C:/Users/RounakSuranshe/Documents/Projects/Abbvie-MRD-Automation"
# pre-flight: refuse to truncate if the file is already smaller than expected
test "$(wc -l < data/Holdout_HCP_Universe.csv)" -ge 1041 || { echo "ABORT: holdout has <1041 lines; not truncating"; exit 1; }
head -n 701 data/Holdout_HCP_Universe.csv > data/Holdout_HCP_Universe.csv.tmp
mv data/Holdout_HCP_Universe.csv.tmp data/Holdout_HCP_Universe.csv
test "$(wc -l < data/Holdout_HCP_Universe.csv)" -eq 701 || { echo "ABORT: expected 701 lines"; exit 1; }
```

- [ ] **Step 2: Rewrite RULE-102 caveats in `semantic/filters.md`**

Replace the `caveats:` block of RULE-102 (currently lines ~37–41):

```
- caveats: >
    The Holdout id set currently EQUALS the full gastro universe (1,040 / 1,040), so
    this filter is a no-op today — but apply it anyway so analyses stay correct if a
    future cut narrows the universe. Do not confuse "holdout" here with an experimental
    control arm.
```

with:

```
- caveats: >
    The Holdout id set is a strict SUBSET of the gastro universe (700 of 1,040 HCPs),
    so this filter MATERIALLY restricts HCP analyses — it is no longer a no-op. Apply
    it unconditionally on any gastro HCP analysis. Do not confuse "holdout" here with
    an experimental control arm; it is the analyzable scope.
```

- [ ] **Step 3: Rewrite the `known_issues` in `metadata/Holdout_HCP_Universe.yaml`**

Replace the first and third `known_issues` bullets (the "1,040 / 1,040 ids match"
and "identical 1,040-id set" claims) with:

```yaml
known_issues:
  - "Scope/membership list: HCP analyses on the gastro universe MUST be RESTRICTED to these ids (RULE-102). It is a strict subset of the gastro universe (700 of 1,040 HCPs), so the restriction is material — not a no-op."
  - "Defines the analyzable population; it is NOT a treatment/control split. Presence of an id simply means the HCP is in scope."
  - "abbott_customer_id is the same key value space as the gastro universe's abv_customer_id and HCP_demographics.abbott_customer_id (join-compatible). The holdout now covers 700 of those ids; coverage shrank, the key did not change."
```

- [ ] **Step 4: Rewrite the holdout claims in `metadata/relationships.yaml`**

(a) In the shared-key prose block, replace `(verified: identical / 1,040-id set)`
wording so it reads (keep the surrounding lines):

```
# It DOES join, on the HCP key, to the two HCP reference tables below. The HCP key is
# the same value space across all three: gastro abv_customer_id == HCP_demographics
# .abbott_customer_id == Holdout_HCP_Universe.abbott_customer_id (join-compatible; the
# holdout now covers 700 of the universe's 1,040 ids — a strict subset, not full).
```

(b) In the `Holdout_HCP_Universe.abbott_customer_id → …abv_customer_id` edge `notes:`,
replace `Currently the id set equals the universe exactly (no-op today), but it is the
authoritative scope if a future cut narrows it.` with:

```
      The holdout is a strict subset (700 of the 1,040 universe ids), so this RESTRICTS
      gastro HCP analyses to in-scope HCPs (RULE-102) — material, not a no-op. The edge
      is 1:1 on matched ids; it simply no longer covers the whole universe.
```

- [ ] **Step 5: Verify the gate still passes and the subset is real**

```bash
py -3 scripts/validate_schema.py                 # expect: ALL CLEAR (700-row sample fine)
grep -rn "1,040 / 1,040\|identical 1,040\|no-op today" semantic/ metadata/ ; echo "exit=$?"  # expect: none, exit=1
```

- [ ] **Step 6: Commit**

```bash
git add data/Holdout_HCP_Universe.csv semantic/filters.md metadata/Holdout_HCP_Universe.yaml metadata/relationships.yaml
git commit -m "rule: RULE-102 holdout subset to 700 (restriction now material, not no-op)"
```

---

### Task 3: Re-run run_2026-06-26_001 under the 700-holdout scope

The script builds its HCP spine from the holdout file, so re-running yields a 700-row
result with new group counts. Renumber the plan, re-run, validate, regenerate the
narrative, and rebuild the deck.

**Files:**
- Modify: `output/run_2026-06-26_001/analysis_plan.md` (counts only; name already swapped in Task 1)
- Regenerate: `output/run_2026-06-26_001/result.csv` (by running the script)
- Modify: `output/run_2026-06-26_001/takeaways.md`, `output/run_2026-06-26_001/context.md`
- Modify: `output/run_2026-06-26_001/deck_spec.json` (statement_title)
- Regenerate: `output/run_2026-06-26_001/deck.pptx` (by running the builder)
- Create: `output/run_2026-06-26_001/extracted_figures.json` (figure hand-off to Task 4)

**Interfaces:**
- Consumes: `data/Gastro_prod_sales_260605.csv` (Task 1), 700-row `Holdout_HCP_Universe.csv` (Task 2).
- Produces: the new segment counts (printed by the script) that Task 4 reuses for the walkthrough.

- [ ] **Step 1: Renumber the plan's counts**

In `output/run_2026-06-26_001/analysis_plan.md`:
- Change `expected_row_count: 1040` → `expected_row_count: 700`.
- In the `output_grain:` line, change `across the full holdout universe (1,040 HCPs)` → `across the holdout universe (700 HCPs)` and `1,040 rows is intended` → `700 rows is intended`.
- In the `joins:` line, change `No-op today (id sets identical).` → `Restricts to the 700-HCP holdout scope (RULE-102; material, the holdout is a strict subset of the 1,040-HCP universe).`
- In the `assumptions:` line, change `Universe = full 1,040-HCP holdout universe incl. zero-CD doctors` → `Universe = the 700-HCP holdout scope incl. zero-CD doctors`.

- [ ] **Step 2: Re-run the analysis script**

```bash
cd "C:/Users/RounakSuranshe/Documents/Projects/Abbvie-MRD-Automation"
py -3 output/run_2026-06-26_001/analysis_code.py
```
Expected console output: `spine HCPs (universe): 700`, `result rows: 700`, plus the
`group counts:` and `holdout status:` tables. **Record these numbers** — Task 4 needs them.

- [ ] **Step 3: Validate the result**

```bash
py -3 scripts/validate_result.py output/run_2026-06-26_001
```
Expected: `RESULT: PASS.` with `Rows: 700`. A `Row count N != expected_row_count`
mismatch means either (a) the plan's `expected_row_count` was not renumbered to 700
(Task 3 Step 1), or (b) the holdout subset is the wrong size — re-check Task 2 Step 1
(`wc -l data/Holdout_HCP_Universe.csv` must be 701). Fix the cause, re-run Step 2, then Step 3.

- [ ] **Step 4: Capture every figure the narrative cites, from result.csv**

This writes the figures to `extracted_figures.json` in the run folder (a stable
on-disk source of truth so Task 4's transcription can't drift across sessions) AND
prints them. It also computes each distribution/funnel **bar width** the way `_src.html`
scales them — normalized to the largest segment = 100% — so Task 4 never hand-computes
a percentage.

```bash
py -3 - <<'PY'
import pandas as pd, json
df = pd.read_csv("output/run_2026-06-26_001/result.csv")
g = df["classification_group"].value_counts().to_dict()
h = df["holdout_status"].value_counts().to_dict()
sky = float(df["skyrizi_cd_nbrx_13wk"].sum()); stel = float(df["stelara_cd_nbrx_13wk"].sum())
active = int((df["classification_group"]!="no_cd_nbrx").sum())
switch = g.get("stelara_only",0)+g.get("both_lean_stelara",0)
order = ["no_cd_nbrx","skyrizi_only","stelara_only","both_lean_stelara","both_lean_skyrizi"]
mx = max((g.get(k,0) for k in order), default=1) or 1
widths = {k: round(100*g.get(k,0)/mx, 1) for k in order}   # largest bar = 100.0
out = {"total": len(df), "groups": g, "holdout_status": h,
       "active": active, "switch_n": switch,
       "sky_total": round(sky), "stel_total": round(stel),
       "mult": round(sky/stel,1) if stel else None,
       "bar_widths_pct": widths}
json.dump(out, open("output/run_2026-06-26_001/extracted_figures.json","w"), indent=2)
print(json.dumps(out, indent=2))
PY
```
Keep this output (and the on-disk `extracted_figures.json`). Every number in Steps 5–6
and in Task 4 traces to it. Note: under the first-700 subset the small groups shrink but
(per a dry-run) stay non-zero (`both_lean_skyrizi` ≈ 1, not 0) — so Task 4 Step 3b's
removal branch is typically NOT triggered; confirm against your actual `groups` output.

- [ ] **Step 5: Rewrite `takeaways.md` and `context.md` from those numbers**

Edit `output/run_2026-06-26_001/takeaways.md`: keep its 2–4 numbered structure
(drill-down: top contributor + concentration), but replace every figure with the
Step-4 values — total HCPs (700), Holdout vs Non-Holdout split, the silent
`no_cd_nbrx` count, the active-switch-list count (`stelara_only + both_lean_stelara`),
and market-wide SKYRIZI vs STELARA CD NBRx + multiple. Every claim must cite a
column/value from `result.csv`. Edit `context.md`: update `headline:` to the new
700-scope story, `time_period` stays (cur_13wk, w/e 2026-06-05), and update any
HCP-count mention. Do not add a perturbation caveat (the gastro/holdout tables are
not perturbed).

- [ ] **Step 6: Make the deck title data-driven**

In `output/run_2026-06-26_001/deck_spec.json`, change `statement_title` from
`"1,040 Crohn's HCPs Narrow to a {switch_n}-Prescriber STELARA Switch List"` to
`"{total:,} Crohn's HCPs Narrow to a {switch_n}-Prescriber STELARA Switch List"`
(the builder injects `total = len(result)` — verified in `build_deck_holdout.py:101,116`).

- [ ] **Step 7: Rebuild and structurally validate the deck**

```bash
py -3 scripts/build_deck_holdout.py output/run_2026-06-26_001
```
Expected: it writes `deck.pptx`, runs its integer-EMU sanitizer + round-trip
validation, and reports 0 integrity issues. The funnel pool node should read the new
total (700) and the title the new `{total}`/`{switch_n}`.

- [ ] **Step 8: Commit**

```bash
git add output/run_2026-06-26_001/
git commit -m "data: re-run run_2026-06-26_001 under 700-HCP holdout scope (new result, narrative, deck)"
```

---

### Task 4: Rebuild the gated case-study walkthrough + fix the onboarding doc

`holdout-case-study.html` is generated by `build_walkthrough.py`, which (a) pins the
deck to a frozen sha256 + length and (b) asserts the segment counts sum to 1040 and
that specific figure strings are present. The deck changed (Task 3) and the numbers
changed (700-scope), so the source AND the gate constants must be updated together.

**Files:**
- Modify: `docs/walkthrough/_src.html` (hand-baked figures + narrative)
- Modify: `scripts/build_walkthrough.py` (FROZEN_SHA, FROZEN_LEN, segment gates, figure list)
- Regenerate: `docs/walkthrough/holdout-case-study.html` (by running the builder)
- Modify: `docs/metadata-onboarding-session-record.html` (lines ~223 and ~226)

**Interfaces:**
- Consumes: the 700-scope segment counts from Task 3 Step 4, and the rebuilt
  `output/run_2026-06-26_001/deck.pptx` from Task 3 Step 7.

- [ ] **Step 1: Get the rebuilt deck's new sha256 + byte length**

```bash
cd "C:/Users/RounakSuranshe/Documents/Projects/Abbvie-MRD-Automation"
py -3 - <<'PY'
import hashlib, pathlib
b = pathlib.Path("output/run_2026-06-26_001/deck.pptx").read_bytes()
print("FROZEN_LEN =", len(b))
print("FROZEN_SHA =", hashlib.sha256(b).hexdigest())
PY
```
Capture this **once**, immediately after Task 3 Step 7's `build_deck_holdout.py` exits 0
(a clean exit means the deck is stable — it aborts on integrity failure). The `.pptx` is
not byte-deterministic across rebuilds, so do NOT re-run `build_deck_holdout.py` during
Task 4; if you must rebuild it for any reason, re-capture SHA+LEN before Step 4.

- [ ] **Step 2: Update the deck pin + segment gates in `scripts/build_walkthrough.py`**

- Set `FROZEN_LEN` (line ~20) and `FROZEN_SHA` (line ~19) to the Step-1 values.
- Replace the `segs` dict (line ~45) with the new `classification_group` counts from
  Task 3 Step 4 (keys are the count strings, e.g. `{"<no_cd>": <n>, "<sky_only>": <n>, "<stel_only>": <n>, "<both_stel>": <n>, "<both_sky>": <n>}`), and change the
  `sum(segs.values()) != 1040` check to `!= 700`.
- Change the `43 + 370 + 627 != 1040` assert (line ~48) to the new
  `switch_n + nonholdout_n + no_cd_nbrx != 700` using the actual integer values
  (this partition holds: `no_cd_nbrx + switch_n + nonholdout_n == total`).
- Replace the required-figure tuple (line ~51) `("627","367","26","17","3","1,040","670","370","43")`
  with the new figure strings (new segment counts, new total `700`, new holdout/non-holdout, new switch count).
- **Add an ABSENCE gate** (close the silent-stale-figure hole): after the presence
  check, fail the build if any OLD figure string still appears — e.g.
  `for v in ("1,040","670","627","367","370"):` `if v in html: fail(f"stale old figure {v} still in page")`.
  (Pick old strings that are NOT also valid new figures; e.g. if a new count coincidentally
  equals an old one like `17`, omit it from this list.) This makes a missed `_src.html`
  replacement trip the gate instead of shipping silently.

- [ ] **Step 3: Re-narrate `docs/walkthrough/_src.html` to the 700-scope numbers**

Replace every baked figure with its Task-3 value. The occurrences (from grep) are:
`<title>` and `<meta name="description">` ("670 or 43?"), the hero (`<span class="strike">670</span>`, `<span class="hero43">43</span>`, the "670 Holdouts / 43 / 627 silent" lead and the "~93% (627/670)" stakes line), the validation block (`row count = 1,040 == expected_row_count 1,040`, `spine 1,040 → 1,040`, `result.csv (1,040 rows)`), the section headers ("670 collapses to 43", "670 Holdouts collapse to 43 real switch targets", `1,040 Crohn's HCPs Narrow to a 43-Prescriber…`), the distribution + funnel bars (627/367/26/17/3), the funnel split (`670 · 64%` / `370 · 36%`), the callouts (`627 are silent`, `43 active STELARA prescribers`), the `#1`/`#3` insight quotes (413 active, 370 Non-Holdouts, SKY 666 vs STEL 49 ≈13.6×), and the output-node traces (`result.csv · 1,040 rows`, `627 / 367 / 26 / 17 / 3`, `SKY 666 vs STEL 49`), the **"Decision recap" / exec section** (~lines 632–646: the reconciliation line `43 + 370 + 627 = 1,040`, the 43/370/627 segment cards, the `context.md` headline quote), and **both "Canonical view" lines** (~460 and ~646: `1,040 in scope → 413 actively prescribing → 43 switch targets (627 silent…)`). Use the exact integers/total/ratio from Task 3 Step 4. Do not introduce em/en-dashes or the literal `TL;DR` (the builder rejects both).

**Also recalculate every bar WIDTH.** The distribution and funnel bars are scaled to
the largest segment = `width:100%`; each other bar is `width:<count/max*100>%`. Use the
`bar_widths_pct` from `extracted_figures.json` (Task 3 Step 4) — do NOT use `count/700`,
and never hand-compute. Apply to BOTH distribution blocks (~lines 454–458 and ~498–502)
and the funnel leaf bars (~lines 538–542), and update the two literal aria-label strings
(~lines 453 and 526) to the new counts + new total (700). The `build_walkthrough.py` gate
does NOT validate widths, so after the rebuild eyeball `holdout-case-study.html` to confirm
no broken/overflowing bars (especially the now ~1-HCP `both_lean_skyrizi` sliver).

**Residual scan (do this after editing).** Confirm no stale figure survived:

```bash
grep -nE "1,040|1040|670|627|367|\b370\b|\b413\b|666|49|13\.6" docs/walkthrough/_src.html
```
Every remaining hit must be an intentionally-kept value; any leftover old count is a missed
replacement (and the Step-2 ABSENCE gate will also catch the major ones at build time).

- [ ] **Step 3b: If any segment count dropped to 0, adjust structurally**

The first-700 subset shrinks the small groups (a dry-run gives `both_lean_skyrizi` ≈ 1,
not 0 — so this branch is usually NOT triggered). Check the Task 3 Step 4 output. If a
`classification_group` count is now **0**, then remove that group's bar in `_src.html`:
the group appears as a single-line `<div class="row">` in the distribution (~line 458)
and a single-line `<div class="leaf">` in the funnel (~line 542) — delete each whole
line, remove its count clause from the aria-labels (~lines 453 and 526), and in
`build_walkthrough.py` drop that key from `segs` and the required-figure tuple. (A third
copy in the s7 "v1 bar" reconstruction ~line 502 may stay; the gate only checks figure
presence.) Re-confirm the remaining `segs` still sum to 700. If all five groups are
non-zero (the expected case), skip the removal — but still apply the count swap (e.g.
`3`→its new value) in the aria-labels at ~453 and ~526, not just the visible bars.

- [ ] **Step 4: Rebuild the walkthrough (this is the gate)**

```bash
py -3 scripts/build_walkthrough.py
```
Expected: `OK -> …holdout-case-study.html` and the final gate line. Any
`BUILD GATE FAILED:` means a figure in `_src.html` and the gate constants in
`build_walkthrough.py` disagree, or the deck sha/len wasn't updated — reconcile and re-run.

- [ ] **Step 5: Fix the onboarding-record claim**

In `docs/metadata-onboarding-session-record.html`, change line ~223 from
`All three sources cover the same ~1,040 prescribers and connect through a single shared prescriber ID.`
to
`Two cover the full ~1,040-prescriber universe; the holdout scope narrows to 700. All connect through a single shared prescriber ID.`
Also update the related now-false claim at **line ~226** (`Today it matches the full
universe, so no prescribers are excluded yet — it is the authoritative scope if that ever
narrows.`) → the holdout scope has now narrowed to 700 of the ~1,040 universe (the
"if that ever narrows" has occurred). Leave the ~1,040 universe mentions at lines ~159
and ~186 unchanged (the gastro universe is not subset).

- [ ] **Step 6: Commit**

```bash
git add docs/walkthrough/_src.html docs/walkthrough/holdout-case-study.html scripts/build_walkthrough.py docs/metadata-onboarding-session-record.html
git commit -m "docs: rebuild case-study + onboarding record for 700-HCP holdout scope"
```

---

### Task 5: Drop pre-perturb backups + update MEMORY + final whole-repo verification

Deletes the pre-perturb backup dirs (keeping the simulate `_original`), folds the
gastro rename + holdout-700 narrative into MEMORY, and runs the full gate sweep.

**Files:**
- Delete: `data/_pre_perturb/`, `_pre_perturb_backup/`
- Modify: `MEMORY.md`

- [ ] **Step 1: Delete the pre-perturb backup dirs**

```bash
cd "C:/Users/RounakSuranshe/Documents/Projects/Abbvie-MRD-Automation"
rm -rf data/_pre_perturb _pre_perturb_backup
ls -d data/_original data/_pre_perturb _pre_perturb_backup 2>&1   # expect: only data/_original exists
```

- [ ] **Step 2: Update MEMORY.md**

- Replace every `sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl` with `Gastro_prod_sales_260605`:
  ```bash
  sed -i 's/sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl/Gastro_prod_sales_260605/g' MEMORY.md
  ```
- Hand-edit the holdout facts: the `data/Holdout_HCP_Universe.csv` line ("1,040 ids … Equals the gastro universe exactly (no-op restriction)") → 700 ids, a strict subset, RULE-102 now material. The "HCP KEY … verified identical 1,040-id set" line → "join-compatible key; holdout covers 700 of the 1,040 ids". RULE-102 / RULE-009 relationship notes mentioning the 1,040 identical set → subset wording. The run_2026-06-26_001 entry → note it was re-run under the 700-HCP holdout scope (numbers refreshed from result.csv).
- In the perturbation section, update the revert note: the root `_pre_perturb_backup/` true-originals path is **removed** — record that re-perturb-from-true-originals is no longer available (accepted); `data/_original/` (simulate reset) is retained.

- [ ] **Step 3: Whole-repo verification sweep**

```bash
# old table name fully gone from the LIVE engine surface. Scope to the dirs that
# matter — the planning docs (docs/superpowers/*) and scratch_final_plan.md
# legitimately quote the old name as historical "old -> new" record, so they are
# intentionally NOT searched. Exclude data/.snapshot.json: it is a gitignored,
# runtime-regenerated cache that may re-list the date-less table under the old key;
# it carries no engine logic (compare() ignores orphan keys) — just delete it so it
# self-reinitializes clean: rm -f data/.snapshot.json
rm -f data/.snapshot.json
grep -rn "sqlqueries_4_gastro_hcp_universe_prod_2_260605_cl" \
  data metadata semantic output scripts web MEMORY.md ; echo "exit=$?"   # expect: none, exit=1
py -3 scripts/validate_schema.py                          # expect: ALL CLEAR, 5 tables, new name
py -3 scripts/validate_result.py output/run_2026-06-26_001  # expect: PASS, 700 rows
py -3 scripts/build_walkthrough.py                        # expect: OK
py -3 -m pytest -q                                        # expect: 66 passed, 6 failed (the documented pre-existing perturbed-demo-data failures); NO new failures
```
If pytest shows anything other than the 6 known failures
(`test_reset_without_backup_returns_400`, `test_weekly_table_info_against_real_data`,
`test_monthly_min_max`, `test_reset_restores_byte_identical`,
`test_reset_without_backup_is_noop`, `test_snapshot_detects_a_changed_max`),
investigate before committing — that is a regression.

- [ ] **Step 4: Commit**

```bash
git add MEMORY.md data/
git commit -m "chore: drop pre-perturb backups + record gastro rename / 700-holdout in MEMORY"
```

---

## Notes for the executor

- The 6 pre-existing pytest failures are unrelated to this work (perturbed-demo-data
  fixtures); they must remain exactly those 6 — no more, no fewer.
- If `validate_schema.py` ever reports the new table EXCLUDED, the CSV stem and the
  YAML `table:` field disagree — they must both be `Gastro_prod_sales_260605`.
- Tasks are strictly ordered: 1 → 2 → 3 → 4, then 5. Task 3 reads Task 1+2's outputs;
  Task 4 reads Task 3's deck + counts. Task 5's MEMORY rename assumes Task 1 done.

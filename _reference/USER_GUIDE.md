# USER GUIDE — Query-to-Slide Analytics Engine

This repository turns a plain-English business question into a slide-ready result table, a context block, and 2-4 takeaways. You run it inside **Claude Code**. The slide itself is built by another team from what lands in `/output`; this system stops at the handoff.

This guide covers: one-time setup, adding datasets, running queries day to day, how the clarification loop works, managing business rules, the output handoff, maintenance, and troubleshooting.

---

## 1. What's in the box

```
query-to-slide/
├── CLAUDE.md              ← The engine's operating manual. Claude Code reads this
│                            automatically at session start. Don't run queries
│                            without it; it IS the system.
├── USER_GUIDE.md          ← This file.
├── PLAN.md                ← The full build plan and design rationale.
├── data/                  ← Your CSVs go here. Nothing else.
├── metadata/              ← One YAML dictionary per CSV + relationships.yaml.
│   └── _TEMPLATE.yaml     ← Copy this for each new dataset.
├── semantic/              ← Business rules in four files:
│   ├── metrics.md         ← how numbers are calculated
│   ├── filters.md         ← what is always excluded
│   ├── context.md         ← known business patterns (explains, never alters)
│   ├── time.md            ← date logic: anchor, windows, defaults
│   └── _rule_log.csv      ← audit log of every rule
├── scripts/
│   ├── validate_schema.py ← gate: dictionaries vs CSVs
│   └── validate_result.py ← gate: result vs plan
├── output/                ← one folder per query run (the deliverable)
└── examples/              ← a complete synthetic worked example, end to end
```

**The one rule that governs everything:** a CSV without a matching dictionary in `/metadata` is invisible. The engine will not see it, mention it, or use it. This is deliberate; it prevents analysis of data nobody has described.

---

## 2. One-time setup (15 minutes)

**Step 1 — Initialize git.** The semantic and metadata layers are version-controlled so any bad rule is one revert away from gone:

```bash
cd query-to-slide
git init
git add .
git commit -m "initial scaffold"
```

**Step 2 — Install dependencies.**

```bash
pip install pandas pyyaml
```

**Step 3 — Replace the placeholder rules.** The files in `/semantic` ship with seeded pharma placeholder rules (marked `[DEFINE ...]`). Open each file and replace the placeholders with your real definitions: your actual market basket, your real test-ID exclusions, your true provisional-week count. Commit when done. **Do not skip this** — the engine will faithfully apply whatever these files say, including placeholders.

**Step 4 — Verify the example.** Prove the machinery works before adding real data:

```bash
cd examples
python ../scripts/validate_schema.py --root .
python output/run_2026-06-04_001/analysis_code.py
python ../scripts/validate_result.py output/run_2026-06-04_001 --max-rows 30
```

All three should pass. The `examples/` folder is also your reference for what a correct dictionary, relationship file, and finished run folder look like.

---

## 3. Adding a dataset (do this for each of your CSVs)

1. Drop the CSV into `/data`, e.g. `data/rx_transactions.csv`.
2. Copy `metadata/_TEMPLATE.yaml` to `metadata/rx_transactions.yaml` (the basename must match the CSV exactly).
3. Fill it in. The fields that matter most, in order:
   - **grain** — "one row per HCP per product per week." Most wrong analyses come from a misunderstood grain. Get this right.
   - **columns** — every column, with a business-language description. For categorical columns, list `sample_values`; the engine uses them to filter correctly.
   - **known_issues** — claims lag, undercounted weeks, anything an analyst would warn a colleague about.
4. If this table joins to any other, declare the edge in `metadata/relationships.yaml`. Include the join type and a note on direction and null behavior (see the commented examples in the file). **No edge = the engine refuses the join.** It will never guess keys.
5. Run the gate: `python scripts/validate_schema.py`. Fix anything it flags.
6. Commit: `git add metadata/ && git commit -m "add rx_transactions dictionary"`.

When a data refresh changes a CSV's columns, the gate will halt the next session and tell you exactly which columns drifted. Update the dictionary (or fix the file) and re-run.

---

## 4. Running a query (the daily workflow)

Open Claude Code in the project root and just ask:

> "How is PRODUCT_A share trending in the Northeast vs national?"

Claude Code reads `CLAUDE.md` automatically and follows its protocol. Here's what you'll experience:

**Boot (automatic, a few seconds).** It checks git status, runs schema validation, loads all dictionaries, relationships, and rules, and flags any auto-saved rules pending review. If a dataset is broken or undocumented, you hear about it now, not after a wrong answer.

**Clarification (when needed).** Three things can happen:

- *Your question is fully answerable* → it proceeds straight to the plan.
- *Answerable with assumptions* (most common) → it states them in plain English and asks you to confirm: "I'll define 'top territories' as the top 10 by TRx over the trailing 13 weeks. Confirm or adjust?" If you reply "whatever you think," it applies the documented default and records that the choice was a default, not your confirmation.
- *Not answerable* → it tells you why, precisely:
  - **Missing data:** "This needs patient out-of-pocket cost, which isn't in any dataset." It stops; it will not invent.
  - **Missing definition:** "The data supports this, but 'loyal writer' isn't defined. Proposed: an HCP with ≥1 NRx in each of the last 3 months. Shall we use that?" You discuss, agree, and the rule is **saved automatically** to the semantic layer so it is never asked again.

**Execution (automatic).** It writes an analysis plan, generates a standalone Python script, runs it, and validates the result (row counts, nulls, join fan-out, reconciliation). The engine never does math itself; all numbers come from executed code. If validation fails, it does not deliver; it tells you what's wrong.

**Delivery.** You get the headline plus a folder path:

```
output/run_2026-06-04_001/
├── result.csv        ← the table (≤15 rows by default; long lists become top-N + "Other")
├── context.md        ← headline, methodology, filters, period, freshness, caveats
├── takeaways.md      ← 2-4 numbered findings, each traceable to the table
├── analysis_plan.md  ← what was decided and assumed   ┐
├── analysis_code.py  ← exactly how it was computed    ├─ audit trail
└── query.txt         ← what you asked, verbatim       ┘
```

**Follow-ups.** Just keep talking: "now break that by payer." A follow-up inherits the previous plan, changes only what you asked, doesn't re-confirm what you already confirmed, and still produces a complete standalone run folder.

### Tips for asking good questions
- Name the product, geography, and time window when you know them; you'll skip the clarification round.
- If you omit the time window, you get the documented default (trailing 13 weeks) and it will be stated back to you.
- Vague terms are fine: that's what the clarification loop and rule brainstorm are for. The system gets smarter every time you define one.

---

## 5. Managing business rules (the semantic layer)

Rules live in four files in `/semantic`, all in the same format (see any existing rule). The categories matter because the engine uses them differently:

| File | What it controls | Effect |
|---|---|---|
| `metrics.md` | how numbers are computed | feeds the calculation code |
| `filters.md` | standing exclusions | applied to **every** query, unconditionally |
| `context.md` | known business patterns | explains results in takeaways; never changes numbers |
| `time.md` | anchor date, windows, defaults | resolves all date language |

**Adding a rule manually:** append it to the right file in the standard format, add a row to `_rule_log.csv`, commit.

**Auto-saved rules:** when a rule is created during a query conversation, the engine first checks it doesn't conflict with an existing rule (a conflict is shown to you to resolve, never saved silently), then saves, logs, and git-commits it. You'll see a one-line confirmation like "Saved as RULE-031 in filters.md."

**The 30-day review (important).** Auto-save is convenient and dangerous: a bad rule silently corrupts every future answer. Two safety valves protect you:
1. At each session start, the engine lists auto-saved rules older than 30 days that nobody has reviewed. Review them: open the file, check the definition, set `reviewed = yes` in `_rule_log.csv` (or edit/delete the rule).
2. Everything is in git. A bad rule is removed with `git revert <commit>`.

---

## 6. The handoff (output contract)

The slide team receives the run folder. The contract is: `result.csv` + `context.md` + `takeaways.md` are slide inputs; the plan, code, and query are the audit trail for when a number is challenged. The contract is frozen once agreed with the slide team; changes need their sign-off.

**When a client challenges a number:** open the run folder. `analysis_plan.md` shows every assumption and filter; `analysis_code.py` re-runs standalone and reproduces `result.csv` exactly. Total time to defend a number: about two minutes.

---

## 7. Maintenance

| Cadence | Task |
|---|---|
| Every data refresh | `python scripts/validate_schema.py` (the engine also runs it at every session start) |
| When prompted | Review flagged auto-saved rules; mark reviewed or revert |
| After any semantic/metadata change | Re-run your benchmark queries (the 5 known-answer tests from the build plan) and confirm results haven't shifted unexpectedly |
| Quarterly | Skim all rules for stale definitions (changed market basket, new products, retired filters) |

---

## 8. Troubleshooting

**"Table X is excluded from analysis."** No dictionary. Create `metadata/X.yaml` from the template.

**"Schema drift" at session start.** A CSV's columns changed since the dictionary was written. The report names the exact columns; update the YAML or fix the file, commit, retry.

**"No validated join exists between A and B."** Working as designed. If the join is legitimate, add the edge to `relationships.yaml` with the keys and join type, run the schema gate, commit, re-ask.

**Result validation failed.** The engine refuses to deliver and names the discrepancy (row count off, nulls, fan-out). It will fix the plan/code and re-run; if it can't after 3 attempts, it stops and shows you the error. Never hand-edit `result.csv` — fix the cause and regenerate.

**A delivered number looks wrong.** Read `analysis_plan.md` first; nine times out of ten the issue is an assumption or filter you'd have set differently, not a code bug. Re-ask the query with the correction; the rule brainstorm will capture your preference permanently if it should be a standing rule.

**An auto-saved rule is wrong.** `git log --oneline -- semantic/` to find the commit, `git revert <commit>`, and update `_rule_log.csv`.

**The engine is asking too many questions.** It clarifies only when assumptions are material. To reduce questions permanently, encode your defaults as rules (especially in `time.md` and `metrics.md`); defaults are applied silently and recorded in the plan.

---

## 9. Hard guarantees (what the engine will never do)

It will never do arithmetic itself (all numbers come from executed pandas code). It will never join tables without a declared, validated edge. It will never use a dataset without a dictionary. It will never deliver a result that failed validation. It will never produce patient-grain output. And it will never silently overwrite an existing rule with a conflicting one.

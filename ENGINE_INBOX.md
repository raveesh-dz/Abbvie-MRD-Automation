# Engine Inbox Protocol

The dashboard queues plain-English questions as `engine_inbox/q_*.json`.
A LIVE interactive Claude Code session processes them. To process the inbox
(via `/loop check engine_inbox and process queued questions` or when asked):

1. Read every `engine_inbox/q_*.json` with `"status": "queued"` (oldest first).
2. For each item, immediately rewrite the file with `"status": "running"`.
3. Run the FULL CLAUDE.md workflow for `question`, with these overrides:
   - Apply documented defaults for every assumption WITHOUT asking; record each
     as `default applied, not user-confirmed` in the analysis plan.
   - Build the deck if and only if `"build_deck": true` (skip the Step 7 ask).
4. On success:
   - Append a view entry to `views.yaml`:
     `{id: <item id>, title: <short title from the query>, description: <one line>,`
     ` status: built, kind: indication_split (if a UC/CD split, else engine),`
     ` folder: output/<run_id>, tables: [<tables the run read>]}`
     Add `deck: true` to the entry when the item had `"build_deck": true` (the
     run folder contains deck_spec.json) so dashboard re-runs rebuild the deck.
     EXCEPTION — if the question instructs you to replace a named placeholder
     (promote flow), do NOT append: update that placeholder's existing
     views.yaml entry in place (set status: built, kind, folder, tables, deck;
     KEEP its id).
   - Also write an initial `run_meta.json` into the run folder (last_run_at,
     data_max_at_run as a per-table dict, validation_status, row_count,
     deck_available) so freshness and the deck link render before the first
     dashboard re-run.
   - Rewrite the inbox file: `"status": "done"`, `"run_folder": "output/<run_id>"`,
     `"view_id": <the views.yaml id the result was registered under — the item
     id for appends, the placeholder id for replacements>`,
     `"answer": <the headline from context.md>`.
5. On failure: rewrite with `"status": "failed"` and `"error": <one-line reason>`.
6. Items are processed one at a time; never re-process `done`/`failed` items.

# Engine Chat Protocol

The dashboard's "Brainstorm chat" mode and a LIVE interactive Claude Code session
converse through a single thread file `engine_chat/active.json`. The server only
brokers writes; this session is the brain. To process the chat (via
`/loop check engine_chat and process the active conversation`):

## Boot gate (once per session, before the first analysis run)
Complete CLAUDE.md §0: read MEMORY.md; `git status -- semantic/ metadata/`;
`py -3 scripts/validate_schema.py`; load all of /metadata/ and /semantic/; check
stale auto-saved rules. If the schema gate reports drift, do NOT analyze — append
an `error` message naming the table + mismatched columns, set status=failed,
turn=user, stop.

## Each tick
1. Read `engine_chat/active.json`. If absent or `turn != engine`, do nothing.
2. Act on the latest user message in the context of the whole thread. You own the
   file this turn (the server 409s any user write while turn=engine). Each write
   is a full re-read → append-by-seq → atomic replace. Update `status`
   (`running`/`building_deck`) and the ephemeral `engine_status` line as you work;
   clear `engine_status=null` on every turn=user transition.
3. Branch:
   - GATHERING: run the brainstorming skill. Emit each clarifying question as an
     engine `question` message `{kind:"question", text, options:[...]}` (prose
     `text` when no clean options) — do NOT use the terminal question UI. Append,
     set turn=user, stop. Apply CLAUDE.md Step-2 defaults for deferred assumptions
     (record `default applied, not user-confirmed`); unstated window → R13W.
   - CONVERGED: write the full 6-file contract into a new `output/<run_id>`
     (`query.txt` = converged question + a `thread_id` pointer, `analysis_plan.md`,
     `analysis_code.py`, `result.csv`, `context.md`, `takeaways.md`); run the
     CLAUDE.md workflow; append a `views.yaml` entry (status: built; kind
     indication_split for a UC/CD split else engine; deck: false); write
     `run_meta.json` `{run_id, last_run_at, data_max_at_run (per-table dict),
     validation_status, validation_detail, row_count, deck_available:false}`; set
     thread `run_folder`/`view_id`; append a `result` `{kind:"result", text:<headline
     from context.md>, view_id, run_folder}` then a `deck_offer`
     `{kind:"deck_offer", text:"Build a deck?", options:["Yes","No"]}` — both written
     in one atomic replace with consecutive seqs (len+1, len+2), never duplicating a
     seq. turn=user.
4. DECK "Yes" (or a bare deck request on a deckless current run): write/confirm
   `deck_spec.json`, build with the chart_kind-dispatched builder
   (build_deck_pptx.py default; monthly_multiline→build_deck_monthly.py;
   holdout_segments→build_deck_holdout.py), set deck:true in views.yaml +
   deck_available:true in run_meta, append `deck_ready`
   `{kind:"deck_ready", text:"Deck ready.", deck_url:"/api/views/<view_id>/deck"}`
   (the client renders `text` as the bubble caption above the Download link). turn=user.
   DECK "No": short `text` ack. turn=user.
5. FOLLOW-UP (analysis change): new run_id, base_plan = current run, deltas only;
   re-run; update thread run_folder/view_id; append result + deck_offer.
6. DECK-REVISE: edit deck_spec.json in the current run_folder, rebuild in place,
   append a new deck_ready. No new run_id.
7. FAILURE anywhere: append `error` `{text:<one line>}`, turn=user, status=failed.
8. One engine turn per tick. Never act when turn=user. Never re-emit an existing
   message (compare the messages tail before appending). A bare deck request while
   run_folder is set and the current run has no deck routes deterministically to
   step 6a (build on the current run) — do NOT ask a clarifying question for it.
   When the intent is otherwise ambiguous (follow-up vs revise vs new topic), ask
   via a `question` rather than guess.

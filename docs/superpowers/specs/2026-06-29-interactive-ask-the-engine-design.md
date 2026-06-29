# Interactive "Ask the Engine" — Design Spec

date: 2026-06-29
status: draft (pending user review)
author: R (Rounak.suranshe@datazymes.com) + engine

## 1. Problem

Today "Ask the Engine" is fire-and-forget. The browser posts a one-line question
→ `server/engine.py` writes `engine_inbox/q_*.json` → a separate live Claude Code
session (`/loop`) picks it up, runs the full CLAUDE.md workflow, writes
`output/<run_id>`, updates `views.yaml` + the inbox JSON. The dashboard polls and
shows queued / running / done with an "Open result" button. There is no dialogue:
the user cannot be asked clarifying questions, cannot shape the output, cannot
trigger a deck conversationally, and cannot iterate.

We want a **complete interactive flow**: the user chats, the brainstorming skill
runs, the engine asks follow-up questions, converges on what to build, runs the
real CLAUDE.md workflow, delivers the result, offers a deck, lets the user
download it, and lets the user revise (deck tweaks *and* analysis follow-ups).

## 2. Constraints / non-negotiables

- **No Agent SDK, no `claude -p`.** The brain is the live interactive Claude Code
  session already run in the terminal (the same one that processes the inbox).
- **Server stays a dumb file broker.** It never reasons, never runs an LLM. It
  only reads/writes a thread file and serves existing result/deck artifacts. This
  preserves today's trust model exactly.
- **Live alongside the existing one-shot ask.** The inbox path
  (`engine.py` / `engine.js` / `/api/engine*`) is untouched — zero regression.
- **Reuse existing artifacts.** Runs still produce the CLAUDE.md 6-file contract
  in `output/<run_id>`, register in `views.yaml`, and are served by the existing
  `/api/views/{id}/result` and `/api/views/{id}/deck` endpoints. Decks build via
  the existing `build_deck_*.py` family; note the dashboard's `run_view_core` only
  dispatches `monthly_multiline` vs the default `build_deck_pptx` today (not the
  full family — see the §6.4 NOTE on `holdout_segments`). The chat build path
  itself always calls the correct builder.
- **CLAUDE.md rules hold inside the chat.** No arithmetic by the model; declared
  joins only; validation pass before delivery; `analysis_plan.md` is the spec.

## 3. Architecture & data flow

```
Browser (chat UI)  ⇄  engine_chat/active.json  ⇄  live Claude /loop (terminal)
   user sends   → POST /api/chat/message → append user msg, turn=engine
   loop polls   → reads active.json, acts (brainstorm / run / build deck)
   loop replies → append engine msg(s), turn=user
   browser polls → GET /api/chat every 3s while turn=engine
```

The server brokers file writes only. All reasoning, the brainstorming skill, the
analysis run, and the deck build happen in the live session — exactly as inbox
processing does today (`Bash` + `py -3`).

## 4. Thread data model

One active conversation at a time: `engine_chat/active.json`. "New chat" moves the
current file to `engine_chat/archive/<thread_id>.json` and starts fresh.

```json
{
  "thread_id": "chat_<YYYYMMDD_HHMMSS%f>",
  "created_at": "<iso seconds>",
  "status": "awaiting_engine|awaiting_user|running|building_deck|done|failed",
  "turn": "engine|user",
  "engine_status": "<transient progress line, e.g. 'Running analysis…'|null>",
  "run_folder": "output/<run_id>|null",
  "view_id": "<views.yaml id>|null",
  "messages": [ <message>, ... ]
}
```

`turn` is the single source of truth for whose move it is. `status` is a finer
label for UI affordances. `engine_status` is an **ephemeral, overwritten** progress
line (NOT a stored message) the loop updates during a run so the browser shows live
progress without cluttering the transcript; it is cleared (`null`) whenever
`turn=user`. `run_folder` / `view_id` are set once the first analysis run completes
and updated on each follow-up re-run (they always point at the *latest* run of this
chat).

### Message schema

Every message: `{ "seq": <int, 1-based, monotonic>, "role": "user|engine",
"ts": "<iso seconds>", "kind": <kind>, ... }`. `seq` is assigned by whoever
appends and must equal `len(messages)+1` at append time. When a single atomic
write appends multiple messages in one turn (e.g. `result` + `deck_offer`), seqs
are assigned consecutively in append order (`len+1`, `len+2`, …), not duplicated.

User message kinds:
- `text` — `{ text }`. Free-text reply or initial question.
- `text` with `in_reply_to: <seq>` and optional `chosen: <string>` — a chip click
  (the chosen option label) or a typed answer to a specific engine `question`.

Reply association: any reply sent while a `question` or `deck_offer` is
outstanding posts `in_reply_to=<that seq>`. A chip click sets
`chosen=<label>` and `text=<label>`; a typed answer sets `text` and omits
`chosen`. The loop treats a reply with a missing `in_reply_to` as answering the
latest outstanding question.

Engine message kinds:
- `text` — `{ text }`. Plain prose.
- `question` — `{ text, options: [<string>...] }`. Renders chips + free-text box.
- `result` — `{ text: <headline>, view_id, run_folder }`. Renders "Open result".
- `deck_offer` — `{ text, options: ["Yes","No"] }`. Renders Yes/No chips.
- `deck_ready` — `{ text, deck_url: "/api/views/<id>/deck" }`. Renders "Download".
- `error` — `{ text }`. Renders an error bubble; `turn` returns to user.

## 5. State machine

| status          | turn   | input | UI                                            |
|-----------------|--------|-------|-----------------------------------------------|
| awaiting_user   | user   | ON    | normal reply box; chips if last msg has options|
| awaiting_engine | engine | OFF   | "engine working…" + spinner                   |
| running         | engine | OFF   | `engine_status` text + spinner                |
| building_deck   | engine | OFF   | `engine_status` ("building deck…") + spinner  |
| done            | user   | ON    | reply box (follow-up / revise) + New chat     |
| failed          | user   | ON    | error shown; reply to retry + New chat        |

Transitions (every `turn=user` transition clears `engine_status` to `null`):
- **send (browser):** append user msg → `turn=engine`, `status=awaiting_engine`.
- **engine asks (loop):** append `question`/`text` → `turn=user`,
  `status=awaiting_user`, `engine_status=null`.
- **engine runs (loop):** `status=running`, update `engine_status` at phase
  boundaries → on success append `result` + `deck_offer`, `turn=user`,
  `status=done`, `engine_status=null`.
- **deck build (loop):** `status=building_deck` → append `deck_ready`,
  `turn=user`, `status=done`, `engine_status=null`. Triggered by a `deck_offer`
  "Yes" OR by a bare deck request on a deckless current run (step 6a).
- **failure (loop):** append `error` → `turn=user`, `status=failed`,
  `engine_status=null`.

## 6. Loop protocol — `ENGINE_CHAT.md`

New protocol doc, sibling to `ENGINE_INBOX.md`. The live session runs:
`/loop check engine_chat and process the active conversation`.

**Boot gate.** Before the first analysis run of a session the loop MUST have
completed the CLAUDE.md §0 boot sequence: read `MEMORY.md`, `git status --
semantic/ metadata/`, `py -3 scripts/validate_schema.py`, load every file in
`/metadata/` and `/semantic/`, and check for stale `auto-saved` rules. If the
schema gate reports drift, do NOT run the analysis (hard rule: never analyze a
table whose dictionary fails validation) — append an `error` message naming the
table and mismatched columns, set `status=failed`, `turn=user`, and stop.

1. Read `engine_chat/active.json`. If it does not exist or `turn != engine`, do
   nothing this tick.
2. Act on the **latest user message** in the context of the whole thread. The
   browser already set `turn=engine`/`status=awaiting_engine` on send, and the 409
   guard (§7) means no user write can land while `turn=engine` — so the loop owns
   the file for this turn. Update sub-states (`status=running` / `building_deck`)
   and `engine_status` as work proceeds; each write is a full re-read + atomic
   replace (§9).
3. Act on the conversation so far:
   - **Gathering phase:** run the brainstorming skill internally. When a
     clarifying question is needed, emit it as an engine `question` message
     (options when there are clean choices, else prose `text`). Do NOT use the
     terminal's native question UI. Append, set `turn=user`, stop.
     Assumptions follow CLAUDE.md Step 2: surface each as a `question`, but if the
     user defers ("whatever you think") or a documented default exists, apply the
     default, proceed, and record it in `analysis_plan.md` as `default applied,
     not user-confirmed`. An unstated time window resolves to the documented
     default (R13W) and is recorded as an assumption rather than blocking on a
     chip.
   - **Converged:** write the full CLAUDE.md Step-7 6-file contract into a new
     `output/<run_id>`: `query.txt` (the converged question synthesized from the
     thread, written verbatim, plus a `thread_id` pointer back to this chat),
     `analysis_plan.md`, `analysis_code.py`, `result.csv`, `context.md`, and
     `takeaways.md`. Run the full CLAUDE.md workflow (generate `analysis_code.py`,
     execute, validate) to produce these. Update `engine_status` at phase
     boundaries. On success: append a `views.yaml` entry with `status: built`
     (kind per the analysis — `indication_split` for a UC/CD split, else `engine`,
     mirroring `ENGINE_INBOX.md` step 4; `deck: false` initially), write
     `run_meta.json` (schema below), set the thread `run_folder`/`view_id`,
     append a `result`
     message (headline read from `context.md` — so the run folder stays
     standalone) followed by a `deck_offer`. `turn=user`.

   `run_meta.json` schema (match `server/views.py` `_finish`, views.py:108-119,
   the authority — plus `run_id`): `{ run_id, last_run_at, data_max_at_run
   (per-table dict), validation_status, validation_detail, row_count,
   deck_available }`. `deck_available` starts `false`, flipped `true` on a
   successful deck build (step 4). `api_result` (app.py:118-120) surfaces
   `data_max_at_run` and `deck_available`, so these fields must be present and
   correctly typed for chat runs to render freshness and the deck affordance.
4. **Deck offer answered:**
   - "Yes" → write/confirm `deck_spec.json`, build via the `chart_kind`-dispatched
     builder (`build_deck_pptx.py` default; `monthly_multiline`→`build_deck_monthly.py`;
     `holdout_segments`→`build_deck_holdout.py`), set `deck: true` on the
     `views.yaml` entry and `deck_available: true` in `run_meta.json`, append
     `deck_ready` with `deck_url=/api/views/<view_id>/deck`. `turn=user`.
     NOTE: `server/views.py run_view_core` dispatches `monthly_multiline`→monthly
     else `build_deck_pptx` (views.py:173). So `monthly_multiline` re-runs *from
     the dashboard* are already safe; only `holdout_segments` (and any future
     `chart_kind`) lacks a branch, so a chat-built `holdout_segments` view re-run
     from the dashboard would mis-render. The chat build path itself is correct
     (the loop calls the right builder). Before chat-built decks of the
     `holdout_segments` shape are dashboard-served, add the `holdout_segments`
     branch to `run_view_core` — tracked, not blocking for this spec.
   - "No" → append a short `text` acknowledgement. `turn=user`. (The user may
     still ask for a deck later; see the deck-after-No branch in step 6a.)
5. **Follow-up (analysis change)** — e.g. "now break CD by region", "change window
   to R26W": treat as a CLAUDE.md follow-up. New `run_id`, `base_plan` = the chat's
   current `run_folder`'s run_id; the new plan states only the deltas. Re-run,
   update thread `run_folder`/`view_id` to the new run, append `result` +
   `deck_offer`. The prior run folder is left intact.
6. **Deck-revise** — e.g. "make the title shorter", "drop insight 3", "use a bar
   chart": edit `deck_spec.json` in the current `run_folder`, rebuild in place,
   append a new `deck_ready`. No new run_id.

   **6a. Deck-after-No (bare deck request)** — if `run_folder` is set, the current
   run has no deck (`deck: false` / `deck_available: false`), and the user asks for
   a deck (having earlier said "No", or never offered one for this run), treat it
   as the step-4 "Yes" path on the CURRENT `run_folder`: build the deck, flip
   `deck: true` / `deck_available: true`, append `deck_ready`. No new `run_id`.
7. **Failure** at any step: append an `error` message with a one-line reason,
   `turn=user`, `status=failed`. The user can reply to retry.
8. Process one engine turn per tick, then return to polling. Never act on a thread
   whose `turn=user`. Never re-emit a message that already exists (idempotency:
   compare against the current `messages` tail before appending).

Distinguishing follow-up vs deck-revise vs deck-after-No vs new-topic is the
engine's judgment from the message text and current thread state (`run_folder`
set? does the current run have a deck? last engine msg a `deck_ready`?). A bare
deck request when `run_folder` is set but the run has no deck routes to step 6a
(build on the current run), NOT to a clarifying question. When still ambiguous,
ask via a `question` message rather than guess.

## 7. Server endpoints

New module `server/chat.py` (thread read/write/append helpers) + routes in
`app.py`, plus a `config.engine_chat_dir()` helper (sibling to the existing
`config.engine_inbox_dir()`). `engine.py` and `/api/engine*` are untouched.

- `POST /api/chat/message` body `{ text, in_reply_to?, chosen? }` →
  - 400 if `text` empty.
  - 409 if active thread exists and `turn == engine` (engine is mid-turn; the UI
    also disables input). This check is NOT race-free on its own — FastAPI routes
    here are sync `def` and run on uvicorn's threadpool, so two concurrent POSTs
    can both read `turn=user` and both pass a naive check. The 409 MUST therefore
    be evaluated inside the module-level lock (see below), re-reading `turn`
    immediately before the atomic replace and rejecting (409) if it flipped.
  - else: create `active.json` if absent (new `thread_id`), append the user
    message with the next `seq`, set `turn=engine`, `status=awaiting_engine`,
    return the updated thread.
- `GET /api/chat` → the active thread JSON, or `{ "thread_id": null }` if none.
- `POST /api/chat/reset-turn` → dead-loop recovery. If an active thread is stuck
  `turn=engine` (the `/loop` session is not running, so the message will never be
  picked up), flip `turn=user`, `engine_status=null`, `status=awaiting_user`, and
  return the updated thread. Goes through the same locked atomic-write helper. This
  is the escape hatch so a wedged thread does not require discarding the question
  via New chat.
- `POST /api/chat/new` →
  - 409 if active thread `turn == engine` (don't discard work mid-run) unless body
    `{ force: true }`.
  - else: if the active thread has any messages, move `active.json` →
    `archive/<thread_id>.json` (skip the move for an empty thread — just delete it),
    then return `{ "thread_id": null }`.

All writes go through a single `chat.py` helper that re-reads, appends by `seq`,
and writes atomically (write temp + replace) to avoid browser/loop interleave
corruption. The helper holds a module-level `threading.Lock` (mirroring
`runner._LOCK`) across the ENTIRE read → 409-check → append → atomic-replace
critical section, so concurrent POSTs on uvicorn's threadpool serialize. Inside
the lock it re-reads and re-validates `turn` immediately before the replace
(detect-and-reject: return 409 if it flipped, never last-writer-wins) and rejects
any append whose computed `seq` duplicates an existing `seq`.

## 8. UI

New `web/js/chat.js`; `engine.js` untouched. A mode toggle in the existing
Ask-the-Engine panel of `web/index.html`. **Quick ask is the default mode on load**
(no disruption to the existing flow); the user opts into Brainstorm chat.

```
Ask the Engine     ( ) Quick ask   (•) Brainstorm chat        [New chat]
+-------------------------------------------------------------+
| you:  weekly tremfya by indication                          |
| eng:  Which market?  [ IBD only ] [ All indications ] [...]|
| you:  IBD only                                              |
| eng:  Running analysis…  ⟳                                  |
| eng:  Done — Crohn's overtook UC in Tremfya's IBD mix.      |
|       [ Open result ]   Build a deck?  [ Yes ] [ No ]       |
| you:  Yes                                                   |
| eng:  Deck ready.  [ Download deck ]                        |
| [ type a reply………………………………………… ]  [ Send ]                  |
+-------------------------------------------------------------+
```

Behaviour:
- Render transcript from `messages`. Bubbles by `role`. `question` and
  `deck_offer` render their `options` as clickable chips; clicking posts a `text`
  message with `chosen=<label>` and `in_reply_to=<that msg seq>`. Free-text box is
  always available.
- `result` → "Open result" button → `loadViews()` then `showResult(view_id)`
  (refresh first, like `engine.js` — the chat-registered view may not be in the
  cached list yet).
- `deck_ready` → "Download deck" link → `deck_url` (existing `/api/views/{id}/deck`).
- Input + chips disabled while `turn=engine`; show `engine_status` (fallback
  "engine working…") + spinner.
- Poll lifecycle is driven by the observed `turn`, not started once. The repaint
  function must, on every `GET /api/chat` fetch AND on the `POST /api/chat/message`
  response, (re)schedule a poll iff `turn==engine` and clear the timer otherwise
  (mirror `engine.js`'s active-predicate scheduling, engine.js:27-29). This is what
  restarts polling for the next engine turn after a clarifying-question
  round-trip — without it, the second and subsequent engine turns in a
  multi-question brainstorm would never be polled and the UI would hang on "engine
  working…". The poll that first observes `turn=user` renders the new engine
  messages, re-enables input, and clears the timer (event-light, matches
  `engine.js`). Reuse the `pollMisses` tolerance: after 5 consecutive
  failed polls, toast "Chat poll lost". Separately, if the thread sits
  `turn=engine` with no new engine message / `engine_status` change for ~30s, show
  an actionable hint: "waiting for the engine — is the /loop session running?"
  with a **Reset turn** button that POSTs `/api/chat/reset-turn` (flips
  `turn=user`, re-enables input) so the user can re-send or rephrase without
  discarding the question. Without this, a dead loop wedges the chat: the 409
  guard blocks every subsequent send while `turn=engine`, and New chat would
  discard the pending question.
- `New chat` posts `/api/chat/new`; if 409, confirm "discard the running chat?"
  then retry with `{force:true}`.
- Only repaint when the fetched thread JSON differs from the last (mirror
  `engine.js` `lastItemsJson` guard), but the diff must stringify the WHOLE thread
  JSON — including `engine_status`. ANY thread-JSON diff repaints, including an
  `engine_status`-only change while `turn=engine` (no new message), so the running
  spinner/label updates live and §9's "browser shows progress, not a frozen UI"
  holds. Observing `turn=user` additionally re-enables input and stops the poll.

## 9. Concurrency & integrity

- **`turn` is the mutex; atomic file replace.** Both the browser (via server) and
  the loop write `active.json` by re-read → append-by-seq → atomic temp-rename
  (`os.replace`). The `turn` field gates who may write: the browser only appends
  when `turn=user`, the loop only when `turn=engine`. `os.replace` is atomic on
  Windows NTFS but raises `PermissionError` (sharing violation) if the destination
  is momentarily open by another reader or AV — realistic with two processes
  touching `active.json` on a 3 s cadence. Wrap the replace in a short bounded
  retry (≈3 attempts, 50–100 ms backoff) catching `PermissionError`; surface a
  clean miss rather than an unhandled 500 / loop crash if it still fails.
- **Two race windows — one closed in-process, one residual cross-process.**
  - *Intra-server (closed).* The FastAPI routes are sync `def` on uvicorn's
    threadpool, so two concurrent POSTs (a double-clicked Send, or Send racing
    New chat) could both read `turn=user`, both pass a bare 409 check, both
    compute `seq=len+1`, and the second `os.replace` would clobber the first —
    a lost user message and a duplicated seq, reachable by one user with no loop
    involved. This window is closed by the §7 module-level lock: the
    read → 409-check → append → replace runs inside the lock, `turn` is re-read
    and re-validated immediately before replace (detect-and-reject, returning 409
    if it flipped), and a duplicate computed `seq` is rejected. The 409 is
    race-free only because of this compare-before-replace, not on its own.
  - *Cross-process (residual, tolerated).* The server and the live Claude session
    are independent processes; no shared kernel lock spans them, so the `turn`
    gate between them stays advisory. The only instant both could write is the
    turn-handoff (the loop's final write flipping `turn=engine→user` racing a
    browser send). Given a single-user, human-paced, 3 s-polled demo this is
    negligible and **accepted**; the atomic replace guarantees the file is never
    left half-written (worst case a single lost append, recoverable by re-sending).
    A future hardening is an advisory `engine_chat/.lock` file — out of scope (§10).
- **Path containment (security).** `thread_id`, `run_folder`, and `view_id` are
  free strings that get joined into filesystem paths (e.g.
  `config.get_root()/v['folder']` to serve `result.csv`/`deck.pptx`, app.py:94,142,
  and `engine_chat/archive/<thread_id>.json`). Validate before any path use:
  `thread_id` must match `^chat_[0-9_]+$`; any `run_folder`/`view_id` resolved to a
  path must be contained within `output_dir()` (resolve the path and assert it
  startswith the resolved output root) — reject `..` and absolute escapes with a
  400. This also hardens the existing `/deck` and `/result` endpoints, which take
  the folder from `views.yaml` without a containment check today.
- **The analysis run itself** happens in the live session (`py -3`), like inbox
  processing today — no `runner.run_lock` needed for it. Dashboard-initiated view
  re-runs continue to use the existing lock; they are a separate path.
- **Tick cadence:** the loop processes at most one engine turn per tick. Long runs
  surface as `engine_status` updates so the browser shows progress, not a frozen UI.

## 10. Out of scope (YAGNI)

- Multiple concurrent / persisted in-UI chat history (single active chat only;
  archive files exist on disk but no in-UI list).
- Streaming token-by-token output (turn-granular messages only).
- Auth / multi-user threads (single-user demo).
- Editing `/semantic/` or `/metadata/` rules through the chat (rule changes stay a
  deliberate terminal action with a git commit, per CLAUDE.md §3).
- A kernel-grade write lock. The advisory `engine_chat/.lock` hardening noted in §9
  is deferred; the turn-mutex + atomic replace is sufficient for the demo.

## 11. Build order

1. `ENGINE_CHAT.md` protocol doc (defines the contract both sides honor) +
   `config.engine_chat_dir()`.
2. `server/chat.py` + the four `/api/chat*` routes (`POST /api/chat/message`,
   `GET /api/chat`, `POST /api/chat/reset-turn`, `POST /api/chat/new`) + atomic
   write helper.
3. `web/js/chat.js` + the mode toggle + transcript/chips/poll in `index.html`.
4. Manual end-to-end: start `/loop check engine_chat`, run a full brainstorm →
   analysis → deck → follow-up → deck-revise cycle from the browser.
5. Update `MEMORY.md` (new interactive engine path, the `engine_chat/` thread model,
   the `/loop check engine_chat` command) so a fresh session resumes aware of it.

## 12. Acceptance criteria

- From the browser, a user can: send a question, receive and answer a structured
  clarifying question (chip or free text), see the analysis run, open the result,
  request and download a deck, ask an analysis follow-up (new run_id, prior plan
  inherited), and request a deck revision (same run folder) — all without touching
  the terminal.
- The existing one-shot inbox ask still works unchanged.
- The server runs no LLM; every reasoning step is the live session.
- Every delivered run has the CLAUDE.md 6-file contract and a `views.yaml` entry.
- `active.json` is never left half-written (atomic replace); the sole tolerated
  race is the turn-handoff window (§9), accepted for a single-user demo.
```

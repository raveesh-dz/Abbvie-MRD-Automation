# Engine Chat Protocol — CLI Mirror

The dashboard's "Brainstorm chat" is a **semantic mirror of ONE always-on Claude
Code session** that behaves exactly like the terminal CLI. The server is a dumb
file broker; this session is the brain. You are launched once via `/serve-engine`
(see `.claude/commands/serve-engine.md`) and run a single persistent foreground
serve-loop: block until `engine_chat/active.json` has `turn == "engine"`, handle
that turn **in-process with full context**, set `turn=user`, and re-block. You
NEVER re-read this file from scratch per turn and you NEVER reset context between
turns. This is not a script of what to say — it is the transport contract plus a
delegation to behave like the terminal.

## Boot gate (once per session, before the first analysis run)
Complete CLAUDE.md §0: read MEMORY.md; `git status -- semantic/ metadata/`;
`py -3 scripts/validate_schema.py`; load all of /metadata/ and /semantic/; check
stale auto-saved rules. If the schema gate reports drift, do NOT analyze — append
an `error` message naming the table + mismatched columns, set status=failed,
turn=user, stop. **Re-run (or cheaply re-validate) this gate after any compaction
and on every relaunch** — a compacted/fresh process cannot assume the dictionaries
are loaded (hard rule: never analyze a table whose dictionary fails validation).

## 5a. Transport / rendering contract (mechanical)
- A turn arrives as the latest user message(s) in `active.json` while `turn=engine`.
  The server already flipped `turn=engine` on the user send; you own the file for
  this turn (the server 409s any user write while `turn=engine`).
- Render every user-facing output as a thread message of an existing kind ONLY:
  `text {text}`, `question {text, options[]}`, `result {text, view_id, run_folder}`,
  `deck_offer {text, options:["Yes","No"]}`, `deck_ready {text, deck_url}`,
  `error {text}`. Do NOT use the terminal's native question UI.
- **On wake, set `engine_status` promptly (e.g. `"thinking…"`) BEFORE any long work**
  — this is the proof-of-pickup that distinguishes a live-but-slow turn from a dead
  session. Keep updating `engine_status` at each internal stage
  (`"generating code…"` → `"validating…"` → `"building deck…"`) so a long converged
  run never looks stalled (the browser's 30s stall hint resets on every JSON change).
- **`turn` stays `engine` for the FULL duration of a turn** — boot/schema gate, code
  generation, execution, validation, deck build — and flips to `user` only at the
  single terminal append. Clear `engine_status=null` on that flip.
- Append engine messages by the same `len(messages)+1` seq rule and write via the
  same atomic pattern (`active.json.tmp` → `os.replace`) the server uses. Multiple
  messages in one turn (e.g. `result` + `deck_offer`) get consecutive seqs in one
  atomic write, never duplicating a seq.
- **Durable non-rendered state (you write these every engine turn; the server never
  reads them):**
  - `brainstorm_phase`: one of `gathering` | `approaches_presented` |
    `awaiting_approval` | `approved` | `converged`. Authoritative for the approval
    gate and for compaction recovery. The thread tail is corroboration only.
  - `skill_invocations`: append `{skill:"superpowers:brainstorming", seq:<N>}` the
    moment you invoke the skill on a turn, before any message append — the automatable
    §11 proof that the skill actually fired (checkable via `jq` on `active.json`, no
    transcript archaeology). Record `seq` as the seq of the first engine message
    produced on that turn (or `null` if the skill produced no rendered message that
    turn).

## 5b. Behavioral instruction (delegation, not a script)
You are in one continuous conversation. Each user message is the next turn.
**Behave exactly as you would in the terminal Claude Code session.**
- For a **new analytical request**, invoke `superpowers:brainstorming` and follow
  its process (record the `skill_invocations` marker).
- For a **follow-up** on an existing run, treat it as a CLAUDE.md follow-up.
- For a **deck request/revision**, build/revise the deck.
Your only added constraint is the §5a rendering contract: surface user-facing turns
as thread messages and end the turn with `turn=user`. "No script" means no canned
phrasing — it does NOT remove the §6 deterministic routing below.

## 6. Brainstorming → thread mapping (engine-specific overrides)
CLAUDE.md governs, so the generic skill is adapted:

On a NEW analytical request, before invoking the skill set `brainstorm_phase=gathering`
and initialize `skill_invocations=[]` if absent (a pre-existing thread already carries
them). `gathering` is therefore the entry phase every new request starts in.

| brainstorming step | engine rendering |
|---|---|
| explore project context | already held (boot gate / MEMORY) |
| clarifying questions, one at a time | `question` messages (chips when clean options, else prose `text`) |
| propose 2–3 approaches | a `question` (or `text`) presenting the options; set `brainstorm_phase=approaches_presented` |
| present design + approval gate | a `question` with **Approve / Revise** options; set `brainstorm_phase=awaiting_approval`. HARD-GATE: do NOT run the analysis until approved (enforced by the gate-check below). |
| write design doc to `docs/.../specs` | **skipped** — replaced by `analysis_plan.md` in the run folder (CLAUDE.md Step 3) |
| terminal: invoke `writing-plans` | **overridden** — convergence runs the CLAUDE.md analysis workflow (generate `analysis_code.py` → execute → validate → result + context + takeaways), then offers a deck |

The visual-companion offer is **suppressed** (the dashboard is the surface).

Documented defaults still apply (CLAUDE.md Step 2): when the user defers ("whatever
you think") or a documented default exists (e.g. R13W window), apply it, record it
in `analysis_plan.md` as `default applied, not user-confirmed`, and proceed without
blocking on a chip.

### Approval gate-check (deterministic precondition — keyed on `brainstorm_phase`)
You MUST NOT enter the CONVERGED branch (which writes `output/<run_id>` + a
`views.yaml` entry — a real side effect) unless ALL hold:
1. `brainstorm_phase == "approved"` (you set this only after the presented-design
   gate was satisfied on that turn).
2. Corroborating tail: the preceding **engine** message was a `question` whose
   `options` include `Approve` and `Revise`, AND the latest **user** message is
   `in_reply_to` that question's `seq` with `chosen == "Approve"`. A typed revision
   is treated as **Revise** → set `brainstorm_phase` back to `awaiting_approval`,
   present a revised design, do NOT run.
On recovery the durable `brainstorm_phase` is the SOLE source of truth for the gate;
the tail is corroboration only. If `brainstorm_phase==approved` but the preceding
Approve/Revise question is missing (an incomplete write), trust the durable field and
resume the workflow — do NOT re-present the gate. If the tail genuinely CONTRADICTS
the durable field (e.g. durable==approved but tail shows an unanswered
awaiting_approval), prefer the durable field and re-present only when the durable field
itself is not `approved`.
- Set `brainstorm_phase=converged` only after the CONVERGED branch completes (6-file
  contract written to `output/<run_id>`, `views.yaml` entry appended, `result` +
  `deck_offer` appended) and immediately before the terminal `turn=user` flip. On
  relaunch a thread with `converged` + `analysis_plan.md` present resumes at
  result-presentation, not brainstorming.

### Retained deterministic routing (carried forward; do NOT drop)
- **New analytical request** → invoke `superpowers:brainstorming` (gathering →
  converged).
- **Follow-up** (analysis change on the current run) → new `run_id`,
  `base_plan = current run`, deltas only; re-run; update thread `run_folder`/`view_id`;
  append `result` + `deck_offer`. NEVER re-brainstorm a follow-up from scratch.
- **Deck-revise** → edit `deck_spec.json` in the CURRENT `run_folder`, rebuild in
  place, append a new `deck_ready`. No new `run_id`.
- **Bare deck request** while `run_folder` is set and the current run has no deck →
  route deterministically to building a deck on the current run; do NOT ask a
  clarifying question for it.
- **Ambiguity guard:** when `run_folder` is set and intent is genuinely ambiguous
  (follow-up vs new topic, revise vs new run), ask via a `question` rather than guess
  — guessing risks the wrong `base_plan` or re-brainstorming a follow-up.

### Deck builders (chart_kind dispatch)
Build with `build_deck_pptx.py` (default: line / wow_compare),
`monthly_multiline`→`build_deck_monthly.py`, `holdout_segments`→`build_deck_holdout.py`.
NOTE: the dashboard re-run path `server/views.py run_view_core` only dispatches
`monthly_multiline` vs the default — a chat-built `holdout_segments`/by-region deck
re-run FROM the dashboard would mis-render. The chat build path here is always
correct; wiring `run_view_core` is tracked non-blocking follow-up.

## 7. Compaction & crash recovery (durable-phase-driven)
`active.json` holds only rendered messages — it does NOT capture brainstorming
checklist state or whether the boot gate was satisfied. On any post-compaction
recovery, recover from the durable `brainstorm_phase` (thread tail = corroboration
only), and re-run the boot/schema gate before any converged run.

Thread-tail → phase mapping (corroborating `brainstorm_phase`):
- `gathering` (last engine msg a clarifying `question`, answered by a later user
  reply) → continue with the next UNANSWERED item; do not re-ask answered ones.
- `awaiting_approval` (last engine msg an Approve/Revise `question`, no later user
  Approve) → re-present the gate; do not run.
- `approved`, **pre-plan-write** (Approve reply received, `analysis_plan.md` not yet
  written) → resume at the CLAUDE.md workflow; if a run_folder was pre-created but
  `analysis_plan.md` is not yet written, reuse that `run_id` and re-run (idempotent);
  if no run_folder was created, generate a fresh `run_id`. Do NOT re-ask for approval.
  See crash guard.
- `approved`/`converged` with `analysis_plan.md` present for the current
  `run_folder` → resume at the CLAUDE.md workflow, not at brainstorming.

**Crash-after-run-folder, before-result-append window.** If the session crashed
after creating `output/<run_id>` (and maybe a `views.yaml` entry) but before
appending the `result` message, a naive relaunch would re-run and orphan the partial
run. Before re-running a converged analysis, check for an existing run folder +
`views.yaml` entry for the current `run_folder`: if a COMPLETE prior run exists
(6-file contract present, `views.yaml` registered), append the missing
`result`/`deck_offer` from it rather than re-running; only re-run (new `run_id`) if no
complete run folder is found.

## Failure & idempotency
- FAILURE anywhere → append `error {text:<one line>}`, set `turn=user`,
  `status=failed`. The user can reply to retry.
- Process one engine turn per block-and-continue. Never act when `turn=user`. Never
  re-emit a message that already exists (compare the messages tail before appending).

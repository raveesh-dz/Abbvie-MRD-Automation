# Engine as CLI Mirror — Design Spec

date: 2026-06-29
status: draft (pending user review)
author: R (Rounak.suranshe@datazymes.com) + engine
supersedes-behavior-of: ENGINE_CHAT.md (rewritten from script → transport contract)
builds-on: docs/superpowers/specs/2026-06-29-interactive-ask-the-engine-design.md (the transport/UI; committed)

## 1. Problem

In the committed interactive "Brainstorm chat" feature, the brain is a `/loop` that
re-prompts on each cycle, reads the thread file with fresh context, and follows
`ENGINE_CHAT.md`. That file's GATHERING branch (ENGINE_CHAT.md:23) *does* instruct
the engine to "run the brainstorming skill" — the file is not the problem. The
problem is runtime: two consequences:

1. In practice the `superpowers:brainstorming` skill's multi-turn process does **not
   persist**. Each `/loop` tick is a fresh context (ENGINE_CHAT.md is re-read from
   scratch), so even though the file says to run the skill, the skill's stateful
   process — explore intent → one question at a time → propose approaches → present
   design → approval → converge — cannot survive from one tick to the next. The
   result is the engine improvising a single ad-hoc question rather than carrying the
   skill forward. Observed live: the engine asked one chip question, then ran.
2. The statelessness is structural: each wakeup is a fresh context, so even the
   *idea* of a continuous skill-driven conversation can't hold.

The dashboard should instead be a good-looking **face over one continuous Claude
Code session that behaves exactly like the terminal** — same context across turns,
same skills invoked naturally. When the conversation is genuinely continuous,
brainstorming fires the same way it does in the CLI, with no special protocol.

## 2. Goal

Make the "Brainstorm chat" mode a **semantic mirror** of a single always-on engine
session: the user types in the dashboard, the engine responds exactly as it would in
the terminal (invoking `superpowers:brainstorming` on a new analytical request,
running the CLAUDE.md workflow, offering a deck), and the dashboard renders the
session's turns through the existing chip/bubble UI.

## 3. Constraints / non-negotiables

- **No Agent SDK, no `claude -p`.** The brain is one live interactive `claude`
  session the user launches (same kind of session as the terminal).
- **Server stays a dumb file broker.** `server/chat.py`, the `/api/chat*` routes,
  and the atomic-write + turn-mutex are unchanged. The server runs no LLM.
- **Transport and UI are unchanged.** `web/js/chat.js`, the mode toggle, the message
  kinds (`text`/`question`/`result`/`deck_offer`/`deck_ready`/`error`), `engine_status`,
  and the `active.json` schema all stay as committed. The plan-approval step reuses
  the existing `question` kind (Approve/Revise options) — no new rendering code.
- **CLAUDE.md governs.** All its hard rules (no model arithmetic, declared joins only,
  validation before delivery, 6-file contract, follow-up = new run_id w/ base_plan,
  deck opt-in) hold inside the engine session exactly as in the terminal.
- **The existing one-shot inbox path stays untouched** (zero regression).

## 4. Architecture & data flow

```
Browser (chat UI)  ⇄  engine_chat/active.json  ⇄  ONE continuous engine session
   user sends   → POST /api/chat/message → append user msg, turn=engine
   the session's persistent serve-loop is blocking on a Monitor wait for turn==engine;
     the wait returns INTO the same running process (context intact) — it does not
     wake a parked/idle session
   the SAME process continues the conversation as the next turn → appends engine msg(s),
     turn=user → re-blocks on the next turn==engine
   browser polls GET /api/chat every 3s while turn=engine
```

The only architectural change from the committed feature is the **brain**: from a
fresh-context `/loop` re-entry following a script → one persistent session running a
single **continuous foreground serve-loop**, conversing normally. The serve-loop is
**net-new work that replaces the committed `/loop check engine_chat` brain** — it
does not exist in the repo yet (no source/skill references it).

The load-bearing shape is NOT "a Monitor event wakes a STOPPED/idle session." The
Monitor tool contract is explicit that events arrive *while you keep working* and are
*not replies from the user* — they notify an **active** session, they do not re-enter
one parked at an idle prompt. So the design is: the session is **never truly idle**.
It runs one persistent foreground loop that blocks on a Monitor wait until
`active.json` flips `turn==engine`, then the **same process** continues (it never
re-reads `ENGINE_CHAT.md` from scratch and never resets context), appends the engine
turn, sets `turn=user`, and re-blocks for the next turn. One long-lived process
handles many turns; context — including a loaded `brainstorming` process — survives
because the process itself never ends between turns. **The in-session-continuation
behavior MUST be empirically validated before this design is built** (see §7): does a
blocking-event return inside a still-running session retain prior-turn context and a
loaded skill?

## 5. `ENGINE_CHAT.md` — rewritten from script to transport contract

The file flips role entirely: from a behavioral script to a transport contract plus
delegation plus the §6 engine-specific overrides and retained routing. It MUST NOT
prescribe what the engine *says* (no canned phrasing), but it DOES retain the
deterministic *routing* rules (§6) — "no script" means no scripted wording, not no
routing logic. Its parts are: (5a) the transport/rendering contract, (5b) the
delegation, and (6) the engine overrides + retained routing + the approval gate-check.

### 5a. Transport / rendering contract (mechanical)
- A turn arrives as the latest user message(s) in `active.json` while `turn=engine`.
- Render user-facing output as thread messages of the existing kinds:
  `text`, `question {text, options[]}`, `result {text, view_id, run_folder}`,
  `deck_offer {options:["Yes","No"]}`, `deck_ready {text, deck_url}`, `error {text}`.
- Use `engine_status` (ephemeral) for live progress during long work. **On wake (the
  instant the serve-loop picks up a `turn==engine` turn) the engine MUST set
  `engine_status` promptly — e.g. `"thinking…"` — as a proof-of-pickup**, before any
  long internal work. This is what makes a never-woken (dead) session distinguishable
  from a slow-but-working one: see §8.5.
- End every turn by setting `turn=user`, `status` per the committed state machine.
- **`turn` stays `engine` for the FULL duration of a turn**, including all internal
  multi-step work (boot/schema gate, code generation, execution, validation, deck
  build) — it flips to `user` only at the single terminal append. This preserves the
  committed server guard (`server/chat.py:78-79` raises `Conflict` / 409 on any user
  send while `turn=engine`) and the UI input-disable, so a long-running turn cannot
  prematurely admit a racing user message mid-work.
- Seq/atomic-write rules are the server's job; the session appends engine messages
  by the same `len+1` rule and writes via the same atomic pattern.

### 5b. Behavioral instruction (delegation, not a script)
- "You are in one continuous conversation. Each user message is the next turn.
  **Behave exactly as you would in the terminal Claude Code session.**"
- "For a new analytical request, **invoke `superpowers:brainstorming`** and follow
  its process. For a follow-up on an existing run, treat it as a CLAUDE.md follow-up.
  For a deck request/revision, build/revise the deck."
- "Your only added constraint is the §5a rendering contract: surface your
  user-facing turns as thread messages and end with `turn=user`."

**"No behavioral script" means "no canned phrasing," not "no routing logic."** The
delegation above removes the scripted *wording* the old brain put in the engine's
mouth; it does NOT remove the committed deterministic *routing* (new-request vs
follow-up vs deck-revise vs bare-deck), which is retained as guidance in §6. The
engine still decides intent by judgment, but with the §6 routing rails and the §6
ambiguity guard so a misjudgment cannot silently re-ask a follow-up as a new
brainstorm or inherit the wrong `base_plan`.

The boot gate (CLAUDE.md §0 + schema gate) still applies once per session before the
first analysis run, exactly as in the committed `ENGINE_CHAT.md` — **plus** it must be
re-run (or cheaply re-validated) after any compaction, since a compacted session can
no longer assume the dictionaries are loaded (see §7 recovery).

## 6. Brainstorming → thread mapping (the subtle part)

The generic `superpowers:brainstorming` skill is written for software features and
terminates in `writing-plans`. In the analytics engine it is adapted — this mapping
is explicit and authoritative because **CLAUDE.md governs** the engine:

| brainstorming step | engine rendering |
|---|---|
| explore project context | the session already holds it (boot gate / MEMORY) |
| clarifying questions, one at a time | `question` messages (chips when clean options, else prose `text`) |
| propose 2-3 approaches | a `question` (or `text`) message presenting the options |
| present design + **approval gate** | a `question` with **Approve / Revise** options; HARD-GATE becomes "do not run the analysis until the plan is approved." Because the server is a dumb broker and the only guard is engine discipline, this gate is enforced by a **deterministic precondition** the engine checks before the CONVERGED branch (see §6 gate-check below). |
| write design doc to `docs/.../specs` | **skipped** — replaced by `analysis_plan.md` in the run folder (CLAUDE.md Step 3) |
| terminal: invoke `writing-plans` | **overridden** — convergence runs the CLAUDE.md analysis workflow (generate `analysis_code.py` → execute → validate → result + context + takeaways), then offers a deck |

**Approval gate-check (deterministic precondition, written into `ENGINE_CHAT.md`).**
The gate decision is keyed on the authoritative **`brainstorm_phase`** field (§7), with
the thread tail used only to corroborate. The engine MUST NOT enter the CONVERGED
branch (which writes `output/<run_id>` and a `views.yaml` entry — a real side effect)
unless ALL of the following hold:
1. `brainstorm_phase == "approved"` (the engine wrote this only after the
   presented-design gate was satisfied on that turn).
2. Corroborating tail: the preceding **engine** message was a `question` whose
   `options` include `Approve` and `Revise`, AND the latest **user** message is
   `in_reply_to` that question's `seq` with `chosen == "Approve"`. A typed revision is
   — per the committed reply-association rule (interactive-ask-the-engine spec §"chip
   vs typed answer") — treated as **Revise** (set `brainstorm_phase` back to
   `awaiting_approval`, present a revised design, do NOT run).
If `brainstorm_phase` is not `approved`, or the tail contradicts it, the engine stays
in its current phase and re-presents the gate; it never runs the analysis on a misread
thread tail, and a compaction landing on the tail cannot flip the gate because the
durable field — not the tail — is authoritative. This makes the HARD-GATE enforceable
without server help. (One exception, per §7 recovery: a recovered
`brainstorm_phase=approved` whose analysis already converged resumes the workflow under
a new `run_id` rather than re-presenting the gate — re-running converged analysis is
idempotent.)

**Retained deterministic routing (carried forward from committed `ENGINE_CHAT.md`
steps 5/6/6a/8).** The rewrite does NOT drop these rules; they remain authoritative
guidance in `ENGINE_CHAT.md` because they prevent the engine from misrouting intent:
- **New analytical request** → invoke `superpowers:brainstorming` (the gathering →
  converged path above).
- **Follow-up** (an analysis change on the current run) → new `run_id`,
  `base_plan = current run`, deltas only; re-run; update thread `run_folder`/`view_id`;
  append `result` + `deck_offer`. (Never re-brainstorm a follow-up from scratch.)
- **Deck-revise** → edit `deck_spec.json` in the **current** `run_folder`, rebuild in
  place, append a new `deck_ready`. No new `run_id`.
- **Bare deck request while `run_folder` is set and the current run has no deck** →
  routes deterministically to building a deck on the current run; do NOT ask a
  clarifying question for it.

**Ambiguity guard (mirrors the approval gate).** When `run_folder` is set and the
intent is genuinely ambiguous between a follow-up and a new topic (or between revise
and a new run), the engine MUST ask via a `question` rather than guess — exactly as
the committed step 8 already requires. Guessing risks inheriting the wrong
`base_plan` or re-brainstorming a follow-up; the ask is the recovery.

Two brainstorming defaults that would mis-fit are explicitly neutralized in
`ENGINE_CHAT.md`: (1) the design-doc-to-`specs/` step is replaced by `analysis_plan.md`;
(2) the "ONLY invoke writing-plans" terminal is replaced by the CLAUDE.md workflow.
The visual-companion offer is also suppressed (the dashboard is the surface).

Documented defaults still apply per CLAUDE.md Step 2: when the user defers
("whatever you think") or a documented default exists (e.g. R13W window), apply it,
record it in `analysis_plan.md`, and proceed without blocking on a chip.

## 7. Launch mechanism — the always-on engine session

A single documented launch path the user runs once, replacing the committed
`/loop check engine_chat and process the active conversation` brain. It is a **small
skill or documented prompt** (working name `/serve-engine`) that, in one live session:

1. Runs the CLAUDE.md §0 boot sequence + schema gate once.
2. Enters one **persistent foreground serve-loop** that blocks on a Monitor wait over
   `engine_chat/active.json` until `turn == "engine"` (the `user→engine` flip the
   server sets on each user send). The loop never exits between turns: block → handle
   turn → re-block, all inside the same process. This loop is net-new (no committed
   command does this today). **Before building, the implementer MUST empirically
   confirm the in-session-continuation shape**: that when the blocking Monitor wait
   returns inside a still-running session, the session retains prior-turn context and
   any skill it had loaded (e.g. a mid-flight `brainstorming` process), and proceeds
   to execute the new turn — rather than the contract's documented behavior of merely
   *notifying* an active session. The validation test is concrete: after a blocking
   event returns, does an in-session continuation still reference the previous turn's
   answers AND keep a loaded skill active? Do NOT frame this as "waking a STOPPED
   session" — the Monitor contract does not re-enter idle sessions, so the loop must
   stay non-idle by design.
3. When the wait returns, the SAME process reads the new user message and **continues
   the conversation as the next turn** — invoking skills naturally per §5b — then
   re-blocks on the next `turn == "engine"`.
4. **Does NOT use a context-resetting re-entry.** The committed brain re-prompts
   `/loop check engine_chat ...` as a *fresh context each cycle* — that fresh-context
   re-entry is what made the engine stateless and scripted; it is explicitly NOT used
   here. A single never-returning serve-loop carries context across all turns. (Note
   the tension this resolves: a `/loop` re-prompt is exactly the fresh-context
   re-entry we reject; the serve-loop is one process that blocks-and-continues, not a
   loop that re-launches the prompt.)
5. **Continuation contract (what "continue" means at the block point).** When the
   blocking wait returns, the loop issues no fresh "process the thread" task; it
   simply proceeds in-process to handle the next user turn with full context. The
   build-blocking open question is whether the harness preserves context + loaded
   skills across a blocking Monitor return inside one session (step 2). If validation
   shows it does NOT, the design must be revised before build — the diagram and §11
   acceptance below MUST NOT be shipped asserting this behavior until it is proven.

Context durability: across a very long conversation the session may compact. The
thread file is the durable record, but `active.json` holds only **rendered messages**
— it does NOT capture brainstorming checklist state (which clarifying questions are
already answered, whether the approval gate was reached) nor whether the CLAUDE.md §0
boot/schema gate has been satisfied. Re-reading the thread and blindly re-invoking the
skill would let a post-compaction run re-ask answered questions, skip the approval
gate, or analyze against stale/unloaded dictionaries — the last of which violates the
CLAUDE.md hard rule against analyzing an unvalidated table.

Recovery therefore requires a **durable phase marker**. The **mandatory, authoritative**
marker is a non-rendered field on `active.json`, `brainstorm_phase`, written by the
engine on **every** turn with one of `gathering` | `approaches_presented` |
`awaiting_approval` | `approved` | `converged`. The thread tail is **corroboration
only** — it is consulted to detect a contradiction, never as the sole basis for the
gate decision (compaction or an unlucky tail must not be able to flip the gate). The
presence of `analysis_plan.md` in a run folder is a secondary corroborating signal
(it can only have been written post-approval, per CLAUDE.md Step 3), not the primary
marker.

Thread-tail → phase mapping on recovery (corroborating the `brainstorm_phase` field):
- `brainstorm_phase=awaiting_approval` (last engine message is a `question` with
  Approve/Revise options and no later user Approve reply) → re-present the gate, do
  not run.
- `brainstorm_phase=gathering` (last engine message is a clarifying `question`
  answered by a later user reply) → continue with the next unanswered item (do not
  re-ask answered ones).
- `brainstorm_phase=approved`, **pre-plan-write** (Approve reply received but
  `analysis_plan.md` not yet written) → **resume at the CLAUDE.md workflow, not at the
  approval gate.** Re-running a converged analysis is idempotent under a **new
  `run_id`**, so this state resumes the workflow rather than re-presenting the gate;
  do not re-ask the user to approve. (See the crash-window guard below before
  re-running.)
- `brainstorm_phase=approved`/`converged` with `analysis_plan.md` present for the
  current `run_folder` → resume at the CLAUDE.md workflow, not at brainstorming.

**Crash-after-run-folder, before-result-append window.** If the session crashes after
it has created `output/<run_id>` (and possibly a `views.yaml` entry) but before
appending the `result` message, a naive relaunch would re-run and orphan the partial
run. On relaunch, **before re-running a converged analysis, check for an existing run
folder + `views.yaml` entry for the current `run_folder`**: if a complete prior run
exists (6-file contract present, `views.yaml` registered), append the missing
`result`/`deck_offer` from it rather than re-running; only re-run (new `run_id`) if no
complete run folder is found. This closes the duplicate-run window on crash recovery.

On any post-compaction recovery, **re-run the CLAUDE.md §0 schema/boot gate (or a cheap
re-validation: `py -3 scripts/validate_schema.py` + confirm `/metadata`+`/semantic`
are loaded) before any converged analysis run** — a compacted session cannot assume
the dictionaries are still in context. Only after the gate passes and the phase marker
is recovered may the session re-invoke `superpowers:brainstorming` (mid-brainstorm) or
resume the workflow (post-approval). This is the one place state can be lost and
recovered.

## 8. What stays unchanged (no work)

- `server/chat.py`, `server/config.py` (`engine_chat_dir`, `assert_within_output`),
  the `/api/chat message|get|reset-turn|new` routes.
- `web/js/chat.js` (transport + polling + stall/reset logic), the mode toggle in
  `index.html`, `web/js/api.js` (`err.status`), the chat styles.
- The `active.json` schema and the state machine (`turn`/`status`/`engine_status`).
  (§7 recovery's mandatory non-rendered `brainstorm_phase` field — and the §11
  `skill_invocations` provenance marker — are additive and engine-written; the server
  neither reads nor validates them, so its broker contract is unchanged.)
- The committed `tests/test_chat.py`.

**One-line copy edits (the only chat.js change):** the committed stall hint string at
`web/js/chat.js:50` (inside the `if (stalled)` block at lines 49-52) reads "is the
/loop session running?", which is inaccurate under the new always-on model — change it
to "is the engine session running?". No logic changes.

**Deck-builder caveat (carried forward).** The dashboard re-run path
`server/views.py:run_view_core` (lines ~166-174) dispatches a builder by
`deck_spec.json.chart_kind` and only knows two: `build_deck_pptx.py` (default,
line/wow_compare) and `build_deck_monthly.py` (`monthly_multiline`). It has **no
`holdout_segments` or by-region branch** — even though `ENGINE_CHAT.md:43` lets the
chat engine build a holdout deck via `build_deck_holdout.py` directly. A freely
conversing engine can now reach deck shapes (holdout, by-region) with no correct
dashboard builder, so a chat-built non-line deck **re-run from the dashboard would
mis-render** (fall through to the default builder). Decks are correct on the
dashboard re-run path only for the line/`wow_compare`/`monthly_multiline`/holdout
builders the engine builds in place; wiring `run_view_core` to dispatch
`holdout_segments`/by-region is tracked as **non-blocking follow-up work**, not part
of this design.

## 8.5. Operator notes — liveness, death, restart

The always-on engine session is now the **single point of failure** (one long-lived
brain replacing the per-tick `/loop`). The server and UI are unchanged, so the
operator story is:

- **Liveness signal (unchanged).** While `turn=engine`, the browser polls every 3s; if
  the thread JSON does not change for 30s the UI shows the stall hint + a **Reset turn**
  button (`web/js/chat.js:49-52, 85-86`; the server `reset_turn()` helper at
  `server/chat.py:102`, exposed via `POST /api/chat/reset-turn` in
  `server/app.py:213`, flips `turn` back to `user`). This affordance is retained
  verbatim as the liveness signal — no new heartbeat is added.
- **Long analysis vs dead session.** A long converged run can legitimately exceed 30s.
  Distinguish the two via the ephemeral `engine_status` line: a **live** long turn keeps
  updating `engine_status` (e.g. "generating code…" → "validating…" → "building deck…"),
  so the thread JSON keeps changing and the 30s stall timer keeps resetting. A **dead**
  session leaves `engine_status` frozen and `turn` stuck at `engine`; the 30s stall hint
  then correctly fires. Implementation note: the engine SHOULD update `engine_status` at
  each internal stage precisely so a healthy long run never looks dead.
- **Proof-of-pickup (first turn after a send).** On the very first turn after a user
  send there is no prior `engine_status` to "freeze," so a never-woken session would be
  indistinguishable from a slow working one for a full 30s — the exact silent stall this
  design aims to eliminate. The contract closing the gap (per §5a): on wake the engine
  sets `engine_status` promptly (e.g. `"thinking…"`). The dead-session signal is therefore
  the **absence of any `engine_status` change within N seconds of the `user→engine` flip**
  (N small, e.g. ≤5s — well under the 30s long-work threshold), which is a distinct signal
  from "engine is working" (status present and advancing). Note the server clears
  `engine_status=null` on the user send (chat.py:90), so the engine writing any non-null
  `engine_status` is itself the observable pickup edge.
- **Restart procedure.** If the session dies (or the operator restarts it): re-launch the
  `/serve-engine` path. The relaunch MUST (a) re-arm the persistent Monitor on the
  **existing** `engine_chat/active.json` (do not create a new thread — the in-flight
  conversation lives there), and (b) re-run the CLAUDE.md §0 boot/schema gate, OR skip it
  only if a cheap re-validation confirms `/metadata`+`/semantic` are loaded and schema is
  clean (a fresh process always re-runs it; see §7 recovery). If the dead session left
  `turn=engine`, the operator clicks **Reset turn** (or the relaunch detects a stale
  `turn=engine` with a frozen `engine_status` and re-drives that pending user turn) before
  the conversation can continue.

## 9. Out of scope (YAGNI)

- Raw terminal mirror (xterm.js/PTY) — rejected; the semantic mirror is the goal.
- Multiple concurrent engine sessions / multi-user — one always-on session.
- Auto-launching the engine session from the server — the user launches it (the
  server must never spawn an LLM).
- Re-deriving the brainstorming skill's full process inside `ENGINE_CHAT.md` — the
  skill is invoked, not transcribed (only the engine-specific *overrides* in §6 are
  written down).

## 10. Risks

- **Context loss on compaction mid-brainstorm.** Mitigated by §7 recovery: the
  mandatory durable phase marker (the authoritative `brainstorm_phase` field, with
  `analysis_plan.md` presence as corroboration) drives a thread-tail → phase mapping
  so answered questions are not re-asked and the approval gate is not skipped, AND the
  CLAUDE.md §0 schema/boot gate is re-run (or cheaply
  re-validated) before any post-compaction converged run so a compacted session never
  analyzes against unloaded/stale dictionaries. The thread is the source of truth for
  rendered messages; the phase marker is the source of truth for process state.
- **The engine "runs ahead" without the approval gate.** The server cannot enforce
  this (dumb broker); the only guard is engine discipline, which a misread thread tail
  could bypass and produce a committed `output/<run_id>` + `views.yaml` side effect.
  Mitigated by §6's **deterministic gate-check precondition**: the CONVERGED branch
  runs only if the immediately-preceding engine message was an Approve/Revise
  `question` AND the latest user reply is `in_reply_to` that seq with
  `chosen == "Approve"` (a typed revision is treated as Revise). The boot/validation
  rules are unchanged.
- **A re-entry silently reverting to scripted behavior.** There is no context-resetting
  re-entry at all: the §7 serve-loop blocks and continues in one process, so turns are
  in-session continuations, not re-launches. Continuation carries no behavioral script
  — it is always "continue the conversation," never "process the thread." (No separate
  fallback heartbeat is specified; liveness is the existing Reset-turn affordance + 30s
  stall hint — see §8 / Operator notes.)

## 11. Acceptance criteria

- Sending a new analytical question in Brainstorm chat causes the engine session to
  **actually invoke `superpowers:brainstorming`** — and this is verified by an
  **inspectable, automatable invocation signal**, not by the observable
  Q&A→plan→approve shape alone (that shape can be improvised without ever firing the
  Skill tool, which is the exact failure this spec exists to fix). The Q&A→plan→approve
  rendering is **explicitly insufficient on its own**. Two checkable artifacts, in
  order of preference:
  1. **Durable provenance marker (preferred — checkable from `active.json`, no
     transcript archaeology).** On skill invocation the engine appends a non-rendered
     marker to `active.json` — e.g. a `skill_invocations` array entry
     `{skill:"superpowers:brainstorming", seq:<N>}` (additive, engine-written; the
     server neither reads nor validates it, so its broker contract is unchanged, per
     §8). Pass = the marker for `superpowers:brainstorming` is present on the turn that
     handled the new question. This is automatable (`jq` on `active.json`) and survives
     the fact that `active.json` does NOT persist a full transcript (§7).
  2. **Session-log grep (fallback).** The Claude Code session transcript is the JSONL
     under `~/.claude/projects/C--Users-RounakSuranshe-Documents-Projects-Abbvie-MRD-Automation/<session>.jsonl`.
     Pass = a tool-use entry naming `superpowers:brainstorming` (grep target:
     `"name":"Skill"` with `"superpowers:brainstorming"`) on the relevant turn.
  (Secondary corroboration, if the skill exposes one: the ordered checklist task list
  it creates appears in the session — confirm against the skill's actual behavior
  before relying on it.)
- The engine keeps context across turns within one session (a later turn references
  earlier ones without re-asking).
- On Approve, the engine runs the CLAUDE.md workflow, delivers the 6-file contract +
  `views.yaml` entry, posts a `result`, and offers a deck — exactly as the terminal.
- `ENGINE_CHAT.md` contains no behavioral script telling the engine *what to say* (no
  canned phrasing) — only the §5a transport contract + §5b delegation + §6 overrides
  and **retained deterministic routing** (new-request / follow-up / deck-revise /
  bare-deck + the ambiguity guard, carried forward from the committed file).
- The launch path produces a continuous session running a single foreground
  serve-loop (block on Monitor wait for `turn==engine` → handle turn in-process →
  re-block) with no context-resetting re-entry. This criterion is gated on the §7
  step-2 validation passing: it MUST NOT be claimed met until an in-session
  continuation after a blocking event is shown to retain prior-turn context and a
  loaded skill.
- The committed transport/UI/tests are unchanged; the one-shot inbox path still works.

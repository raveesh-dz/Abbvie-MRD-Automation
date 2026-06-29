# Engine as CLI Mirror Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **EXCEPTION — Task 1 is NOT a subagent task.** It is a validation spike that must run in a live, foreground, interactive Claude Code session (the same runtime kind that will run `/serve-engine`), because it tests whether *this session* retains context across a blocking-event re-invocation. A subagent is fire-and-forget and cannot exhibit the cross-turn continuation being measured. Run Task 1 inline / by the operator. Tasks 2–6 are subagent-eligible. **Task 1 is a hard GO/NO-GO gate: if it fails, STOP and revise the design before any further build.**

**Goal:** Make the dashboard "Brainstorm chat" a semantic mirror of ONE always-on continuous Claude Code session that behaves exactly like the terminal CLI — so `superpowers:brainstorming` actually fires on a new analytical request, instead of the current stateless `/loop` improvising one ad-hoc question.

**Architecture:** The only architectural change from the committed interactive feature is the **brain**. Replace the fresh-context-per-tick `/loop check engine_chat` re-entry with ONE persistent foreground serve-loop in a single live session: the loop blocks on a wait over `engine_chat/active.json` until `turn==engine`, then the **same process** continues the conversation in-process (full context + any loaded skill intact), appends the engine turn, sets `turn=user`, and re-blocks. No Agent SDK, no `claude -p`, no context-resetting re-entry. The server, transport, UI, and tests are unchanged (verify-don't-touch). `ENGINE_CHAT.md` flips from a behavioral script to a transport/rendering contract + delegation + the engine-specific brainstorming overrides + retained deterministic routing. A durable non-rendered `brainstorm_phase` field on `active.json` (engine-written, server-preserved) is authoritative for the approval gate and compaction recovery.

**Tech Stack:** Python 3.14 (`py -3`), FastAPI + uvicorn (unchanged), pytest + the repo's `repo_copy` fixture for backend, vanilla ES-module JS verified manually (no JS test harness), Claude Code slash command (`.claude/commands/serve-engine.md`) for the launch path, Bash `run_in_background` blocking-wait primitive for the serve-loop.

**Spec:** `docs/superpowers/specs/2026-06-29-engine-as-cli-mirror-design.md` (reviewed, 792/1000)
**Builds on:** `docs/superpowers/specs/2026-06-29-interactive-ask-the-engine-design.md` (committed transport/UI; SDD ledger `.superpowers/sdd/progress.md`)

## Global Constraints

- **No Agent SDK, no `claude -p`.** The brain is one live interactive `claude` session the user launches. (spec §3)
- **Server stays a dumb file broker.** `server/chat.py`, the `/api/chat*` routes, the turn-mutex + atomic write are UNCHANGED. The server runs no LLM and is never edited by this plan. (spec §3, §8)
- **Transport and UI are unchanged** except ONE copy-edit string (`web/js/chat.js:50`). `web/js/chat.js` logic, the mode toggle, message kinds (`text`/`question`/`result`/`deck_offer`/`deck_ready`/`error`), `engine_status`, `api.js` `err.status`, and the `active.json` schema all stay as committed. (spec §8)
- **`active.json` schema is unextended at the server.** The new `brainstorm_phase` and `skill_invocations` fields are **additive, engine-written, non-rendered**; the server neither reads nor validates them. They survive server writes only because `chat.py` mutates the loaded dict in place (verified: `post_message`/`reset_turn`/`new_chat` do `json.loads(raw)` then mutate — unknown top-level keys are preserved). (spec §7, §8, §11)
- **CLAUDE.md governs inside the session** exactly as in the terminal: no model arithmetic, declared joins only, validation before delivery, 6-file contract, follow-up = new `run_id` w/ `base_plan`, deck opt-in. (spec §3)
- **The existing one-shot inbox path** (`server/engine.py`, `web/js/engine.js`, `/api/engine*`) stays untouched — zero regression. (spec §3)
- **Windows:** use `py -3`, never `python` (broken Store alias). (MEMORY.md)
- **Test suite baseline:** the suite has **6 known pre-existing failures** from perturbed/simulated demo data — NOT regressions: `test_api::test_reset_without_backup_returns_400`, `test_datasets::test_weekly_table_info_against_real_data`, `test_datasets::test_monthly_min_max`, `test_simulate::test_reset_restores_byte_identical`, `test_simulate::test_reset_without_backup_is_noop`, `test_snapshot::test_snapshot_detects_a_changed_max`. Per-task gate = new tests pass AND exactly these 6 still fail (no NEW failures). (`.superpowers/sdd/progress.md`)
- **Commit convention:** application/doc code, NOT a `/semantic/` or `/metadata/` rule change — use `feat:`/`test:`/`docs:`, not the `rule:` convention. End commit messages with the `Co-Authored-By` trailer per environment rules. (sibling plan)
- **Git IS initialized** (branch `demo_v3`); the MEMORY.md "not initialized" note is stale.

---

### Task 1: VALIDATION SPIKE — in-session continuation after a blocking event (GO/NO-GO gate)

> **This task is the build-blocking precondition for the entire design.** It empirically proves the load-bearing assumption of §4/§7/§11: that when a blocking wait returns inside a still-running session, the session RETAINS prior-turn context AND a loaded skill (a mid-flight `superpowers:brainstorming` process) and continues the turn in-process — NOT merely "an event notifies an active session" (the Monitor tool's own contract says events "are not replies from the user" and "notify an active session"; that wording is exactly what this spike must show is sufficient for context+skill continuation). **Run this in a live foreground interactive session, NOT a subagent.** If the result is NO-GO, STOP — do not start Tasks 2–6; instead apply the §"NO-GO contingency" below and revise the spec.

**Files:**
- Create: `docs/superpowers/specs/spike-results-monitor-continuation.md` (the recorded evidence + verdict)
- Scratch (throwaway, not committed): a sentinel file under the session scratchpad. Wherever you see `<scratchpad>/spike_gate.txt` below, substitute your live session's scratchpad directory (it is named in the system prompt; do NOT use the repo tree or `/tmp`).

**Interfaces:**
- Produces: a written GO/NO-GO verdict consumed by Tasks 2–6 (build proceeds only on GO). No code interface.

- [ ] **Step 1: Establish prior-turn context AND load a skill (turn A, first half)**

Conduct Steps 1-2 within one continuous assistant message: state the sentinel, invoke `superpowers:brainstorming` and advance it through at least one clarifying-question round so it is mid-process, then (without ending the turn) arm the background wait and end the message. The external sentinel flip (Step 3) happens outside the session.
1. State a sentinel fact verbatim so it is unambiguously in context: `SPIKE-TOKEN = 4271; mid-brainstorm on throwaway feature "widget-X"; the user's last answer was "blue".`
2. Invoke `superpowers:brainstorming` on a throwaway prompt ("help me brainstorm a trivial widget-X feature") and advance it into its multi-turn process — i.e. get to the point where the skill has asked at least one clarifying question and is mid-process (this is the "loaded skill with live state" condition).
3. Create the sentinel file with initial content `wait`:

```bash
echo wait > "<scratchpad>/spike_gate.txt"
```

- [ ] **Step 2: Arm a blocking wait and END THE TURN (turn A, second half)**

Still in the same turn, arm a background blocking wait that exits ONLY when the sentinel flips, then **end the turn** (produce no further output and await re-invocation). Use Bash with `run_in_background` (the exact primitive the serve-loop will use):

```bash
until [ "$(cat '<scratchpad>/spike_gate.txt' 2>/dev/null)" = "go" ]; do sleep 1; done; echo "EVENT: gate opened"
```

This must be launched with `run_in_background: true`. Ending the turn drives the session to idle, blocked on this detached task — reproducing the serve-loop's block point. (Bash `run_in_background` contract: "keeps running across turns and re-invokes you when it exits.")

- [ ] **Step 3: Externally flip the sentinel (no assistant action)**

From a SEPARATE shell (a second terminal — NOT an assistant tool call in the same turn, or the idle→re-invoke boundary is not exercised):

```bash
echo go > "<scratchpad>/spike_gate.txt"
```

The background `until` loop exits and prints `EVENT: gate opened`; the harness re-invokes the session with that completion notification.

- [ ] **Step 4: On re-invocation, probe context + skill retention (turn B)**

When the session is re-invoked by the event, WITHOUT re-reading any file or re-invoking any skill, do exactly two things:
1. **Context probe:** state the `SPIKE-TOKEN` value, the feature name, and the user's last answer purely from memory.
2. **Skill probe:** produce the NEXT step of the in-flight `superpowers:brainstorming` process (the next clarifying question or the approaches proposal), demonstrating the skill's process is still active without re-invoking it.

- [ ] **Step 5: Record the verdict**

Write `docs/superpowers/specs/spike-results-monitor-continuation.md` capturing: the exact prompts used, whether Step 4.1 reproduced `4271`/`widget-X`/`blue` correctly, whether Step 4.2 continued brainstorming without re-invocation, and a one-word verdict.

- **GO** = BOTH probes pass (token+feature+last-answer reproduced verbatim AND brainstorming continued in-process). The §4/§7/§11 claims are proven; proceed to Task 2.
- **NO-GO** = either probe fails (context lost, or the skill had to be re-invoked / restarted).

- [ ] **Step 6: Gate decision**

- If **GO**: commit the evidence and proceed.

```bash
git add docs/superpowers/specs/spike-results-monitor-continuation.md
git commit -m "spike: prove in-session continuation retains context + loaded skill across a blocking event (GO)"
```

- If **NO-GO**: **STOP all build work.** Do not start Task 2. Apply the contingency below, revise `docs/superpowers/specs/2026-06-29-engine-as-cli-mirror-design.md` (remove the §4 diagram + §11 acceptance claims that assert in-process continuation), and re-brainstorm the brain design with the user before writing a new plan.

**NO-GO contingency (design fallback, only if Step 5 = NO-GO):** the serve-loop cannot rely on implicit in-session memory. Fall back to a **durable-state-reload-per-turn** brain: every re-invocation re-reads `active.json` (including `brainstorm_phase`) + the boot/schema state and reconstructs the conversation from the durable record, explicitly re-invoking `superpowers:brainstorming` and feeding it the recovered phase + answered-questions each turn. This is heavier and re-introduces a (bounded, state-driven) re-entry; it must be the user's call, hence STOP-and-revise rather than silently building it.

---

### Task 2: Verify §8 invariants unchanged + prove durable-field survival (regression gate)

> A verify-don't-touch task plus one NEW test that proves the additive `brainstorm_phase`/`skill_invocations` fields survive a server write. If the durable-field test fails, the recovery design needs a server change — which violates a non-negotiable — so this is a second gate: it must pass with the server UNEDITED.

**Files:**
- Verify (no edits): `server/chat.py`, `server/config.py` (`engine_chat_dir`, `assert_within_output`), `server/app.py` (`/api/chat message|get|reset-turn|new`), `web/js/chat.js`, `web/index.html` (mode toggle), `web/js/api.js` (`err.status`), `tests/test_chat.py`.
- Modify: `tests/test_chat.py` (append two tests; no production edits)

**Interfaces:**
- Consumes: `chat.post_message(text, in_reply_to=None, chosen=None) -> dict`, `chat.get_active() -> dict` (from committed `server/chat.py`).
- Produces: a recorded green baseline that Tasks 3–6 must preserve.

- [ ] **Step 1: Record the suite baseline**

Run: `py -3 -m pytest -q`
Expected: the 6 pre-existing failures listed in Global Constraints, and ONLY those 6. Record the pass count. If any OTHER test fails, stop and investigate before building.

- [ ] **Step 2: Confirm the §8 broker surface is intact (read-only)**

Confirm by reading (do not edit):
- `server/chat.py` still exposes `post_message`, `get_active`, `reset_turn`, `new_chat`, the module `_LOCK`, and `_atomic_write` with the 3-attempt `PermissionError` retry.
- `server/config.py` still exposes `engine_chat_dir()` and `assert_within_output()`.
- `web/js/api.js` still sets `err.status` on non-OK responses (the committed 409-detection path).

Record one line per item confirming presence. No code changes.

- [ ] **Step 3: Write the failing durable-field-survival test**

Append to `tests/test_chat.py`:

```python
def test_engine_written_fields_survive_user_send(repo_copy):
    """brainstorm_phase + skill_invocations are engine-written, non-rendered, and
    additive; the unchanged server broker must preserve them across a user send."""
    from server import chat
    # Engine owns the file and has written durable state + handed the turn back.
    chat._dir()
    chat._atomic_write({
        "thread_id": "chat_20260629_000000000000",
        "created_at": "2026-06-29T00:00:00",
        "status": "awaiting_user", "turn": "user", "engine_status": None,
        "run_folder": "output/run_2026-06-29_001", "view_id": "v1",
        "brainstorm_phase": "approved",
        "skill_invocations": [{"skill": "superpowers:brainstorming", "seq": 1}],
        "messages": [{"seq": 1, "role": "engine", "ts": "2026-06-29T00:00:00",
                      "kind": "question", "text": "Approve?", "options": ["Approve", "Revise"]}],
    })
    thread = chat.post_message("Approve", in_reply_to=1, chosen="Approve")
    assert thread["brainstorm_phase"] == "approved"
    assert thread["skill_invocations"] == [{"skill": "superpowers:brainstorming", "seq": 1}]
    assert thread["run_folder"] == "output/run_2026-06-29_001"
    assert thread["turn"] == "engine"        # server still flipped the turn
    assert thread["messages"][-1]["chosen"] == "Approve"
    # prove the fields survived the read->mutate->write cycle to disk, not just in-memory
    reread = chat.get_active()
    assert reread["brainstorm_phase"] == "approved"
    assert reread["skill_invocations"] == [{"skill": "superpowers:brainstorming", "seq": 1}]
```

- [ ] **Step 4: Run it — expect PASS without touching the server**

Run: `py -3 -m pytest tests/test_chat.py::test_engine_written_fields_survive_user_send -v`
Expected: PASS (the committed `post_message` mutates the loaded dict in place, preserving unknown keys).

If it FAILS: the broker drops unknown fields → the durable-field recovery design is unsound with an unchanged server. STOP and escalate (do not "fix" by editing the server — that breaks the §8 non-negotiable; the design must change instead).

- [ ] **Step 5: Write a reset-turn / new-chat preservation test**

Append to `tests/test_chat.py`:

```python
def test_durable_fields_survive_reset_turn(repo_copy):
    from server import chat
    chat._dir()
    chat._atomic_write({
        "thread_id": "chat_20260629_000001000000",
        "created_at": "2026-06-29T00:00:01",
        "status": "awaiting_engine", "turn": "engine", "engine_status": "thinking…",
        "run_folder": None, "view_id": None,
        "brainstorm_phase": "gathering", "skill_invocations": [],
        "messages": [{"seq": 1, "role": "user", "ts": "2026-06-29T00:00:01",
                      "kind": "text", "text": "weekly tremfya by indication"}],
    })
    thread = chat.reset_turn()
    assert thread["turn"] == "user"
    assert thread["engine_status"] is None
    assert thread["brainstorm_phase"] == "gathering"   # reset must not drop it
```

- [ ] **Step 6: Run both new tests + full suite**

Run: `py -3 -m pytest tests/test_chat.py -v` then `py -3 -m pytest -q`
Expected: all `test_chat.py` tests PASS; full suite = previous pass count + 2, still exactly the 6 pre-existing failures.

- [ ] **Step 7: Commit**

```bash
git add tests/test_chat.py
git commit -m "test: prove server preserves engine-written durable fields (brainstorm_phase, skill_invocations)"
```

---

### Task 3: Rewrite `ENGINE_CHAT.md` — script → transport contract + delegation + overrides

> The behavioral heart of the change. `ENGINE_CHAT.md` flips from a per-tick script to: (5a) transport/rendering contract, (5b) delegation, (6) brainstorming overrides + the deterministic approval gate-check + retained routing, and (7) compaction/crash recovery driven by the durable `brainstorm_phase`. It MUST NOT prescribe canned phrasing, but MUST retain the deterministic routing rules. Since it is a markdown contract (no runtime code), it is verified by a doc-contract pytest that asserts the required anchors are present and the old per-tick `/loop` script framing is gone.

**Files:**
- Modify (full replace): `ENGINE_CHAT.md`
- Modify: `tests/test_chat.py` (append the doc-contract test)

**Interfaces:**
- Consumes: the durable-field guarantee from Task 2 (server preserves `brainstorm_phase`/`skill_invocations`).
- Produces: the engine-side contract every serve-loop turn (Task 4) honors; defines the five `brainstorm_phase` values `gathering|approaches_presented|awaiting_approval|approved|converged` and the `skill_invocations` marker shape `{skill, seq}`.

- [ ] **Step 1: Write the failing doc-contract test**

Append to `tests/test_chat.py`:

```python
def test_engine_chat_md_is_transport_contract_not_script():
    import re
    text = (REPO / "ENGINE_CHAT.md").read_text(encoding="utf-8")
    # (5a) transport/rendering contract
    for kind in ["text", "question", "result", "deck_offer", "deck_ready", "error"]:
        assert kind in text, f"missing message kind: {kind}"
    assert "engine_status" in text and "thinking" in text          # proof-of-pickup
    assert "turn=user" in text or 'turn="user"' in text
    # durable phase marker + all five values
    assert "brainstorm_phase" in text
    for phase in ["gathering", "approaches_presented", "awaiting_approval", "approved", "converged"]:
        assert phase in text, f"missing phase value: {phase}"
    assert "skill_invocations" in text                              # §11 provenance marker
    # (5b) delegation, not a script
    assert "superpowers:brainstorming" in text
    assert "behave" in text.lower() and "terminal" in text.lower()
    # (6) approval gate-check + Approve/Revise (literal option labels — case-sensitive, as a paired gate option)
    assert re.search(r"Approve.{0,40}Revise|Revise.{0,40}Approve", text), "Approve/Revise gate options not found together in ENGINE_CHAT.md"
    # (6) retained deterministic routing (case-insensitive — headings may be Title-cased)
    low = text.lower()
    for route in ["follow-up", "deck-revise", "base_plan"]:
        assert route in low, f"missing routing rule: {route}"
    # (7) recovery
    assert "compaction" in low
    assert "analysis_plan.md" in text
    # old per-tick script framing is GONE
    assert "Each tick" not in text
    assert "do nothing this tick" not in text
```

- [ ] **Step 2: Run it — expect FAIL**

Run: `py -3 -m pytest tests/test_chat.py::test_engine_chat_md_is_transport_contract_not_script -v`
Expected: FAIL (current `ENGINE_CHAT.md` is the per-tick script — `Each tick` present, `brainstorm_phase`/`skill_invocations`/the five phases absent).

- [ ] **Step 3: Replace `ENGINE_CHAT.md` with the transport contract**

Replace the ENTIRE contents of `ENGINE_CHAT.md` with:

```markdown
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
```

- [ ] **Step 4: Run the doc-contract test — expect PASS**

Run: `py -3 -m pytest tests/test_chat.py::test_engine_chat_md_is_transport_contract_not_script -v`
Expected: PASS.

- [ ] **Step 5: Full suite check**

Run: `py -3 -m pytest -q`
Expected: prior pass count + 1, still exactly the 6 pre-existing failures.

- [ ] **Step 6: Commit**

```bash
git add ENGINE_CHAT.md tests/test_chat.py
git commit -m "feat: rewrite ENGINE_CHAT.md from per-tick script to CLI-mirror transport contract"
```

---

### Task 4: `/serve-engine` launch path + tested blocking-wait primitive

> The single launch path the user runs once: boot gate + schema gate, then the persistent foreground serve-loop. The loop's one piece of real code — the blocking wait on `active.json` for `turn==engine` — is extracted to a tiny, TDD-tested script so the command doc wraps a reliable primitive instead of an ad-hoc shell one-liner. The command itself is a markdown prompt (Claude Code slash command); the server never spawns it (spec §9 out-of-scope).

**Files:**
- Create: `scripts/wait_engine_turn.py` (the blocking-wait primitive)
- Create: `.claude/commands/serve-engine.md` (the launch prompt / slash command)
- Test: `tests/test_chat.py` (append wait-primitive tests)

**Interfaces:**
- Consumes: `config.engine_chat_dir()` (existing).
- Produces: `scripts/wait_engine_turn.py` — a CLI that polls `engine_chat/active.json` and **exits 0 and prints `ENGINE_TURN`** as soon as `turn == "engine"`; exits 2 on a `--timeout` expiry printing `TIMEOUT`. The serve-loop runs it via Bash `run_in_background`; its exit re-invokes the session.

- [ ] **Step 1: ADD the required imports, then write the failing primitive tests**

At the top of `tests/test_chat.py` (after the `from pathlib import Path` line) add these three lines — the committed file imports none of them (`os.environ`, `subprocess.run`, and `sys.executable` are all used below):

```python
import os
import subprocess
import sys
```

Then append to `tests/test_chat.py`:

```python
def _run_wait(repo_copy, extra_args):
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "wait_engine_turn.py"), *extra_args],
        capture_output=True, text=True,
        env={**os.environ, "QTS_ROOT": str(repo_copy)},
    )


def test_wait_engine_turn_returns_when_engine(repo_copy):
    from server import chat
    chat._dir()
    chat._atomic_write({
        "thread_id": "chat_20260629_010101000000", "created_at": "2026-06-29T01:01:01",
        "status": "awaiting_engine", "turn": "engine", "engine_status": None,
        "run_folder": None, "view_id": None, "brainstorm_phase": "gathering",
        "skill_invocations": [], "messages": [],
    })
    r = _run_wait(repo_copy, ["--interval", "0.1", "--timeout", "5"])
    assert r.returncode == 0
    assert "ENGINE_TURN" in r.stdout


def test_wait_engine_turn_times_out_when_user(repo_copy):
    from server import chat
    chat._dir()
    chat._atomic_write({
        "thread_id": "chat_20260629_020202000000", "created_at": "2026-06-29T02:02:02",
        "status": "awaiting_user", "turn": "user", "engine_status": None,
        "run_folder": None, "view_id": None, "brainstorm_phase": "gathering",
        "skill_invocations": [], "messages": [],
    })
    r = _run_wait(repo_copy, ["--interval", "0.1", "--timeout", "0.5"])
    assert r.returncode == 2
    assert "TIMEOUT" in r.stdout


def test_wait_engine_turn_handles_missing_file(repo_copy):
    # no active.json at all -> behaves like turn=user (keep waiting, then timeout)
    r = _run_wait(repo_copy, ["--interval", "0.1", "--timeout", "0.5"])
    assert r.returncode == 2
    assert "TIMEOUT" in r.stdout
```

- [ ] **Step 2: Run them — expect FAIL**

Run: `py -3 -m pytest tests/test_chat.py -k wait_engine_turn -v`
Expected: FAIL (`scripts/wait_engine_turn.py` does not exist).

- [ ] **Step 3: Write the primitive**

Create `scripts/wait_engine_turn.py`:

```python
"""Blocking wait used by the /serve-engine serve-loop. Polls engine_chat/active.json
and exits 0 (prints ENGINE_TURN) the instant turn == "engine"; exits 2 (prints
TIMEOUT) on --timeout expiry. Run via Bash run_in_background: its exit re-invokes
the live session, which then handles the pending engine turn in-process.

Usage: py -3 scripts/wait_engine_turn.py [--interval 1.0] [--timeout 86400]
Reads QTS_ROOT like the server, so it points at the same active.json."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import config  # noqa: E402


def _turn() -> str | None:
    p = config.engine_chat_dir() / "active.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("turn")
    except (json.JSONDecodeError, OSError):
        return None  # mid-write or transient read error -> keep waiting


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--timeout", type=float, default=86400.0)
    args = ap.parse_args()
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        if _turn() == "engine":
            print("ENGINE_TURN", flush=True)
            return 0
        time.sleep(args.interval)
    print("TIMEOUT", flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the primitive tests — expect PASS**

Run: `py -3 -m pytest tests/test_chat.py -k wait_engine_turn -v`
Expected: 3 PASS.

- [ ] **Step 5: Write the `/serve-engine` launch command**

The `.claude/commands/` directory does not exist yet — the Write tool creates parent dirs automatically, but if writing by other means, first `mkdir -p .claude/commands`. Create `.claude/commands/serve-engine.md`:

```markdown
---
description: Launch the always-on engine session that mirrors the terminal CLI into the dashboard Brainstorm chat.
---

You are the always-on **engine brain** for the dashboard "Brainstorm chat". You run
ONE continuous foreground serve-loop in THIS session. Do not use the Agent SDK,
`claude -p`, or a context-resetting `/loop` re-entry. Read `ENGINE_CHAT.md` once now
— it is your transport/rendering contract, delegation, brainstorming overrides, the
approval gate-check, and the compaction/crash recovery rules.

## 1. Boot once
Run the CLAUDE.md §0 boot sequence + schema gate exactly once: read MEMORY.md;
`git status -- semantic/ metadata/`; `py -3 scripts/validate_schema.py`; load all of
/metadata/ and /semantic/; check stale auto-saved rules. If the schema gate reports
drift, do NOT serve analyses — surface it and stop.

## 2. Recovery on (re)launch
Read `engine_chat/active.json` if it exists (do NOT create a new thread — the
in-flight conversation lives there). If a thread exists, recover per ENGINE_CHAT.md §7
from the durable `brainstorm_phase` (tail = corroboration only) and apply the
crash-after-run-folder guard before re-running anything. If a dead prior session left
`turn=engine` with a frozen `engine_status`, treat the pending user message as the
turn to drive now (or the operator clicks Reset turn in the UI).

## 3. The serve-loop (block → continue in-process → re-block)
Repeat for the lifetime of this session:
1. **Block.** Launch the wait primitive via Bash with `run_in_background: true`:
   `py -3 scripts/wait_engine_turn.py --interval 1 --timeout 3600`
   Then END YOUR TURN and await re-invocation. (Its exit re-invokes you. A `TIMEOUT`
   exit is benign — simply re-arm it. An `ENGINE_TURN` exit means a user turn is
   pending.)
2. **Continue IN-PROCESS.** On re-invocation, do NOT re-read context from scratch and
   do NOT restart any loaded skill. Set `engine_status` promptly (proof-of-pickup),
   then handle the pending turn exactly per ENGINE_CHAT.md §5a/§5b/§6: a new
   analytical request → invoke `superpowers:brainstorming` (append the
   `skill_invocations` marker); a follow-up / deck request → per the retained routing.
   Write `brainstorm_phase` every engine turn. End the turn with `turn=user`.
3. **Re-block.** Go back to step 1.

Never act when `turn=user`. Never re-emit an existing message. `turn` stays `engine`
for the FULL duration of a turn (including code-gen / execute / validate / deck
build); flip to `user` only at the single terminal append.
```

- [ ] **Step 6: Smoke-test the primitive (MANUAL / operator-only — subagents SKIP this step; it requires a live dashboard + claude session and cannot run in an isolated task)**

Run the dashboard (`py -3 run_dashboard.py`), open Brainstorm chat, send a message (flips `turn=engine`), then in a shell run `py -3 scripts/wait_engine_turn.py --timeout 5` and confirm it prints `ENGINE_TURN` and exits 0 immediately.

- [ ] **Step 7: Full suite + commit**

Run: `py -3 -m pytest -q` (prior + 3, still only the 6 pre-existing failures).

```bash
git add scripts/wait_engine_turn.py .claude/commands/serve-engine.md tests/test_chat.py
git commit -m "feat: /serve-engine launch path + tested blocking-wait serve-loop primitive"
```

---

### Task 5: `chat.js` stall-hint copy edit (the only transport change)

> The one permitted change to committed transport: the stall hint at `web/js/chat.js:50` says "is the /loop session running?", inaccurate under the always-on model. No logic change. No JS test harness exists — verified manually + by grep.

**Files:**
- Modify: `web/js/chat.js:50`

**Interfaces:** none (string-only edit).

- [ ] **Step 1: Make the edit**

In `web/js/chat.js`, change the stall hint string at line 50 from
`waiting for the engine — is the /loop session running?` to
`waiting for the engine — is the engine session running?`.

- [ ] **Step 2: Verify no other `/loop` user-facing copy remains in chat.js**

Run: `py -3 -c "import pathlib,sys; t=pathlib.Path('web/js/chat.js').read_text(encoding='utf-8'); sys.exit(0 if '/loop session running' not in t else 1)"`
Expected: exit 0 (the old string is gone).

Run this in the Bash tool, not PowerShell (the nested single-quotes are Bash quoting). In PowerShell the quoting must be reworked or run as a `.py` file instead.

- [ ] **Step 3: Syntax check**

Run: `node --check web/js/chat.js`
Expected: no output (valid).

- [ ] **Step 4: Manual confirm (optional)**

With the dashboard running and NO engine session, send a chat message, wait ~30s → the stall bubble now reads "is the engine session running?" with a Reset turn button.

- [ ] **Step 5: Commit**

```bash
git add web/js/chat.js
git commit -m "docs: chat stall hint reflects always-on engine session (not /loop)"
```

---

### Task 6: MEMORY.md update, full-branch review, manual E2E sign-off

> Records the new brain model so a fresh session resumes aware of it, runs the final whole-branch verification, and defines the manual E2E acceptance (which needs a live `/serve-engine` session + running dashboard — deferred to the operator).

**Files:**
- Modify: `MEMORY.md`
- Modify: `.superpowers/sdd/progress.md` (append this plan's ledger)

**Interfaces:** none.

- [ ] **Step 1: Update MEMORY.md**

Append a subsection under the dashboard area of `MEMORY.md` capturing, in plain prose:
- The "Brainstorm chat" brain is now ONE always-on continuous session launched via `/serve-engine` (`.claude/commands/serve-engine.md`), running a single persistent foreground serve-loop (block on `scripts/wait_engine_turn.py` for `turn==engine` → continue in-process → re-block). It REPLACES the committed `/loop check engine_chat` fresh-context brain.
- Why: the old per-tick `/loop` was fresh-context each tick, so `superpowers:brainstorming`'s multi-turn process could not persist. The serve-loop carries context + a loaded skill across turns (proven by the Task 1 spike — see `docs/superpowers/specs/spike-results-monitor-continuation.md`).
- `ENGINE_CHAT.md` is now a transport/rendering contract + delegation + §6 overrides + retained routing + §7 recovery — NOT a script.
- Durable non-rendered fields on `active.json`: `brainstorm_phase` (`gathering|approaches_presented|awaiting_approval|approved|converged`, authoritative for the approval gate + compaction recovery) and `skill_invocations` (`{skill,seq}`, the §11 proof brainstorming fired). Server preserves them unchanged (mutates the loaded dict in place).
- Server / transport / UI / tests UNCHANGED except one copy-edit (`chat.js:50` "/loop" → "engine"). The one-shot inbox path remains untouched.
- Known non-blocking follow-up: `server/views.py run_view_core` still lacks a `holdout_segments`/by-region builder branch; a chat-built non-line deck re-run from the dashboard mis-renders.

- [ ] **Step 2: Append the SDD ledger**

Append to `.superpowers/sdd/progress.md` a new block for this plan: plan path, branch, base commit, and one line per task with its commit + review note (mirror the existing format).

- [ ] **Step 3: Full regression run**

Run: `py -3 -m pytest -q`
Expected: all chat + primitive + doc-contract tests PASS; the prior pass count recorded in Task 2 Step 1 PLUS the 6 new tests added across Tasks 2-4 all PASS, with EXACTLY the 6 pre-existing failures still failing and no NEW failures.

- [ ] **Step 4: Verify the §11 acceptance is automatable**

Confirm the provenance check is real: with a thread where the engine handled a new question, `active.json` carries a `skill_invocations` entry for `superpowers:brainstorming` on that turn — checkable via:
`py -3 -c "import json; d=json.load(open('engine_chat/active.json',encoding='utf-8')); print([s for s in d.get('skill_invocations',[]) if s['skill']=='superpowers:brainstorming'])"`
(This is exercised during Step 5 E2E; document the command in MEMORY.)

Run this in the Bash tool, not PowerShell (the nested single-quotes are Bash quoting). In PowerShell the quoting must be reworked or run as a `.py` file instead.

Fallback per spec §11 if the marker is absent: grep the Claude Code session JSONL under `~/.claude/projects/C--Users-RounakSuranshe-Documents-Projects-Abbvie-MRD-Automation/<session>.jsonl` for a tool-use entry naming `superpowers:brainstorming`. The marker is preferred; the grep is the backstop.

- [ ] **Step 5: Manual E2E acceptance (operator — needs live session)**

If the Task 4 Step 6 smoke test was skipped (subagent build), run it before starting E2E — the primitive must work in real use.

With `py -3 run_dashboard.py` running and a live `claude` session having run `/serve-engine`, from the browser Brainstorm chat verify the spec §11 acceptance:
1. Send a NEW analytical question → confirm `superpowers:brainstorming` actually fired via the `skill_invocations` marker on the handling turn (Step 4 command) — NOT just the Q&A→plan→approve shape.
2. The engine asks clarifying `question`(s) with chips; answering advances phases; a later turn references an earlier answer without re-asking (context-across-turns).
3. The design is presented as a `question` with Approve/Revise; sending "Approve" (and ONLY then) runs the CLAUDE.md workflow → 6-file contract + `views.yaml` entry + a `result` + `deck_offer` — exactly like the terminal.
4. A typed revision (not "Approve") is treated as Revise — `brainstorm_phase` returns to `awaiting_approval`, no run.
5. Follow-up ("break CD by region") → new `run_id` w/ `base_plan`; deck-revise → same run folder; bare deck on a deckless run → builds on the current run.
6. Switch to Quick ask → the one-shot inbox still queues and shows a card (zero regression).
7. Kill the engine session mid-`turn=engine`; wait ~30s → stall hint "is the engine session running?" + Reset turn; relaunch `/serve-engine` → it re-arms on the EXISTING `active.json`, recovers `brainstorm_phase`, and continues without re-asking answered questions or skipping the gate.

- [ ] **Step 6: Final commit**

```bash
git add MEMORY.md .superpowers/sdd/progress.md
git commit -m "docs: record CLI-mirror engine brain in MEMORY + SDD ledger"
```

---

## Self-Review

**Spec coverage** (each §, mapped to a task):
- §3 no-SDK/dumb-broker/transport-unchanged/CLAUDE.md-governs/inbox-untouched → Global Constraints + Task 2 (verify) + Task 5 (only allowed UI change).
- §4 persistent serve-loop, in-process continuation → Task 1 (proves it) + Task 4 (builds it).
- §5a transport/rendering contract, proof-of-pickup, turn-stays-engine, durable fields → Task 3 (ENGINE_CHAT.md §5a) + doc-contract test.
- §5b delegation not script → Task 3 (§5b) + doc-contract test (`behave`/`terminal`/no `Each tick`).
- §6 brainstorming→thread mapping, approval gate-check, retained routing, ambiguity guard, suppress visual companion, analysis_plan.md/CLAUDE.md-workflow overrides → Task 3 (§6) + doc-contract test (Approve/Revise, follow-up, deck-revise, base_plan).
- §7 launch path, recovery, crash-window, post-compaction schema re-gate → Task 4 (`/serve-engine` + recovery steps) + Task 3 (§7 written into the contract).
- §8 unchanged inventory + durable fields additive + chat.js:50 copy edit → Task 2 (verify + field-survival test) + Task 5 (copy edit).
- §8.5 liveness/death/restart, engine_status discipline → Task 3 (engine_status stage updates) + Task 4 (relaunch recovery) + Task 5 (stall hint copy).
- §10 risks (compaction, run-ahead, scripted re-entry) → mitigated by Task 1 gate + Task 3 gate-check + durable phase.
- §11 acceptance: skill_invocations provenance marker → Task 3 (defines it) + Task 6 Step 4 (automatable check) + Task 1 (continuation proof) + Task 6 Step 5 (E2E).

**Placeholder scan:** every code/doc step contains full content; the only deliberately operator-deferred items are Task 1 (live session) and Task 6 Step 5 (live E2E), both with concrete checkable steps. No TBD/TODO.

**Type consistency:** `brainstorm_phase` values, the `skill_invocations` `{skill, seq}` shape, `wait_engine_turn.py`'s `ENGINE_TURN`/`TIMEOUT`/exit-codes (0/2), and `config.engine_chat_dir()` are used identically across Tasks 2, 3, 4, 6.

**Gate notes:** Task 1 (spike) and Task 2 Step 4 (durable-field survival) are both hard gates — a failure of either invalidates a non-negotiable and requires STOP-and-revise rather than working around it.

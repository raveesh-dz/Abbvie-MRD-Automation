# Interactive "Ask the Engine" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bidirectional chat "Ask the Engine" mode where the browser converses with the live Claude Code `/loop` session — brainstorm → clarify → run the CLAUDE.md workflow → deliver → offer/download a deck → revise — alongside the untouched one-shot inbox.

**Architecture:** A single active thread file `engine_chat/active.json` is the message bus. The FastAPI server is a dumb file broker (no LLM): it appends user messages and flips `turn=engine`; a live Claude session polls, acts, appends engine messages, flips `turn=user`. The browser polls `GET /api/chat` every 3s while `turn=engine`. All server writes go through one module-level lock + atomic replace.

**Tech Stack:** Python 3.14 (`py -3`), FastAPI + uvicorn (sync `def` routes on a threadpool), pytest + `fastapi.testclient.TestClient`, vanilla ES-module JS (no build step, no JS test framework).

**Spec:** `docs/superpowers/specs/2026-06-29-interactive-ask-the-engine-design.md`

## Global Constraints

- Server NEVER runs an LLM or does analysis — it only reads/writes `active.json` and serves existing artifacts. (spec §2)
- Existing inbox path (`server/engine.py`, `web/js/engine.js`, `/api/engine*`) MUST stay byte-for-byte untouched — zero regression. (spec §2)
- All paths derive from `server/config.py` helpers off `QTS_ROOT`; never hardcode the repo root. (config.py:9-10)
- Every server write to `active.json` goes through the `chat.py` helper holding the module-level `threading.Lock` across read → 409-check → append → atomic `os.replace`. (spec §7, §9)
- `thread_id` format is `chat_<YYYYMMDD_HHMMSS%f>` (server-generated via `strftime`; no untrusted thread_id input path exists). (spec §4, §9)
- Run on Windows: use `py -3` not `python`; `os.replace` needs bounded `PermissionError` retry. (MEMORY.md, spec §9)
- Frontend has no automated test harness in this repo — JS tasks are verified manually against the running app, matching the existing `web/` (which ships no tests).
- Commit messages: this is application code, not a `/semantic/` or `/metadata/` rule change, so the `rule:` commit convention does NOT apply; use `feat:` / `test:` / `docs:`.
- Git IS initialized in this checkout (branch demo_v3); the MEMORY.md note about git being uninitialized is stale — run the boot `git status` and the per-task commit steps normally.

---

### Task 1: `config.engine_chat_dir()` + `ENGINE_CHAT.md` protocol doc

**Files:**
- Modify: `server/config.py` (add one helper after `engine_inbox_dir`, config.py:45-46)
- Create: `ENGINE_CHAT.md` (repo root, sibling to `ENGINE_INBOX.md`)
- Test: `tests/test_chat.py` (new file — first test only)

**Interfaces:**
- Produces: `config.engine_chat_dir() -> Path` returning `get_root() / "engine_chat"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_chat.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]


def _client(repo_copy):
    # chat endpoints need no seeded views; lifespan still inits the snapshot.
    from server.app import create_app
    return TestClient(create_app())


def test_engine_chat_dir(repo_copy):
    from server import config
    assert config.engine_chat_dir() == repo_copy / "engine_chat"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_chat.py::test_engine_chat_dir -v`
Expected: FAIL with `AttributeError: module 'server.config' has no attribute 'engine_chat_dir'`

- [ ] **Step 3: Add the helper**

In `server/config.py`, after `engine_inbox_dir` (config.py:45-46), append:

```python


def engine_chat_dir() -> Path:
    return get_root() / "engine_chat"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_chat.py::test_engine_chat_dir -v`
Expected: PASS

- [ ] **Step 5: Write `ENGINE_CHAT.md`**

Create `ENGINE_CHAT.md` at the repo root with this content (it is the loop-side contract; transcribe spec §5/§6 faithfully):

```markdown
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
   `{deck_url:"/api/views/<view_id>/deck"}`. turn=user.
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
```

- [ ] **Step 6: Commit**

```bash
git add server/config.py ENGINE_CHAT.md tests/test_chat.py
git commit -m "feat: engine_chat_dir helper + ENGINE_CHAT loop protocol doc"
```

---

### Task 2: `server/chat.py` — locked atomic thread broker

**Files:**
- Create: `server/chat.py`
- Test: `tests/test_chat.py` (extend — these tests drive the module directly via the API in Task 3; here we test the module functions in isolation)

**Interfaces:**
- Consumes: `config.engine_chat_dir()` (Task 1).
- Produces:
  - `chat.Conflict` (Exception) — engine holds the turn / concurrent external write.
  - `chat.get_active() -> dict` — the active thread, or `{"thread_id": None}`.
  - `chat.post_message(text: str, in_reply_to=None, chosen=None) -> dict` — append a user message, flip `turn=engine`; raises `ValueError` on empty text, `Conflict` if `turn==engine`.
  - `chat.reset_turn() -> dict` — flip `turn=user`, clear `engine_status`; `{"thread_id": None}` if no thread.
  - `chat.new_chat(force: bool=False) -> dict` — archive (if non-empty) + clear; raises `Conflict` if `turn==engine` and not `force`; returns `{"thread_id": None}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_chat.py`:

```python
def test_get_empty_returns_null(repo_copy):
    from server import chat
    assert chat.get_active() == {"thread_id": None}


def test_reset_turn_on_empty_returns_null(repo_copy):
    from server import chat
    assert chat.reset_turn() == {"thread_id": None}


def test_post_creates_thread_and_takes_engine_turn(repo_copy):
    from server import chat
    t = chat.post_message("weekly tremfya by indication")
    assert t["turn"] == "engine" and t["status"] == "awaiting_engine"
    assert t["messages"][0]["seq"] == 1
    assert t["messages"][0]["text"] == "weekly tremfya by indication"
    assert t["thread_id"].startswith("chat_")
    assert (repo_copy / "engine_chat" / "active.json").exists()


def test_post_empty_text_raises(repo_copy):
    import pytest
    from server import chat
    with pytest.raises(ValueError):
        chat.post_message("   ")


def test_post_while_engine_turn_conflicts(repo_copy):
    import pytest
    from server import chat
    chat.post_message("q1")
    with pytest.raises(chat.Conflict):
        chat.post_message("q2")


def test_reset_turn_then_second_message_increments_seq(repo_copy):
    from server import chat
    chat.post_message("q1")
    r = chat.reset_turn()
    assert r["turn"] == "user" and r["engine_status"] is None
    assert r["status"] == "awaiting_user"
    t = chat.post_message("q2", in_reply_to=1, chosen="q2")
    assert [m["seq"] for m in t["messages"]] == [1, 2]
    assert t["messages"][-1]["in_reply_to"] == 1
    assert t["messages"][-1]["chosen"] == "q2"


def test_new_archives_nonempty_and_clears(repo_copy):
    import pytest
    from server import chat
    t = chat.post_message("q1")
    tid = t["thread_id"]
    with pytest.raises(chat.Conflict):
        chat.new_chat()                       # engine turn, no force
    assert chat.new_chat(force=True) == {"thread_id": None}
    assert chat.get_active() == {"thread_id": None}
    assert (repo_copy / "engine_chat" / "archive" / f"{tid}.json").exists()


def test_post_cross_process_write_conflicts(repo_copy, monkeypatch):
    # Drive the detect-and-reject branch: a second _read_raw (the post-lock
    # re-read) returns different bytes than the first, as if the loop wrote mid-hold.
    import pytest
    from server import chat
    real = chat._read_raw
    calls = {"n": 0}

    def racy():
        calls["n"] += 1
        return '{"thread_id":"chat_x","turn":"user","messages":[]}' if calls["n"] == 2 else real()

    monkeypatch.setattr(chat, "_read_raw", racy)
    with pytest.raises(chat.Conflict):
        chat.post_message("q1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_chat.py -v`
Expected: the 6 new tests FAIL with `ModuleNotFoundError: No module named 'server.chat'`

- [ ] **Step 3: Implement `server/chat.py`**

```python
"""Interactive chat thread broker. The dashboard (via the server) and a live
Claude Code /loop session both read/write a single active thread file; the server
only brokers those writes and never runs an LLM. See ENGINE_CHAT.md for the
loop-side protocol. A module-level lock + atomic replace serialize all server
writes; `turn` is the advisory mutex between the server and the loop process."""
import json
import os
import threading
import time
from datetime import datetime

from . import config

_LOCK = threading.Lock()          # serializes the read -> check -> append -> replace RMW


class Conflict(Exception):
    """The engine holds the turn, or an external (loop) write raced us -> HTTP 409."""


def _dir():
    d = config.engine_chat_dir()
    d.mkdir(exist_ok=True)
    return d


def _active_path():
    return _dir() / "active.json"


def _archive_dir():
    d = _dir() / "archive"
    d.mkdir(exist_ok=True)
    return d


def _read_raw():
    p = _active_path()
    return p.read_text(encoding="utf-8") if p.exists() else None


def _atomic_write(thread: dict) -> None:
    """Serialize `thread` to active.json atomically. Bounded retry on Windows
    PermissionError (a reader/AV momentarily holding the destination)."""
    p = _active_path()
    tmp = p.with_name("active.json.tmp")
    tmp.write_text(json.dumps(thread, indent=2), encoding="utf-8")
    for attempt in range(3):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(0.05 * (attempt + 1))


def _new_thread() -> dict:
    now = datetime.now()
    return {"thread_id": f"chat_{now.strftime('%Y%m%d_%H%M%S%f')}",
            "created_at": now.isoformat(timespec="seconds"),
            "status": "awaiting_user", "turn": "user", "engine_status": None,
            "run_folder": None, "view_id": None, "messages": []}


def get_active() -> dict:
    raw = _read_raw()
    return json.loads(raw) if raw else {"thread_id": None}


def post_message(text: str, in_reply_to=None, chosen=None) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("text is required")
    with _LOCK:
        raw = _read_raw()
        thread = json.loads(raw) if raw else _new_thread()
        if thread["messages"] and thread["turn"] == "engine":
            raise Conflict()
        msg = {"seq": len(thread["messages"]) + 1, "role": "user",
               "ts": datetime.now().isoformat(timespec="seconds"),
               "kind": "text", "text": text}
        if in_reply_to is not None:
            msg["in_reply_to"] = int(in_reply_to)
        if chosen is not None:
            msg["chosen"] = chosen
        thread["messages"].append(msg)
        thread["turn"] = "engine"
        thread["status"] = "awaiting_engine"
        thread["engine_status"] = None
        # cross-process detect-and-reject: if the loop wrote during our lock hold,
        # the on-disk bytes changed since our read — abort rather than clobber.
        if _read_raw() != raw:
            raise Conflict()
        # spec §7: never write an append whose computed seq duplicates an existing one.
        assert msg["seq"] not in {m["seq"] for m in thread["messages"][:-1]}
        _atomic_write(thread)
        return thread


def reset_turn() -> dict:
    with _LOCK:
        raw = _read_raw()
        if not raw:
            return {"thread_id": None}
        thread = json.loads(raw)
        thread["turn"] = "user"
        thread["status"] = "awaiting_user"
        thread["engine_status"] = None
        _atomic_write(thread)
        return thread


def new_chat(force: bool = False) -> dict:
    with _LOCK:
        raw = _read_raw()
        if not raw:
            return {"thread_id": None}
        thread = json.loads(raw)
        if thread["turn"] == "engine" and not force:
            raise Conflict()
        if thread["messages"]:
            (_archive_dir() / f"{thread['thread_id']}.json").write_text(
                json.dumps(thread, indent=2), encoding="utf-8")
        _active_path().unlink(missing_ok=True)
        return {"thread_id": None}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_chat.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add server/chat.py tests/test_chat.py
git commit -m "feat: chat.py locked atomic thread broker"
```

---

### Task 3: `/api/chat*` routes

**Files:**
- Modify: `server/app.py` (import `chat`; add 4 routes near the `/api/engine*` block, app.py:174-190)
- Test: `tests/test_chat.py` (extend with API-level tests)

**Interfaces:**
- Consumes: `chat.post_message/get_active/reset_turn/new_chat`, `chat.Conflict` (Task 2).
- Produces: `POST /api/chat/message`, `GET /api/chat`, `POST /api/chat/reset-turn`, `POST /api/chat/new`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_chat.py`:

```python
def test_api_post_and_get(repo_copy):
    with _client(repo_copy) as c:
        t = c.post("/api/chat/message", json={"text": "weekly tremfya by indication"}).json()
        assert t["turn"] == "engine"
        assert c.get("/api/chat").json()["messages"][0]["text"] == "weekly tremfya by indication"


def test_api_empty_text_400(repo_copy):
    with _client(repo_copy) as c:
        assert c.post("/api/chat/message", json={"text": "  "}).status_code == 400


def test_api_engine_turn_409(repo_copy):
    with _client(repo_copy) as c:
        c.post("/api/chat/message", json={"text": "q1"})
        assert c.post("/api/chat/message", json={"text": "q2"}).status_code == 409


def test_api_reset_turn(repo_copy):
    with _client(repo_copy) as c:
        c.post("/api/chat/message", json={"text": "q1"})
        t = c.post("/api/chat/reset-turn").json()
        assert t["turn"] == "user"
        assert c.post("/api/chat/message", json={"text": "q2"}).status_code == 200


def test_api_new_force_and_guard(repo_copy):
    with _client(repo_copy) as c:
        c.post("/api/chat/message", json={"text": "q1"})
        assert c.post("/api/chat/new").status_code == 409
        assert c.post("/api/chat/new", json={"force": True}).json() == {"thread_id": None}
        assert c.get("/api/chat").json() == {"thread_id": None}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_chat.py -k api -v`
Expected: the new API tests FAIL because no `/api/chat` route exists yet (the StaticFiles mount returns 404/405). The asserted 200/400/409 codes only appear after Step 3 adds the routes; the Step-4 assertions are the real gate.

- [ ] **Step 3: Add the routes**

In `server/app.py`, add `chat` to the existing import (app.py:10) — exact replace:

old_string:
```python
from . import config, datasets, engine, jobs, pipeline, runner, simulate, snapshot, views
```
new_string:
```python
from . import config, datasets, engine, jobs, pipeline, runner, simulate, snapshot, views, chat
```

Then, immediately after the `api_engine_get` route (app.py:185-190), add:

```python
    @app.post("/api/chat/message")
    def api_chat_message(body: dict | None = Body(None)):
        try:
            return chat.post_message((body or {}).get("text"),
                                     (body or {}).get("in_reply_to"),
                                     (body or {}).get("chosen"))
        except ValueError:
            raise HTTPException(400, "text is required")
        except chat.Conflict:
            raise HTTPException(409, "engine is mid-turn")

    @app.get("/api/chat")
    def api_chat_get():
        return chat.get_active()

    @app.post("/api/chat/reset-turn")
    def api_chat_reset():
        return chat.reset_turn()

    @app.post("/api/chat/new")
    def api_chat_new(body: dict | None = Body(None)):
        try:
            return chat.new_chat(bool((body or {}).get("force")))
        except chat.Conflict:
            raise HTTPException(409, "engine is mid-turn; pass force to discard")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_chat.py -v`
Expected: all PASS

- [ ] **Step 5: Verify no inbox regression**

Run: `py -3 -m pytest tests/test_engine.py tests/test_api.py -v`
Expected: all PASS (engine path untouched)

- [ ] **Step 6: Commit**

```bash
git add server/app.py tests/test_chat.py
git commit -m "feat: /api/chat message|get|reset-turn|new routes"
```

---

### Task 4: Path-containment hardening for `/result` + `/deck`

**Files:**
- Modify: `server/config.py` (add `assert_within_output`)
- Modify: `server/app.py` (`api_result` app.py:89-121, `api_deck` app.py:137-145)
- Test: `tests/test_chat.py` (extend)

**Interfaces:**
- Produces: `config.assert_within_output(folder: str) -> Path` — resolve `get_root()/folder`, assert it is the output root or under it; raise `ValueError` on escape.

**Why:** `view["folder"]` comes from `views.yaml` and is joined into a filesystem path with no containment check today (app.py:94, app.py:142). The chat path lets the loop register views; harden the read side. (spec §9)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_chat.py`:

```python
def test_assert_within_output(repo_copy):
    import pytest
    from server import config
    assert config.assert_within_output("output/run_2026-06-08_001").name == "run_2026-06-08_001"
    with pytest.raises(ValueError):
        config.assert_within_output("../../Windows/System32")
    with pytest.raises(ValueError):
        config.assert_within_output("output/../../etc")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_chat.py::test_assert_within_output -v`
Expected: FAIL with `AttributeError: ... 'assert_within_output'`

- [ ] **Step 3: Add the helper**

In `server/config.py`, after `output_dir` (config.py:21-22), add:

```python


def assert_within_output(folder: str) -> Path:
    """Resolve `folder` (relative to the repo root) and assert it is the output
    directory or contained within it. Raises ValueError on `..`/absolute escape."""
    root = output_dir().resolve()
    p = (get_root() / folder).resolve()
    if p != root and root not in p.parents:
        raise ValueError(f"path escapes output dir: {folder}")
    return p
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_chat.py::test_assert_within_output -v`
Expected: PASS

- [ ] **Step 5: Apply containment at the two endpoints**

In `server/app.py` `api_result`, replace the folder line (app.py:94):

```python
        folder = config.get_root() / v["folder"]
```

with:

```python
        try:
            folder = config.assert_within_output(v["folder"])
        except ValueError:
            raise HTTPException(400, "invalid view folder")
```

In `api_deck`, replace (app.py:142):

```python
        deck = config.get_root() / v["folder"] / "deck.pptx"
```

with:

```python
        try:
            deck = config.assert_within_output(v["folder"]) / "deck.pptx"
        except ValueError:
            raise HTTPException(400, "invalid view folder")
```

- [ ] **Step 6: Run the result-path test to verify no regression**

Run: `py -3 -m pytest tests/test_api.py::test_run_then_result tests/test_chat.py -v`
Expected: all PASS (legitimate `output/...` folders still resolve)

- [ ] **Step 7: Commit**

```bash
git add server/config.py server/app.py tests/test_chat.py
git commit -m "feat: assert output-dir containment on /result and /deck"
```

---

### Task 5: `web/js/chat.js` + mode toggle (frontend — manual verification)

**Files:**
- Create: `web/js/chat.js`
- Modify: `web/js/api.js` (surface HTTP status on thrown errors, api.js:4-10 — needed for `e.status === 409`)
- Modify: `web/index.html` (replace the inner ask card with the toggle + chat block, index.html:78-88 — the `<section id="sec-engine">` (76), its `<h2>` (77), and the closing `</section>` (89) are preserved)
- Modify: `web/js/main.js` (import + call `wireChat`, main.js:4 & 15)
- Modify: `web/styles.css` (append chat bubble styles)

**Interfaces:**
- Consumes: `api`, `$` (api.js); `esc`, `toast` (ui.js); `showResult` (results.js); `loadViews` (views.js); the `GET /api/chat`, `POST /api/chat/message|reset-turn|new` routes (Task 3).
- Produces: `wireChat()` export, called once at boot from `main.js`.

**Note:** No JS test framework exists in this repo; verification is the manual browser walkthrough in Steps 5-7. The existing `web/` ships no tests — do not add a framework (YAGNI).

- [ ] **Step 1: Surface the HTTP status on `api()` errors**

`chat.js` distinguishes a 409 (engine mid-turn) from any other failure via `e.status`, but `api()` (api.js:8) currently throws an `Error` whose `.message` is only the FastAPI `detail` string (`"engine is mid-turn"`), with no status. In `web/js/api.js`, replace the throw line (api.js:8):

```javascript
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
```

with:

```javascript
  if (!r.ok) {
    const detail = (await r.json().catch(() => ({}))).detail;
    const err = new Error(detail || `HTTP ${r.status}`);
    err.status = r.status;
    throw err;
  }
```

- [ ] **Step 2: Restructure the markup**

In `web/index.html`, replace the block at index.html:78-88 (the `<div class="ask card">` through `<div id="engine-items" ...>`) with:

```html
      <div class="engine-mode">
        <label><input type="radio" name="engine-mode" value="quick" checked /> Quick ask</label>
        <label><input type="radio" name="engine-mode" value="chat" /> Brainstorm chat</label>
        <button id="chat-new" class="btn" style="margin-left:auto">New chat</button>
      </div>

      <div id="engine-quick">
        <div class="ask card">
          <label for="ask-q">Business question (plain English)</label>
          <textarea id="ask-q" rows="2"
            placeholder="e.g. weekly HUMIRA TRx split by indication for the IBD market"></textarea>
          <div class="ask-row">
            <label class="chk"><input type="checkbox" id="ask-deck" /> Build slide deck too</label>
            <button id="btn-ask" class="btn primary">Send to engine</button>
          </div>
          <p class="hint">Questions queue to <code>engine_inbox/</code> and are processed by the live Claude Code session.</p>
        </div>
        <div id="engine-items" class="grid"></div>
      </div>

      <div id="engine-chat" class="card" style="display:none">
        <div id="chat-transcript" class="chat-transcript"></div>
        <div class="ask-row">
          <textarea id="chat-input" rows="2" placeholder="Ask a question, or reply…"></textarea>
          <button id="chat-send" class="btn primary">Send</button>
        </div>
        <p class="hint">Chats the live Claude Code session via <code>engine_chat/</code> — it asks follow-ups, runs the analysis, and offers a deck.</p>
      </div>
```

- [ ] **Step 3: Create `web/js/chat.js`**

```javascript
import { $, api } from './api.js';
import { esc, toast } from './ui.js';
import { showResult } from './results.js';
import { loadViews } from './views.js';

let pollTimer = null;
let pollMisses = 0;
let lastThreadJson = '';
let lastKey = '';           // composite render key (thread JSON + stalled flag)
let lastChangeAt = 0;       // when the thread JSON last changed (stall detection)
let stalled = false;

const box = () => $('#chat-transcript');

function schedulePoll() {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(() => {
    loadChat().catch((e) => {
      if (++pollMisses >= 5) toast(`Chat poll lost: ${e.message}`, 'fail');
      else schedulePoll();
    });
  }, 3000);
}

function bubble(m) {
  if (m.role === 'user') return `<div class="msg user">${esc(m.text)}</div>`;
  if (m.kind === 'question' || m.kind === 'deck_offer') {
    const chips = (m.options || []).map((o) =>
      `<button class="chip-btn" data-seq="${m.seq}" data-opt="${esc(o)}">${esc(o)}</button>`).join(' ');
    return `<div class="msg eng">${esc(m.text)}<div class="chip-row">${chips}</div></div>`;
  }
  if (m.kind === 'result') {
    return `<div class="msg eng">${esc(m.text)}<div class="chip-row">` +
      `<button class="chip-btn open-result" data-vid="${esc(m.view_id)}">Open result</button></div></div>`;
  }
  if (m.kind === 'deck_ready') {
    return `<div class="msg eng">${esc(m.text)}<div class="chip-row">` +
      `<a class="chip-btn" href="${esc(m.deck_url)}">Download deck</a></div></div>`;
  }
  if (m.kind === 'error') return `<div class="msg eng err">${esc(m.text)}</div>`;
  return `<div class="msg eng">${esc(m.text)}</div>`;
}

function render(thread) {
  const engineTurn = !!(thread.thread_id && thread.turn === 'engine');
  let html = (thread.messages || []).map(bubble).join('');
  if (engineTurn) {
    html += `<div class="msg eng status"><span class="spin"></span>${esc(thread.engine_status || 'engine working…')}</div>`;
    if (stalled) {
      html += `<div class="msg eng err">waiting for the engine — is the /loop session running?` +
        `<div class="chip-row"><button class="chip-btn" id="chat-reset">Reset turn</button></div></div>`;
    }
  }
  box().innerHTML = html || '<div class="meta">Start a brainstorm — type a question below.</div>';
  $('#chat-input').disabled = engineTurn;
  $('#chat-send').disabled = engineTurn;
  box().scrollTop = box().scrollHeight;
  wireDynamic();
}

function wireDynamic() {
  document.querySelectorAll('.chip-btn[data-opt]').forEach((el) => {
    el.onclick = () => sendMessage(el.dataset.opt,
      { in_reply_to: +el.dataset.seq, chosen: el.dataset.opt });
  });
  document.querySelectorAll('.open-result').forEach((el) => {
    el.onclick = async () => {
      try { await loadViews(); await showResult(el.dataset.vid); }
      catch (e) { toast(e.message || 'view not registered yet', 'fail'); }
    };
  });
  const reset = $('#chat-reset');
  if (reset) reset.onclick = async () => {
    await api('POST', '/api/chat/reset-turn'); stalled = false; lastThreadJson = ''; lastKey = ''; await loadChat();
  };
}

export async function loadChat() {
  const thread = await api('GET', '/api/chat');
  pollMisses = 0;
  const next = JSON.stringify(thread);
  const active = !!(thread.thread_id && thread.turn === 'engine');
  if (next !== lastThreadJson) { lastChangeAt = Date.now(); stalled = false; }
  else if (active && Date.now() - lastChangeAt > 30000) { stalled = true; }
  clearTimeout(pollTimer);
  if (active) schedulePoll();                    // restart polling for the next engine turn
  lastThreadJson = next;
  // gate on a composite key so an unchanged stalled state is not repainted every tick
  const key = next + (stalled ? '|stalled' : '');
  if (key === lastKey) return;
  lastKey = key;
  render(thread);
}

async function sendMessage(text, extra = {}) {
  const t = (text ?? $('#chat-input').value).trim();
  if (!t) { toast('Type a question first', 'fail'); return; }
  try {
    await api('POST', '/api/chat/message', { text: t, ...extra });
    $('#chat-input').value = '';
    lastThreadJson = ''; lastKey = '';   // force a repaint of the new turn
    await loadChat();
  } catch (e) {
    if (e.status === 409) toast('Engine is working — wait for its reply', 'fail');
    else toast(e.message, 'fail');
  }
}

export function wireChat() {
  const send = $('#chat-send');
  if (!send) return;
  send.onclick = () => sendMessage();
  $('#chat-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  $('#chat-new').onclick = async () => {
    try {
      await api('POST', '/api/chat/new');
    } catch (e) {
      if (e.status === 409) {
        if (!confirm('Discard the running chat?')) return;
        await api('POST', '/api/chat/new', { force: true });
      } else { toast(e.message, 'fail'); return; }
    }
    lastThreadJson = ''; lastKey = ''; stalled = false; await loadChat();
  };
  document.querySelectorAll('input[name="engine-mode"]').forEach((r) => {
    r.onchange = () => {
      const chatMode = document.querySelector('input[name="engine-mode"]:checked').value === 'chat';
      $('#engine-quick').style.display = chatMode ? 'none' : '';
      $('#engine-chat').style.display = chatMode ? '' : 'none';
      $('#chat-new').style.display = chatMode ? '' : 'none';
      if (chatMode) { lastThreadJson = ''; lastKey = ''; loadChat().catch((e) => toast(e.message, 'fail')); }
      else { clearTimeout(pollTimer); }            // stop polling while the chat panel is hidden
    };
  });
  $('#chat-new').style.display = 'none';        // hidden until chat mode is selected
}
```

- [ ] **Step 4: Wire it into `main.js`**

In `web/js/main.js`, add the import after main.js:4:

```javascript
import { wireChat } from './chat.js';
```

and call it after `wireEngine();` (main.js:15):

```javascript
wireEngine();
wireChat();
```

Append the bubble styles to `web/styles.css`:

```css
.engine-mode { display:flex; align-items:center; gap:1rem; margin-bottom:.75rem; }
.chat-transcript { display:flex; flex-direction:column; gap:.5rem; max-height:48vh; overflow-y:auto; padding:.25rem; }
.chat-transcript .msg { padding:.5rem .75rem; border-radius:.6rem; max-width:80%; white-space:pre-wrap; }
.chat-transcript .msg.user { align-self:flex-end; background:#1f6feb22; }
.chat-transcript .msg.eng { align-self:flex-start; background:#8b949e22; }
.chat-transcript .msg.eng.err { background:#f8514922; }
.chat-transcript .chip-row { display:flex; flex-wrap:wrap; gap:.4rem; margin-top:.4rem; }
.chip-btn { padding:.3rem .6rem; border-radius:.5rem; border:1px solid currentColor; background:transparent; cursor:pointer; font:inherit; color:inherit; text-decoration:none; }
.chip-btn:hover { background:#ffffff14; }
```

- [ ] **Step 5: Manual verification — start the app and the loop**

Run (terminal 1): `py -3 run_dashboard.py`
Run (terminal 2, the brain): `claude` then `/loop check engine_chat and process the active conversation`
Open the dashboard URL. In "Ask the engine", select **Brainstorm chat**. Confirm: the quick-ask card hides, the chat panel shows, "New chat" appears.
Expected: empty transcript with "Start a brainstorm — type a question below."

- [ ] **Step 6: Manual verification — full happy path**

Type `weekly tremfya TRx split by indication` and Send. Confirm:
- input disables, a spinner + "engine working…"/`engine_status` shows;
- within a few seconds the loop posts a `question` with clickable chips;
- clicking a chip (or typing) re-enables → re-disables as the turn flips;
- a `result` bubble with "Open result" appears → clicking it opens the result view;
- a `deck_offer` with Yes/No appears → "Yes" → "building deck…" → a `deck_ready` with "Download deck" that downloads the `.pptx`.

- [ ] **Step 7: Manual verification — revise, follow-up, recovery, no-regression**

Confirm each:
- type `make the deck title shorter` → a new `deck_ready` (same run folder, no new run_id);
- type `now break CD out by region` → a new analysis run + new `result`;
- with the loop NOT running, send a message, wait ~30s → the "is the /loop session running?" hint + **Reset turn** button appears; click it → input re-enables;
- switch back to **Quick ask**, send a one-line question → it still queues to `engine_inbox/` and shows a card (inbox path unaffected).

- [ ] **Step 8: Commit**

```bash
git add web/js/api.js web/js/chat.js web/index.html web/js/main.js web/styles.css
git commit -m "feat: brainstorm chat UI (transcript, chips, poll, reset-turn)"
```

---

### Task 6: MEMORY.md update + end-to-end sign-off

**Files:**
- Modify: `MEMORY.md`

- [ ] **Step 1: Record the new capability in MEMORY.md**

Add a section to `MEMORY.md` (under the dashboard area) capturing, in plain prose:
- The interactive "Brainstorm chat" path lives ALONGSIDE the one-shot inbox (inbox untouched).
- Thread model: single active `engine_chat/active.json`, archived to `engine_chat/archive/<thread_id>.json` on New chat; `turn` is the server↔loop mutex; `engine_status` is an ephemeral progress line.
- Server is still a dumb broker: `server/chat.py` (module lock + atomic `os.replace` with PermissionError retry), routes `POST /api/chat/message|reset-turn|new`, `GET /api/chat`.
- The brain is a live session running `/loop check engine_chat and process the active conversation`, contract in `ENGINE_CHAT.md` (boot/schema gate, brainstorm→6-file run→views.yaml→deck_offer→deck, follow-ups = new run_id w/ base_plan, deck-revise in place).
- `config.assert_within_output` now guards `/result` and `/deck`.
- Known limitation (no code change in this plan): `run_view_core` (views.py:173) dispatches builders only for `monthly_multiline` vs the `build_deck_pptx.py` default — it has no `holdout_segments` branch. A chat-built `holdout_segments` view re-run from the dashboard mis-renders until a `holdout_segments` branch is added to `run_view_core`.
- Tests: `tests/test_chat.py`.

- [ ] **Step 2: Full regression run**

Run: `py -3 -m pytest -q`
Expected: all tests PASS (chat + engine + api + the rest).

- [ ] **Step 3: Schema gate sanity (unchanged by this work)**

Run: `py -3 scripts/validate_schema.py`
Expected: ALL CLEAR (this feature touches no dictionaries).

- [ ] **Step 4: Commit**

```bash
git add MEMORY.md
git commit -m "docs: record interactive engine_chat path in MEMORY"
```

---

## Self-Review

**Spec coverage:**
- §2 server-dumb-broker / inbox-untouched → Tasks 2, 3 (+ Step 5 regression in Task 3).
- §4 thread model + message schema → Task 2 (`_new_thread`, `post_message` seq/in_reply_to/chosen).
- §5 state machine (turn/status/engine_status, clear on turn=user) → Task 2 + render() in Task 5.
- §6 loop protocol → `ENGINE_CHAT.md` (Task 1); the loop is the live session, not server code, so it is documented, not unit-tested.
- §7 endpoints incl. `reset-turn`, 409 inside lock → Tasks 2, 3.
- §8 UI (toggle default quick, chips, poll lifecycle restart, stall hint + Reset turn, whole-JSON repaint incl. engine_status, open-result via loadViews) → Task 5.
- §9 lock/atomic-replace, PermissionError retry, path containment → Tasks 2, 4. Cross-process detect-and-reject branch covered by a monkeypatch test; `reset_turn` empty-thread null covered (Task 2).
- §11 build order → Tasks 1→5; §11.5 MEMORY → Task 6.
- §12 acceptance → Task 5 Steps 5-7 (manual E2E) + Task 6 Step 2.

**Placeholder scan:** none — every code step carries full source; manual-verification steps list exact observable outcomes.

**Type consistency:** `chat.Conflict`, `post_message(text,in_reply_to,chosen)`, `get_active`, `reset_turn`, `new_chat(force)`, `assert_within_output(folder)`, `engine_chat_dir()`, `wireChat()`, `loadChat()` — names identical across the tasks that define and consume them. Endpoint paths identical between Task 3 (server) and Task 5 (client).

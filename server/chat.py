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

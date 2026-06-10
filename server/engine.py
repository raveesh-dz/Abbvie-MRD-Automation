"""File-based question inbox. The dashboard WRITES items; a live interactive
Claude Code session PROCESSES them (see ENGINE_INBOX.md) and updates the same
file with status/run_folder. The server never runs the engine itself."""
import itertools
import json
from datetime import datetime

from . import config

_SUFFIX = itertools.count(1)


def _dir():
    d = config.engine_inbox_dir()
    d.mkdir(exist_ok=True)
    return d


def ask(question: str, build_deck: bool = False) -> dict:
    # %f (microseconds) keeps ids unique across server restarts, where the
    # in-process _SUFFIX counter resets but same-second timestamps can repeat.
    qid = f"q_{datetime.now().strftime('%Y%m%d_%H%M%S%f')}_{next(_SUFFIX):03d}"
    item = {"id": qid, "question": question.strip(), "build_deck": bool(build_deck),
            "status": "queued",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "run_folder": None, "view_id": None, "answer": None, "error": None}
    (_dir() / f"{qid}.json").write_text(json.dumps(item, indent=2), encoding="utf-8")
    return item


def get(qid: str):
    p = _dir() / f"{qid}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def list_items() -> list:
    items = [json.loads(p.read_text(encoding="utf-8"))
             for p in sorted(_dir().glob("q_*.json"), reverse=True)]
    return items

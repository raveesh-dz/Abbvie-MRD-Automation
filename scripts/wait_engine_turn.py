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

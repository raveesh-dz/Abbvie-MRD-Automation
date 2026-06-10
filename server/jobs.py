"""In-memory background job registry. One worker lock serializes execution:
a second job queues (status stays 'queued') until the first releases the lock.
This IS the run queue — no 409s for job-based runs."""
import itertools
import threading
import traceback
from datetime import datetime

_JOBS = {}
_SEQ = itertools.count(1)
_REG_LOCK = threading.Lock()
_WORK_LOCK = threading.Lock()


def create_job(kind: str, steps: list) -> dict:
    """steps: [{"name": str, "view_id": optional str}, ...]"""
    with _REG_LOCK:
        jid = f"job_{next(_SEQ):04d}"
        job = {
            "id": jid, "kind": kind, "status": "queued",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "steps": [{"name": s["name"], "view_id": s.get("view_id"),
                       "status": "pending", "detail": ""} for s in steps],
            "summary": None, "error": None,
        }
        _JOBS[jid] = job
        finished = [k for k, v in _JOBS.items()
                    if v["status"] in ("done", "failed")]
        for k in finished[:-50]:        # keep the 50 most recent finished jobs
            del _JOBS[k]
        return job


def get_job(jid: str):
    return _JOBS.get(jid)


def update_step(job: dict, idx: int, status: str, detail: str = "") -> None:
    job["steps"][idx].update(status=status, detail=detail)


def start(job: dict, target) -> dict:
    """Run target(job) on a daemon thread under the worker lock.
    target's return value becomes job['summary']."""
    def _run():
        with _WORK_LOCK:
            job["status"] = "running"
            try:
                job["summary"] = target(job)
                job["status"] = "done"
            except Exception as e:  # noqa: BLE001 — captured for the API
                job["error"] = f"{e}\n{traceback.format_exc()}"
                job["status"] = "failed"
    threading.Thread(target=_run, daemon=True).start()
    return job

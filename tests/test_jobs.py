# tests/test_jobs.py
import time

from server import jobs


def _wait(job, timeout=5):
    for _ in range(int(timeout * 10)):
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.1)
    raise AssertionError(f"job stuck in {job['status']}")


def test_job_lifecycle_success():
    job = jobs.create_job("test", [{"name": "a"}, {"name": "b", "view_id": "v1"}])
    assert job["status"] == "queued"
    assert job["steps"][1]["view_id"] == "v1"

    def target(j):
        jobs.update_step(j, 0, "ok", "did a")
        jobs.update_step(j, 1, "ok")
        return {"x": 1}

    jobs.start(job, target)
    _wait(job)
    assert job["status"] == "done"
    assert job["summary"] == {"x": 1}
    assert [s["status"] for s in job["steps"]] == ["ok", "ok"]
    assert jobs.get_job(job["id"]) is job


def test_job_failure_captured():
    job = jobs.create_job("test", [{"name": "a"}])

    def target(j):
        raise RuntimeError("boom")

    jobs.start(job, target)
    _wait(job)
    assert job["status"] == "failed"
    assert "boom" in job["error"]


def test_jobs_serialize_in_order():
    # Deterministic: j1 provably OWNS the worker lock before j2 starts,
    # so this can never pass/fail on thread-scheduling luck.
    order = []
    j1 = jobs.create_job("test", [{"name": "a"}])
    j2 = jobs.create_job("test", [{"name": "a"}])
    release = []

    def slow(j):
        while not release:          # hold the lock until the test lets go
            time.sleep(0.02)
        order.append("first")

    def fast(j):
        order.append("second")

    jobs.start(j1, slow)
    for _ in range(50):
        if j1["status"] == "running":
            break
        time.sleep(0.02)
    assert j1["status"] == "running"
    jobs.start(j2, fast)
    time.sleep(0.1)
    assert j2["status"] == "queued"   # queued behind j1 — no 409, item 12
    release.append(True)
    _wait(j1); _wait(j2)
    assert order == ["first", "second"]

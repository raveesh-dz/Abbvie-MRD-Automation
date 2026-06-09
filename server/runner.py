"""Run the project's existing scripts via subprocess, with a single in-flight
lock and the validate_result exit-code convention (0/2 = pass, 1 = fail)."""
import subprocess
import sys
import threading


class Busy(Exception):
    """Raised when a run is already in progress."""


_LOCK = threading.Lock()


class run_lock:
    def __enter__(self):
        if not _LOCK.acquire(blocking=False):
            raise Busy("another run is in progress")
        return self

    def __exit__(self, *exc):
        _LOCK.release()
        return False


def run_script(args, cwd=None):
    """Run `<this python> <args...>`; return (returncode, stdout, stderr).
    sys.executable is the py -3 interpreter running the server, so spawned
    analysis_code.py / validate_result.py / build_deck_pptx.py see the same
    pandas/pptx install. analysis_code.py finds the project root via parents[2]
    of its own location, so cwd is irrelevant to it."""
    proc = subprocess.run([sys.executable, *args], cwd=cwd,
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def validation_ok(code: int) -> bool:
    return code in (0, 2)

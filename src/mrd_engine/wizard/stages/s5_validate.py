"""
Stage 5 — run the schema gate, parse the summary, surface to user.

Optionally runs --include-remote to handshake Snowflake for drift checks.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from mrd_engine.wizard import prompts, state as state_mod
from mrd_engine.wizard.state import WizardState


_ACTIVE_RE   = re.compile(r"Tables active for analysis\s*:\s*(.+)$", re.M)
_EXCLUDED_RE = re.compile(r"Tables excluded\s*:\s*(.+)$", re.M)
_WARN_RE     = re.compile(r"^\s*\[WARN\]\s+(.*)$", re.M)
_ERR_RE      = re.compile(r"^\s*\[ERROR\]\s+(.*)$", re.M)


def _run_validate(repo: Path, include_remote: bool) -> dict:
    cmd = [sys.executable, str(repo / "scripts" / "validate_schema.py"),
           "--root", str(repo)]
    if include_remote:
        cmd.append("--include-remote")
    prompts.info(f"running: {' '.join(cmd[-3:])}")
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    out = proc.stdout + proc.stderr
    print(out)
    summary = {
        "exit_code": proc.returncode,
        "active":   _parse_list(_ACTIVE_RE,   out),
        "excluded": _parse_list(_EXCLUDED_RE, out),
        "warnings": _WARN_RE.findall(out),
        "errors":   _ERR_RE.findall(out),
    }
    return summary


def _parse_list(rx, text: str) -> list[str]:
    m = rx.search(text)
    if not m:
        return []
    raw = m.group(1).strip()
    if raw.lower() in {"none", "[]", "['none']"}:
        return []
    return [x.strip().strip("'[]\"") for x in raw.strip("[]").split(",") if x.strip()]


def run(repo: Path, state: WizardState) -> str:
    prompts.rule("Stage 5 — validate data layer")
    state.stage = "s5_validate"

    include_remote = prompts.yesno(
        "also handshake Snowflake to check remote schema drift?", default=False,
    )
    summary = _run_validate(repo, include_remote)
    state.validation_summary = {
        "active":   len(summary["active"]),
        "excluded": len(summary["excluded"]),
        "warnings": len(summary["warnings"]),
        "errors":   len(summary["errors"]),
        "exit_code": summary["exit_code"],
    }
    state_mod.save(repo, state)

    if summary["errors"]:
        prompts.err(f"{len(summary['errors'])} ERROR(s) — data layer is NOT ready.")
        if prompts.yesno("re-run validate?", default=False):
            return "s5_validate"
    elif summary["warnings"]:
        prompts.warn(f"{len(summary['warnings'])} warning(s) — proceed with care.")
    else:
        prompts.ok("ALL CLEAR.")

    return "s6_signoff"

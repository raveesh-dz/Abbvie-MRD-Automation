"""
Stage 6 — final signoff. Print summary, write session log, clear state on yes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from mrd_engine.wizard import prompts, state as state_mod, summary as summary_mod
from mrd_engine.wizard.state import WizardState


def run(repo: Path, state: WizardState) -> str:
    prompts.rule("Stage 6 — final signoff")
    state.stage = "s6_signoff"

    summary_mod.print_final_summary(state)

    v = state.validation_summary or {}
    if int(v.get("errors", 0)) > 0:
        prompts.err("validation has errors — cannot confirm data layer.")
        return _route_remaining(state)

    if prompts.yesno("confirm data layer is ready?", default=True):
        state.completed_at = datetime.now(timezone.utc).isoformat()
        state.stage = "done"
        log_path = summary_mod.write_log(state, repo)
        prompts.ok(f"session log -> {log_path.relative_to(repo)}")
        # write "ready" sentinel
        ready = repo / "profiles" / "_data_layer_ready.json"
        ready.parent.mkdir(parents=True, exist_ok=True)
        import json
        ready.write_text(json.dumps({
            "confirmed_at": state.completed_at,
            "tables": state.onboarded_this_session + state.reviewed_this_session,
            "edges_accepted": len(state.accepted_edges),
        }, indent=2), encoding="utf-8")
        prompts.ok(f"sentinel  -> {ready.relative_to(repo)}")
        state_mod.clear(repo)
        prompts.ok("data layer confirmed. Open Claude Code and ask your question.")
        return "done"

    return _route_remaining(state)


def _route_remaining(state: WizardState) -> str:
    while True:
        opts = [
            ("a", "Add another table"),
            ("b", "More joins (re-run discovery)"),
            ("c", "Re-validate"),
            ("d", "Exit without confirming"),
        ]
        ans = prompts.menu("What's remaining?", opts, default="a")
        if ans == "a":
            return "s1_onboard"
        if ans == "b":
            return "s3_joins"
        if ans == "c":
            return "s5_validate"
        if ans == "d":
            return "done"

"""
mrd init -- main orchestrator. Dispatches between stages until "done".
"""
from __future__ import annotations

import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from mrd_engine.wizard import prompts, state as state_mod
from mrd_engine.wizard.state import WizardState
from mrd_engine.wizard.stages import (
    s0_inventory, s1_onboard, s2_review, s3_joins, s4_manual_edges,
    s5_validate, s6_signoff,
)


_STAGE_FNS: dict[str, Callable] = {
    "s0_inventory":   s0_inventory.run,
    "s1_onboard":     s1_onboard.run,
    "s2_review":      s2_review.run,
    "s3_joins":       s3_joins.run,
    "s4_manual_edges": s4_manual_edges.run,
    "s5_validate":    s5_validate.run,
    "s6_signoff":     s6_signoff.run,
}


def _new_state() -> WizardState:
    return WizardState(
        started_at=datetime.now(timezone.utc).isoformat(),
        stage="s0_inventory",
    )


def run(repo: Path, *, resume: bool = False,
        auto_metadata: bool = False, no_joins: bool = False,
        review_mode: str = "inline", backend: str = "claude_cli",
        dry_run: bool = False) -> int:
    # Load or create state
    if resume:
        s = state_mod.load(repo)
        if s is None:
            prompts.warn("no saved state — starting fresh.")
            s = _new_state()
        else:
            stale = state_mod.stale_files(s, repo)
            if stale:
                prompts.warn("files changed on disk since last session:")
                for f in stale[:10]:
                    prompts.warn(f"  {f}")
                if not prompts.yesno("resume anyway?", default=False):
                    s = _new_state()
                    state_mod.clear(repo)
    else:
        s = _new_state()
        state_mod.clear(repo)
    state_mod.save(repo, s)

    def _on_sigint(signum, frame):
        prompts.warn("\ninterrupted — saving state for --resume...")
        state_mod.save(repo, s)
        sys.exit(130)

    signal.signal(signal.SIGINT, _on_sigint)

    next_stage = s.stage or "s0_inventory"
    while next_stage and next_stage != "done":
        fn = _STAGE_FNS.get(next_stage)
        if fn is None:
            prompts.err(f"unknown stage '{next_stage}'")
            return 1
        try:
            if next_stage == "s1_onboard":
                next_stage = fn(repo, s, backend=backend, auto_metadata=auto_metadata)
            elif next_stage == "s1_onboard_refresh":
                next_stage = s1_onboard.run_refresh(repo, s)
            elif next_stage == "s2_review":
                next_stage = fn(repo, s, mode="auto" if auto_metadata else review_mode)
            elif next_stage == "s3_joins":
                if no_joins:
                    next_stage = "s5_validate"
                else:
                    next_stage = fn(repo, s)
            elif next_stage == "s0_inventory":
                next_stage = fn(repo, s, dry_run=dry_run)
            else:
                next_stage = fn(repo, s)
            # Don't re-save after Stage 6 cleared the file on successful completion.
            if next_stage != "done":
                state_mod.save(repo, s)
        except KeyboardInterrupt:
            prompts.warn("interrupted — state saved.")
            return 130
        except Exception as exc:
            prompts.err(f"stage {next_stage} crashed: {exc}")
            import traceback
            traceback.print_exc()
            return 2
    s1_onboard.close_all()
    return 0

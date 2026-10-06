"""
Wizard state — persists across sessions so `mrd init --resume` works.

Stored at profiles/_wizard_state.json. Wiped on successful Stage 6 confirmation.
Captures file mtimes of touched files so we can detect external edits on resume.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class WizardState:
    version: int = 1
    started_at: str = ""
    last_updated_at: str = ""
    completed_at: str | None = None
    stage: str = "s0_inventory"          # s0..s6 or "done"
    onboarded_this_session: list[str] = field(default_factory=list)
    pending_review: list[str] = field(default_factory=list)
    reviewed_this_session: list[str] = field(default_factory=list)
    accepted_edges: list[tuple[str, str, str]] = field(default_factory=list)
    rejected_edges: list[tuple[str, str, str]] = field(default_factory=list)
    manual_edges: list[dict[str, Any]] = field(default_factory=list)
    validation_summary: dict[str, Any] = field(default_factory=dict)
    file_signatures: dict[str, float] = field(default_factory=dict)   # path -> mtime
    user_choices: list[dict[str, Any]] = field(default_factory=list)  # audit trail

    def stamp(self) -> None:
        self.last_updated_at = datetime.now(timezone.utc).isoformat()

    def record_choice(self, stage: str, key: str, value: Any) -> None:
        self.user_choices.append({
            "stage": stage, "key": key, "value": value,
            "at": datetime.now(timezone.utc).isoformat(),
        })


def _state_path(repo: Path) -> Path:
    return repo / "profiles" / "_wizard_state.json"


def load(repo: Path) -> WizardState | None:
    p = _state_path(repo)
    if not p.exists():
        return None
    raw = json.loads(p.read_text(encoding="utf-8"))
    # tuples come back as lists in JSON
    raw["accepted_edges"] = [tuple(e) for e in raw.get("accepted_edges", [])]
    raw["rejected_edges"] = [tuple(e) for e in raw.get("rejected_edges", [])]
    return WizardState(**raw)


def save(repo: Path, state: WizardState) -> Path:
    p = _state_path(repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    state.stamp()
    p.write_text(json.dumps(asdict(state), indent=2, default=str), encoding="utf-8")
    return p


def clear(repo: Path) -> None:
    p = _state_path(repo)
    if p.exists():
        p.unlink()


def signature(paths: list[Path]) -> dict[str, float]:
    """Record mtimes for resume staleness detection."""
    out = {}
    for p in paths:
        if p.exists():
            out[str(p)] = p.stat().st_mtime
    return out


def stale_files(state: WizardState, repo: Path) -> list[str]:
    """Files that changed on disk since state was saved."""
    drift = []
    for path_str, recorded in (state.file_signatures or {}).items():
        p = Path(path_str)
        if not p.exists():
            drift.append(path_str + " (deleted)")
        elif abs(p.stat().st_mtime - recorded) > 1.0:
            drift.append(path_str + " (modified)")
    return drift

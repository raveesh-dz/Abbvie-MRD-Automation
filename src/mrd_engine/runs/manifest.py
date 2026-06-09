"""
Source manifest for a run folder. Records connector / fetched_at / row count
/ column hash per table the run touched. Makes runs reproducible.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from mrd_engine.connectors.base import Manifest


def write_manifest(run_dir: Path, manifests: Iterable[Manifest]) -> Path:
    out = run_dir / "source_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        m.table: {
            "connector": m.connector,
            "source_object": m.source_object,
            "fetched_at": m.fetched_at,
            "row_count": m.row_count,
            "column_count": m.column_count,
            "column_hash": m.column_hash,
            "cache_path": m.cache_path,
        }
        for m in manifests
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out

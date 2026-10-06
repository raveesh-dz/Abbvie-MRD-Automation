"""
Stage 1 — onboard new tables (loop). Reuses a single Snowflake connector across
the wizard session so the user only sees ONE SSO popup.

Two entrypoints:
  run()         — normal onboard loop (add new tables)
  run_refresh() — re-fetch stale tables (preserves the existing dict)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from rich.console import Console

from mrd_engine.connectors import get_connector
from mrd_engine.connectors.base import Manifest
from mrd_engine.metadata.profiler import profile_table
from mrd_engine.metadata.proposer import propose
from mrd_engine.wizard import prompts, scan, state as state_mod
from mrd_engine.wizard.state import WizardState

console = Console()

_REGISTERED_CONNECTORS_CACHE: dict[str, Any] = {}


def _list_connectors(repo: Path) -> list[tuple[str, str]]:
    """(connector_name, connector_type) tuples from connectors/*.yaml."""
    out: list[tuple[str, str]] = []
    for p in sorted((repo / "connectors").glob("*.yaml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        out.append((d.get("name", p.stem), d.get("type", "?")))
    return out


def _shared_conn(repo: Path, ctype: str):
    """Open once per type per wizard session (avoids N SSO popups)."""
    if ctype in _REGISTERED_CONNECTORS_CACHE:
        return _REGISTERED_CONNECTORS_CACHE[ctype]
    conn = get_connector(ctype, repo)
    _REGISTERED_CONNECTORS_CACHE[ctype] = conn
    return conn


def close_all() -> None:
    for c in _REGISTERED_CONNECTORS_CACHE.values():
        if hasattr(c, "close"):
            try:
                c.close()
            except Exception:
                pass
    _REGISTERED_CONNECTORS_CACHE.clear()


def _derive_table_name(source_object: str) -> str:
    if source_object.lower().endswith((".csv", ".parquet", ".tsv", ".json")) \
            or "/" in source_object or "\\" in source_object:
        return Path(source_object).stem
    return source_object.split(".")[-1]


def _onboard_one(repo: Path, connector_name: str, ctype: str, source_object: str,
                 table_override: str | None, backend: str, row_cap: int,
                 user_context: str | None = None) -> str:
    table = table_override or _derive_table_name(source_object)
    target = repo / "data" / "_cache" / f"{table}.parquet"

    prompts.info(f"fetching {source_object} via {connector_name}...")
    conn = _shared_conn(repo, ctype)
    manifest: Manifest = conn.fetch(source_object, target, row_cap=row_cap)
    manifest.connector = connector_name
    prompts.ok(f"fetched {manifest.row_count:,} rows, {manifest.column_count} cols -> "
               f"{target.relative_to(repo)}")

    prompts.info("profiling...")
    profile_path = repo / "profiles" / f"{table}.json"
    profile = profile_table(target, profile_path)

    prompts.info(f"proposing metadata ({backend})...")
    source_block = {
        "connector": connector_name,
        "type": ctype,
        "object": source_object,
        "cache_path": str(target.relative_to(repo)),
        "fetched_at": manifest.fetched_at,
        "row_count_at_onboard": manifest.row_count,
        "column_hash": manifest.column_hash,
    }
    fqn = source_object if ctype == "snowflake" else Path(source_object).name
    proposal = propose(
        table, fqn, profile, source_block,
        backend=backend, user_context=user_context, repo_root=repo,
    )
    # If we fell back to heuristic, surface that
    desc = proposal.get("description", "")
    if "AUTO-GENERATED (heuristic)" in desc:
        prompts.warn(f"{table}: claude_cli backend unavailable, used heuristic fallback")
    proposed_path = repo / "metadata" / f"{table}.yaml.proposed"
    proposed_path.write_text(
        yaml.safe_dump(proposal, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    prompts.ok(f"wrote {proposed_path.relative_to(repo)}")
    return table


def _snowflake_handshake(repo: Path, ctype: str) -> bool:
    try:
        prompts.info("handshake with Snowflake (SSO popup may appear once)...")
        info = _shared_conn(repo, ctype).handshake()
        prompts.ok(
            f"snowflake OK: role={info.get('role')}, warehouse={info.get('warehouse')}, "
            f"db={info.get('database')}, schema={info.get('schema')}"
        )
        return True
    except Exception as exc:
        prompts.err(f"snowflake handshake failed: {exc}")
        return False


def _ask_context(label: str) -> str | None:
    """
    Prompt the user for free-text context about the table before metadata propose.

    Two modes:
      - 'one-liner' (default): single line, fast
      - 'file': point at a markdown file with longer context
    Returns the resolved string (or None if user skipped).
    """
    mode = prompts.choice(
        f"context for {label}? (l)ine / (f)ile / (s)kip",
        options=["l", "f", "s"], default="s",
    )
    if mode == "s":
        return None
    if mode == "f":
        path = prompts.text("path to context file (relative or absolute)")
        from pathlib import Path as _P
        p = _P(path)
        if not p.exists():
            prompts.warn(f"file not found: {p} — skipping context")
            return None
        return p.read_text(encoding="utf-8").strip() or None
    # mode == 'l'
    line = prompts.text(
        "one-line context (what is this table? domain? traps? definitions?)",
        allow_empty=True,
    )
    return line.strip() or None


def _batch_untracked_csv_offer(repo: Path) -> list[str]:
    """If untracked CSVs exist in /data/, offer batch onboard."""
    inv = scan.classify(repo)
    if not inv.untracked_csvs:
        return []
    prompts.info(f"found {len(inv.untracked_csvs)} untracked CSV(s) in /data/:")
    for c in inv.untracked_csvs:
        console.print(f"  - {c}")
    if not prompts.yesno("batch-onboard all of them now? (csv_local)", default=False):
        return []
    return [Path(c).name for c in inv.untracked_csvs]


def run(repo: Path, state: WizardState, *,
        backend: str = "claude_cli", auto_metadata: bool = False) -> str:
    prompts.rule("Stage 1 — onboard new tables")
    state.stage = "s1_onboard"

    # First: offer batch CSV onboard if relevant
    batch = _batch_untracked_csv_offer(repo)
    for fname in batch:
        try:
            ctx = _ask_context(fname)
            t = _onboard_one(repo, "csv_local", "csv_local", fname, None,
                             backend=backend, row_cap=10_000_000, user_context=ctx)
            state.onboarded_this_session.append(t)
            state.pending_review.append(t)
            state_mod.save(repo, state)
        except Exception as exc:
            prompts.err(f"failed {fname}: {exc}")

    # Then: per-table interactive loop
    connectors = _list_connectors(repo)
    while True:
        if not prompts.yesno("add another table?", default=True):
            break
        connector_options = [(name, f"{name}  ({ctype})") for name, ctype in connectors]
        connector_options.append(("done", "done — finish onboarding"))
        chosen = prompts.menu("Source connector",
                              connector_options, default=connector_options[0][0])
        if chosen == "done":
            break
        ctype = dict(connectors)[chosen]

        if ctype == "snowflake":
            if not _snowflake_handshake(repo, ctype):
                if not prompts.yesno("retry?", default=True):
                    continue
                if not _snowflake_handshake(repo, ctype):
                    prompts.err("skipping this table.")
                    continue
            source_object = prompts.text(
                "Snowflake FQN (DB.SCHEMA.TABLE)",
            )
        else:  # csv_local or future
            source_object = prompts.text(
                "Path (relative to /data/ or absolute, e.g. ndc_brand_crosswalk.csv)",
            )

        override = prompts.text("Override table name? (Enter to derive)",
                                default="", allow_empty=True)
        ctx = _ask_context(source_object)
        try:
            t = _onboard_one(repo, chosen, ctype, source_object,
                             override or None, backend=backend, row_cap=10_000_000,
                             user_context=ctx)
            state.onboarded_this_session.append(t)
            state.pending_review.append(t)
            state.record_choice("s1_onboard", "onboarded", t)
            state_mod.save(repo, state)
        except Exception as exc:
            prompts.err(f"onboard failed: {exc}")
            if not prompts.yesno("continue with another table?", default=True):
                break

    return "s2_review" if state.pending_review else "s3_joins"


def run_refresh(repo: Path, state: WizardState) -> str:
    """Refresh stale tables: re-fetch cache, preserve dict."""
    prompts.rule("Stage 1 — refresh stale tables")
    state.stage = "s1_onboard_refresh"
    inv = scan.classify(repo)
    stale = scan.stale_tables(inv)
    if not stale:
        prompts.info("no stale tables — nothing to refresh.")
        return "s3_joins"
    prompts.info(f"stale: {stale}")
    for t in stale:
        if not prompts.yesno(f"refresh {t}?", default=True):
            continue
        ymf = repo / "metadata" / f"{t}.yaml"
        d = yaml.safe_load(ymf.read_text(encoding="utf-8")) or {}
        src = d.get("source") or {}
        ctype = src.get("type")
        cname = src.get("connector")
        obj = src.get("object")
        if not (ctype and obj):
            prompts.err(f"{t}: source block incomplete, skipping.")
            continue
        if ctype == "snowflake" and not _snowflake_handshake(repo, ctype):
            continue
        try:
            target = repo / "data" / "_cache" / f"{t}.parquet"
            manifest = _shared_conn(repo, ctype).fetch(obj, target, row_cap=10_000_000)
            d["source"]["fetched_at"] = manifest.fetched_at
            d["source"]["row_count_at_onboard"] = manifest.row_count
            d["source"]["column_hash"] = manifest.column_hash
            ymf.write_text(yaml.safe_dump(d, sort_keys=False, allow_unicode=True),
                           encoding="utf-8")
            prompts.ok(f"refreshed {t} ({manifest.row_count:,} rows)")
        except Exception as exc:
            prompts.err(f"{t}: {exc}")
    return "s3_joins"

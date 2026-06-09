"""One-time, idempotent: build canonical output/<view_id>/ folders from the best
existing runs, normalizing the analysis_plan so validation survives data growth.

Kept directly under output/ so analysis_code.py's parents[2] still resolves to
the project root. Honors QTS_ROOT (default = repo root)."""
import os
import re
from pathlib import Path

ROOT = Path(os.environ.get("QTS_ROOT", str(Path(__file__).resolve().parents[1])))

SEEDS = {
    "tremfya_ibd_split": "run_2026-06-08_001",
    "skyrizi_ibd_split": "run_2026-06-08_002",
}
COPY = ["analysis_code.py", "analysis_plan.md", "deck_spec.json",
        "context.md", "takeaways.md", "query.txt"]


def normalize_plan(text: str) -> str:
    """Drop the pinned numeric row count and mark the series full-grain, so
    validate_result.py passes as weeks accrue."""
    return re.sub(
        r"expected_row_count:.*",
        "expected_row_count: full grain — one row per WEEK_ENDING (grows with data)",
        text,
    )


def main():
    out = ROOT / "output"
    for vid, src in SEEDS.items():
        s, d = out / src, out / vid
        d.mkdir(parents=True, exist_ok=True)
        for f in COPY:
            sp = s / f
            if not sp.exists():
                continue
            text = sp.read_text(encoding="utf-8")
            if f == "analysis_plan.md":
                text = normalize_plan(text)
            (d / f).write_text(text, encoding="utf-8")
        print(f"seeded {vid} from {src}")


if __name__ == "__main__":
    main()

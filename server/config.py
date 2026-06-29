"""Path helpers. Every path derives from QTS_ROOT (default = repo root) so tests
can redirect the whole app at a temp copy by setting one env var."""
import os
from pathlib import Path

_DEFAULT_ROOT = Path(__file__).resolve().parents[1]  # server/ -> repo root


def get_root() -> Path:
    return Path(os.environ.get("QTS_ROOT", str(_DEFAULT_ROOT)))


def data_dir() -> Path:
    return get_root() / "data"


def metadata_dir() -> Path:
    return get_root() / "metadata"


def output_dir() -> Path:
    return get_root() / "output"


def scripts_dir() -> Path:
    return get_root() / "scripts"


def web_dir() -> Path:
    return get_root() / "web"


def views_file() -> Path:
    return get_root() / "views.yaml"


def snapshot_file() -> Path:
    return data_dir() / ".snapshot.json"


def original_backup_dir() -> Path:
    return data_dir() / "_original"


def engine_inbox_dir() -> Path:
    return get_root() / "engine_inbox"


def engine_chat_dir() -> Path:
    return get_root() / "engine_chat"

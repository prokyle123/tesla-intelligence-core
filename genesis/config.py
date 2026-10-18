"""Safe defaults for the optional GENESIS research lab."""
from __future__ import annotations
import os
from pathlib import Path

FEATURE_FLAG = "GHOST_GENESIS_ENABLED"
SOURCE_DB_ENV = "GHOST_AI_DB"
DATA_DIR_ENV = "GHOST_GENESIS_DATA_DIR"

def _get(name: str, default: str) -> str:
    # GHOST uses /etc/ghost-tesla-ai/ghost.env, in addition to process env.
    try:
        from ghost_tesla_ai.config import get
        return get(name, default)
    except ImportError:
        return os.environ.get(name, default)

def enabled() -> bool:
    return _get(FEATURE_FLAG, "false").strip().lower() in {"1", "true", "yes", "on"}

def source_db() -> Path:
    return Path(_get(SOURCE_DB_ENV, "/var/lib/ghost-tesla-ai/ghost_ai.sqlite3")).expanduser()

def data_dir() -> Path:
    return Path(_get(DATA_DIR_ENV, "/var/lib/ghost-tesla-ai/genesis")).expanduser()

def research_db() -> Path:
    return data_dir() / "research.sqlite3"

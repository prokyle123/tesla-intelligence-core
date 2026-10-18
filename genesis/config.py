"""Safe defaults for the optional GENESIS research lab."""
from __future__ import annotations

import os
from pathlib import Path

FEATURE_FLAG = "GHOST_GENESIS_ENABLED"
SOURCE_DB_ENV = "GHOST_AI_DB"
DATA_DIR_ENV = "GHOST_GENESIS_DATA_DIR"
FLEET_MODE_ENV = "GHOST_HIVEMIND_MODE"

def enabled() -> bool:
    return os.getenv(FEATURE_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}

def source_db() -> Path:
    return Path(os.environ.get(SOURCE_DB_ENV, "/var/lib/ghost-tesla-ai/ghost_ai.sqlite3")).expanduser()

def data_dir() -> Path:
    return Path(os.environ.get(DATA_DIR_ENV, "/var/lib/ghost-tesla-ai/genesis")).expanduser()

def research_db() -> Path:
    return data_dir() / "research.sqlite3"

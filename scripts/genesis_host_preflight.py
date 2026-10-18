#!/usr/bin/env python3
"""Read-only host readiness report for safe GENESIS staging.

No writes, background tasks, network access, authentication secrets, VINs,
timestamps of drives, vehicle values or machine identifiers are printed.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import sqlite3
import subprocess
from pathlib import Path
from urllib.parse import quote

DATA = Path("/var/lib/ghost-tesla-ai")
SOURCE = DATA / "ghost_ai.sqlite3"
PRIVATE_ENV = Path("/etc/ghost-tesla-ai/ghost.env")
SERVICES = ("ghost-tesla-ai-web.service", "ghost-tesla-ai-collector.service",
            "ghost-tesla-ai-neural.timer", "ghost-tesla-ai-train.timer",
            "ghost-trip-shadow.timer")

def safe_flags() -> dict:
    flags = {"GHOST_GENESIS_ENABLED": "unset", "GHOST_HIVEMIND_MODE": "unset"}
    try:
        for line in PRIVATE_ENV.read_text().splitlines():
            key, sep, value = line.partition("=")
            key = key.strip()
            if sep and key in flags:
                v = value.strip().strip('"').strip("'").lower()
                if key == "GHOST_GENESIS_ENABLED":
                    flags[key] = "enabled" if v in ("1","yes","true","on") else "disabled"
                else:
                    flags[key] = v if v in ("off","receive","contribute") else "invalid"
    except (OSError, UnicodeError):
        pass
    # Process overrides without ever echoing unrelated environment variables.
    for key in flags:
        v = os.environ.get(key)
        if v is not None:
            v = v.strip().lower()
            flags[key] = ("enabled" if v in ("1","yes","true","on") else "disabled") if key == "GHOST_GENESIS_ENABLED" else (v if v in ("off","receive","contribute") else "invalid")
    return flags

def service_state(name: str) -> str:
    try:
        p = subprocess.run(("systemctl", "is-active", name),
                           capture_output=True, text=True, timeout=3, check=False)
        value = p.stdout.strip()
        return value if value in ("active", "inactive", "failed", "activating", "deactivating") else "unknown"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"

def memory_mb() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except (ValueError, IndexError, OSError):
        pass
    return None

def source_meta(path: Path = SOURCE) -> dict:
    if not path.is_file():
        return {"present": False}
    details = {"present": True, "size_mb": round(path.stat().st_size / 1048576, 1)}
    try:
        uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=2.0) as con:
            con.execute("PRAGMA query_only=ON")
            if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='telemetry'").fetchone():
                details["telemetry_rows"] = int(con.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0])
                cols = {r[1] for r in con.execute("PRAGMA table_info(telemetry)")}
                if "car_id" in cols:
                    details["multiple_vehicles"] = con.execute("SELECT COUNT(DISTINCT car_id) > 1 FROM telemetry").fetchone()[0] == 1
            else:
                details["telemetry_rows"] = None
    except (sqlite3.Error, OSError):
        details["readable"] = False
    else:
        details["readable"] = True
    return details

def report() -> dict:
    target = DATA if DATA.exists() else Path("/")
    free_gb = round(shutil.disk_usage(target).free / (1024**3), 2)
    available = memory_mb()
    db = source_meta()
    services = {name: service_state(name) for name in SERVICES}
    warnings = []
    if free_gb < 1.0:
        warnings.append("Less than 1 GiB available disk; inspect before enabling research.")
    if available is not None and available < 512:
        warnings.append("Less than 512 MiB available memory; inspect competing workloads.")
    if not db.get("present") or not db.get("readable", False):
        warnings.append("Production telemetry database missing or not readable.")
    if db.get("multiple_vehicles"):
        warnings.append("Multiple vehicles: the first Genesis engine refuses mixed histories.")
    if services["ghost-tesla-ai-web.service"] != "active":
        warnings.append("Existing web service is not active; baseline investigation needed.")
    return {
        "scope": "READ_ONLY_HOST_PREFLIGHT",
        "platform_architecture": platform.machine(),
        "available_memory_mb": available,
        "available_disk_gb": free_gb,
        "production_database": db,
        "services": services,
        "genesis_flags": safe_flags(),
        "warnings": warnings,
        "changes_made": False,
        "network_calls": False,
        "credentials_printed": False,
    }

if __name__ == "__main__":
    print(json.dumps(report(), indent=2, sort_keys=True))

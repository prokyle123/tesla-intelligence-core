"""Allowlisted, read-only access to GHOST's existing telemetry.

No SELECT *; no VIN, car ID, coordinates, raw JSON, route or address columns.
The source database is NEVER initialized, migrated, or written by GENESIS.
"""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from urllib.parse import quote

ALLOWED_METRICS = (
    "battery_temp_c", "outside_temp_c", "inside_temp_c",
    "battery_level", "speed_kmh", "power_kw", "pack_power_kw",
    "charger_power_kw", "charge_input_kw", "module_temp_spread_c",
    "pack_current_abs_a", "preconditioning", "battery_heater_on",
)
MAX_ROWS = 12000

class SourceUnavailable(RuntimeError):
    """A safe, non-sensitive explanation of unavailable source telemetry."""

def load_numeric_history(path: Path, limit: int = 6000) -> list[dict[str, float | None]]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise SourceUnavailable("Telemetry database is not available.")
    limit = max(1, min(int(limit), MAX_ROWS))
    uri = "file:" + quote(str(path), safe="/") + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=1.0) as con:
            con.execute("PRAGMA query_only=ON")
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "telemetry" not in tables:
                raise SourceUnavailable("Telemetry table is unavailable.")
            cols = {r[1] for r in con.execute("PRAGMA table_info(telemetry)")}
            if "ts" not in cols:
                raise SourceUnavailable("Timestamp column is unavailable.")
            if "car_id" in cols:
                # Abort rather than accidentally mixing separate vehicles or exporting an identifier.
                n = con.execute("SELECT COUNT(DISTINCT car_id) FROM telemetry").fetchone()[0]
                if n > 1:
                    raise SourceUnavailable("Multiple vehicles detected. Per-vehicle research selection is not implemented.")
            metrics = [key for key in ALLOWED_METRICS if key in cols]
            if len(metrics) < 2:
                raise SourceUnavailable("Insufficient supported telemetry columns.")
            sql = "SELECT ts, " + ", ".join('"' + c + '"' for c in metrics) + ' FROM telemetry ORDER BY ts DESC LIMIT ?'
            rows = con.execute(sql, (limit,)).fetchall()
    except sqlite3.Error as exc:
        raise SourceUnavailable("Telemetry database could not be read safely.") from exc
    out: list[dict[str, float | None]] = []
    for row in reversed(rows):
        try:
            ts = float(row[0])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(ts):
            continue
        item: dict[str, float | None] = {"ts": ts}
        for key, value in zip(metrics, row[1:]):
            try:
                f = float(value)
                item[key] = f if math.isfinite(f) else None
            except (ValueError, TypeError, OverflowError):
                item[key] = None
        out.append(item)
    return out

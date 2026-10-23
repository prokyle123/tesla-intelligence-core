"""Bounded private historical data for the GENESIS experiment architect.

Loads only numeric allowlisted columns plus local ordering timestamps.
Read-only SQL snapshot. No ID, VIN, location, route, raw JSON or API calls.
"""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from urllib.parse import quote

from .history_audit import MAX_BLOCKS, MAX_ROWS_PER_BLOCK, MAX_TOTAL_ROWS
from .source import ALLOWED_METRICS, SourceUnavailable


def historical_blocks(source_db: Path, blocks: int = 5,
                      rows_per_block: int = 2400) -> list[list[dict]]:
    """Disjoint chronological sample windows, at most 12,000 records total."""
    if not 3 <= blocks <= MAX_BLOCKS:
        raise ValueError("Experimental research requires between 3 and 6 historical blocks.")
    if not 100 <= rows_per_block <= MAX_ROWS_PER_BLOCK:
        raise ValueError("Unsupported records per block.")
    if blocks * rows_per_block > MAX_TOTAL_ROWS:
        raise ValueError("Experiment exceeds 12,000 raw observations.")
    path = Path(source_db).expanduser().resolve()
    if not path.is_file():
        raise SourceUnavailable("Telemetry database unavailable.")
    uri = "file:" + quote(str(path), safe="/") + "?mode=ro"
    result = []
    try:
        with sqlite3.connect(uri, uri=True, timeout=2.0) as con:
            con.execute("PRAGMA query_only=ON")
            con.execute("BEGIN")
            schema = {r[1] for r in con.execute("PRAGMA table_info(telemetry)")}
            if "ts" not in schema:
                raise SourceUnavailable("Telemetry schema missing timestamps.")
            if "car_id" in schema:
                count = con.execute("SELECT COUNT(DISTINCT car_id) FROM telemetry").fetchone()[0]
                if count > 1:
                    raise SourceUnavailable("Multiple vehicles detected. Per-vehicle research is not implemented.")
            cols = [name for name in ALLOWED_METRICS if name in schema]
            if len(cols) < 2:
                raise SourceUnavailable("Insufficient numerical telemetry.")
            total = con.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0]
            if total < blocks * rows_per_block:
                raise SourceUnavailable("Insufficient nonoverlapping historical observations.")
            last = total - rows_per_block
            offsets = [round(i * last / (blocks-1)) for i in range(blocks)]
            # Fixed window size with requested rows-per-block, preventing overlap.
            if any(b < a + rows_per_block for a, b in zip(offsets, offsets[1:])):
                raise SourceUnavailable("Requested windows are not disjoint.")
            fields = ','.join(['"ts"'] + ['"' + c + '"' for c in cols])
            for offset in offsets:
                records = con.execute(
                    f"SELECT {fields} FROM telemetry ORDER BY ts ASC, rowid ASC LIMIT ? OFFSET ?",
                    (rows_per_block, offset)).fetchall()
                current = []
                for values in records:
                    try:
                        t = float(values[0])
                    except (TypeError, ValueError, OverflowError):
                        continue
                    if not math.isfinite(t):
                        continue
                    point = {"ts": t}
                    for name, value in zip(cols, values[1:]):
                        try:
                            x = float(value)
                            point[name] = x if math.isfinite(x) else None
                        except (TypeError, ValueError, OverflowError):
                            point[name] = None
                    current.append(point)
                result.append(current)
    except sqlite3.Error as exc:
        raise SourceUnavailable("Cannot read historical telemetry safely.") from exc
    return result

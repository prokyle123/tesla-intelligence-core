"""Bounded, local, distributed-historical coverage audit.

Sample up to five nonoverlapping chronological blocks from across an existing
telemetry database. This is an observational DATA-QUALITY audit, not model
training, validation on future data, or federated communication.

Never load private ID, raw_json, coordinates, routes or exact trip records.
"""
from __future__ import annotations

from collections import Counter
import math
import sqlite3
from pathlib import Path
from urllib.parse import quote

from .coverage import REGIMES, coverage_report
from .source import ALLOWED_METRICS, SourceUnavailable

MAX_BLOCKS = 6
MAX_ROWS_PER_BLOCK = 3000
MAX_TOTAL_ROWS = 12000


def distributed_coverage(source_db: Path, selected_pairs: list[tuple[str, str]] = (),
                         blocks: int = 5, rows_per_block: int = 2400) -> dict:
    """Return count-only summaries across disjoint historical source windows.

    SQLite opens mode=ro/query_only and uses one snapshot; real source rows
    are held only in memory during each block and never put in the report.
    """
    if not 1 <= blocks <= MAX_BLOCKS:
        raise ValueError("Historical block count must be between 1 and 6.")
    if not 100 <= rows_per_block <= MAX_ROWS_PER_BLOCK:
        raise ValueError("Records per block must be between 100 and 3000.")
    if blocks * rows_per_block > MAX_TOTAL_ROWS:
        raise ValueError("Historical audit exceeds the 12,000-row safety budget.")
    if len(selected_pairs) > 40:
        raise ValueError("Too many pairs for local source coverage.")
    for feature, target in selected_pairs:
        if feature not in ALLOWED_METRICS or target not in ALLOWED_METRICS or feature == target:
            raise ValueError("Unapproved metric pair.")

    path = Path(source_db).expanduser().resolve()
    if not path.is_file():
        raise SourceUnavailable("Telemetry database is not available.")

    uri = "file:" + quote(str(path), safe="/") + "?mode=ro"
    segments = []
    regime_total = Counter()
    paired_totals: dict[tuple[str, str], Counter] = {
        (feature, target): Counter() for feature, target in selected_pairs
    }
    loaded = 0
    thinned = 0
    try:
        with sqlite3.connect(uri, uri=True, timeout=2.0) as con:
            con.execute("PRAGMA query_only=ON")
            con.execute("BEGIN")
            schema = {r[1] for r in con.execute("PRAGMA table_info(telemetry)")}
            if "ts" not in schema:
                raise SourceUnavailable("Telemetry schema is unavailable.")
            if "car_id" in schema:
                cars = con.execute("SELECT COUNT(DISTINCT car_id) FROM telemetry").fetchone()[0]
                if cars > 1:
                    raise SourceUnavailable("Multiple vehicles detected. Multi-car history audit is unavailable.")
            metrics = tuple(x for x in ALLOWED_METRICS if x in schema)
            if len(metrics) < 2:
                raise SourceUnavailable("Insufficient supported numeric telemetry.")
            total = int(con.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0])
            if total <= 0:
                raise SourceUnavailable("No telemetry records available.")
            count_per_block = min(rows_per_block, total)
            effective_blocks = min(blocks, max(1, total // count_per_block))
            last_offset = total - count_per_block
            offsets = [
                round(i * last_offset / (effective_blocks - 1))
                for i in range(effective_blocks)
            ] if effective_blocks > 1 else [last_offset]

            columns = ", ".join(['"ts"'] + ['"' + x + '"' for x in metrics])
            query = f"SELECT {columns} FROM telemetry ORDER BY ts ASC LIMIT ? OFFSET ?"
            for i, offset in enumerate(offsets):
                raw = con.execute(query, (count_per_block, offset)).fetchall()
                clean = []
                for record in raw:
                    try:
                        ts = float(record[0])
                        if not math.isfinite(ts):
                            continue
                    except (TypeError, ValueError, OverflowError):
                        continue
                    row = {"ts": ts}
                    for key, value in zip(metrics, record[1:]):
                        try:
                            v = float(value)
                            row[key] = v if math.isfinite(v) else None
                        except (TypeError, ValueError, OverflowError):
                            row[key] = None
                    clean.append(row)
                profile = coverage_report(clean, selected_pairs)
                loaded += len(clean)
                thinned += profile["thinned_rows"]
                regime_total.update(profile["raw_regime_counts"])
                for item in profile["candidate_pair_coverage"]:
                    paired_totals[(item["feature"], item["target"])].update(
                        item["paired_regime_counts"])
                segments.append({
                    "block": f"{i+1:02d}/{effective_blocks:02d}",
                    "chronology": "EARLIEST_TO_LATEST",
                    "raw_rows": profile["raw_rows"],
                    "thinned_rows": profile["thinned_rows"],
                    "raw_regime_counts": profile["raw_regime_counts"],
                    "thinned_regime_counts": profile["thinned_regime_counts"],
                    "pair_coverage": profile["candidate_pair_coverage"],
                    "warnings": profile["warnings"],
                })
    except sqlite3.Error as exc:
        raise SourceUnavailable("Historical telemetry could not be read safely.") from exc

    regime_counts = {k: int(regime_total[k]) for k in REGIMES}
    significant = [k for k in ("DRIVING", "CHARGING", "PARKED_OR_OTHER")
                   if regime_total[k] >= 100]
    alerts = []
    if regime_total["CHARGING"] > loaded * .6:
        alerts.append("CHARGING_DOMINANT_SAMPLE")
    if len(significant) < 2:
        alerts.append("FEWER_THAN_TWO_WELL_REPRESENTED_REGIMES")
    if regime_total["UNKNOWN"] or regime_total["CONFLICT"]:
        alerts.append("INCOMPLETE_OR_CONFLICTING_STATE_SIGNALS")
    if effective_blocks < blocks:
        alerts.append("INSUFFICIENT_HISTORY_FOR_REQUESTED_BLOCKS")

    return {
        "scope": "LOCAL_READ_ONLY_DISTRIBUTED_COVERAGE",
        "source_records_total": total,
        "records_inspected": loaded,
        "records_after_thinning": thinned,
        "historical_blocks": effective_blocks,
        "summary_regime_counts": regime_counts,
        "summary_pair_coverage": [
            {
                "feature": f, "target": t,
                "paired_regime_counts": {k:int(paired_totals[(f,t)][k]) for k in REGIMES},
            } for f,t in selected_pairs
        ],
        "blocks": segments,
        "warnings": alerts,
        "model_validated": False,
        "raw_values_included": False,
        "fleet_uploads": False,
        "eligible_for_production": False,
        "note": "Chronological sampling checks coverage only. A non-causal historical correlation cannot be promoted.",
    }

"""Local-only, read-only analysis of scored production GHOST temperature predictions.

Two NON-OVERLAPPING 7-day windows based on when outcomes were resolved.
This is observational monitoring, not proof of model drift, improvement,
causality, or independent prospective validation. It never uploads data.
"""
from __future__ import annotations

from contextlib import closing
import math
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import quote

DAYS = 7
SECONDS = 86400
MIN_COMPARISON_SCORES = 100
MAX_GROUPS = 16
REQUIRED = frozenset({
    "status", "resolved_at", "target_field", "abs_error",
    "model_name", "generation", "horizon_minutes"
})
_SAFE_MODEL = re.compile(r"^[a-zA-Z0-9_.:-]{1,80}$")
NOTES = [
    "Periods are two non-overlapping rolling seven-day outcome-resolution windows.",
    "Forecast errors are actual resolved GHOST observations, not training accuracy.",
    "Outcomes can share telemetry and are not statistically independent samples.",
    "Different model generations or operating conditions can change the result.",
    "These measurements do not prove causation, prospective validity, or eligibility for model promotion.",
]

def _empty(state: str) -> dict:
    return {
        "status": state,
        "scope": "LOCAL_GHOST_ONLY",
        "window_days": DAYS,
        "scored_target": "battery_temp_c",
        "metric": "absolute_temperature_error_f",
        "recent": {"samples": 0, "mae_f": None, "within_2f_percent": None},
        "previous": {"samples": 0, "mae_f": None, "within_2f_percent": None},
        "models": [],
        "models_omitted": 0,
        "limitations": NOTES,
        "production_changes": False,
        "network_uploads": False,
        "can_promote": False,
    }

def _metric(count: object, mae_c: object, hits: object) -> dict:
    n = int(count or 0)
    if not n:
        return {"samples": 0, "mae_f": None, "within_2f_percent": None}
    value = float(mae_c)
    if not math.isfinite(value) or value < 0:
        return {"samples": n, "mae_f": None, "within_2f_percent": None}
    h = int(hits or 0)
    return {"samples": n, "mae_f": round(value * 1.8, 2),
            "within_2f_percent": round(100 * h / n, 1)}

def _decision(current: dict, previous: dict, versions: set) -> dict:
    if min(current["samples"], previous["samples"]) < MIN_COMPARISON_SCORES:
        return {"state": "INSUFFICIENT_COMPARABLE_EVIDENCE",
                "mae_change_f": None, "accuracy_change_pp": None}
    if len(versions) != 1 or next(iter(versions)) is None:
        return {"state": "GENERATION_CHANGED_OR_MIXED",
                "mae_change_f": None, "accuracy_change_pp": None}
    if current["mae_f"] is None or previous["mae_f"] is None:
        return {"state": "ERROR_METRIC_UNAVAILABLE",
                "mae_change_f": None, "accuracy_change_pp": None}
    delta = round(current["mae_f"] - previous["mae_f"], 2)
    hits = round(current["within_2f_percent"] - previous["within_2f_percent"], 1)
    # Heuristic attention flag only. It is NOT a statistical drift verdict.
    state = "WORSENING_TO_INVESTIGATE" if delta >= 0.5 and hits <= -5 else (
        "IMPROVING_TO_INVESTIGATE" if delta <= -0.5 and hits >= 5 else
        "NO_STRONG_HEURISTIC_CHANGE")
    return {"state": state, "mae_change_f": delta, "accuracy_change_pp": hits}

def prediction_truth(source_db: Path, *, now: float | None = None) -> dict:
    out = _empty("SOURCE_UNAVAILABLE")
    when = time.time() if now is None else float(now)
    if not math.isfinite(when) or when <= 0:
        return out
    try:
        path = Path(source_db).expanduser().resolve(strict=True)
        if not path.is_file():
            return out
        uri = "file:" + quote(str(path), safe="/") + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as con:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA query_only=ON")
            cols = {row["name"] for row in con.execute(
                "PRAGMA table_info(prediction_audit)")}
            if not REQUIRED.issubset(cols):
                out["status"] = "SCHEMA_UNAVAILABLE"
                return out
            telemetry_cols = {row["name"] for row in con.execute(
                "PRAGMA table_info(telemetry)")}
            if "car_id" in telemetry_cols:
                vehicles = con.execute(
                    "SELECT COUNT(DISTINCT car_id) FROM telemetry"
                ).fetchone()[0]
                if vehicles > 1:
                    out["status"] = "MULTIVEHICLE_ISOLATION_REQUIRED"
                    return out
            boundary = when - DAYS * SECONDS
            start = when - 2 * DAYS * SECONDS
            # Directly aggregate in SQLite: do not read event-level rows into
            # Python or expose source rows, VINs, times, locations or IDs.
            criteria = """
                status='resolved' AND target_field='battery_temp_c'
                AND resolved_at >= ? AND resolved_at <= ?
                AND abs_error IS NOT NULL AND abs_error >= 0
                AND abs_error <= 30
            """
            buckets = con.execute(f"""
                SELECT CASE WHEN resolved_at >= ? THEN 1 ELSE 0 END recent,
                       COUNT(*) n, AVG(abs_error) mae_c,
                       SUM(CASE WHEN abs_error * 1.8 <= 2.0
                                THEN 1 ELSE 0 END) hits
                FROM prediction_audit
                WHERE {criteria}
                GROUP BY recent
            """, (boundary, start, when)).fetchall()
            models = con.execute(f"""
                SELECT model_name, horizon_minutes,
                       CASE WHEN resolved_at >= ? THEN 1 ELSE 0 END recent,
                       COUNT(*) n, AVG(abs_error) mae_c,
                       SUM(CASE WHEN abs_error * 1.8 <= 2.0
                                THEN 1 ELSE 0 END) hits,
                       MIN(generation) gmin, MAX(generation) gmax
                FROM prediction_audit
                WHERE {criteria}
                GROUP BY model_name, horizon_minutes, recent
            """, (boundary, start, when)).fetchall()
    except (OSError, ValueError, sqlite3.Error, OverflowError):
        return out

    out["status"] = "OK"
    for row in buckets:
        out["recent" if row["recent"] else "previous"] = _metric(
            row["n"], row["mae_c"], row["hits"])

    grouped = {}
    for row in models:
        name, horizon = row["model_name"], row["horizon_minutes"]
        if not isinstance(name, str) or not _SAFE_MODEL.fullmatch(name):
            continue
        if type(horizon) is not int or not 1 <= horizon <= 1440:
            continue
        key = (name, horizon)
        item = grouped.setdefault(key, {
            "model": name, "horizon_minutes": horizon,
            "recent": _metric(0, None, 0), "previous": _metric(0, None, 0),
            "_versions": {}
        })
        label = "recent" if row["recent"] else "previous"
        item[label] = _metric(row["n"], row["mae_c"], row["hits"])
        item["_versions"][label] = (row["gmin"], row["gmax"])

    for item in grouped.values():
        a = item.pop("_versions")
        versions = set()
        # Both windows must contain exactly one and the SAME generation.
        for label in ("recent", "previous"):
            low, high = a.get(label, (None, None))
            if low != high or low is None:
                versions.add(None)
            else:
                versions.add(low)
        item.update(_decision(item["recent"], item["previous"], versions))

    values = sorted(grouped.values(),
                    key=lambda v: (-(v["recent"]["samples"] +
                                     v["previous"]["samples"]),
                                   v["model"], v["horizon_minutes"]))
    out["models"] = values[:MAX_GROUPS]
    out["models_omitted"] = max(0, len(values) - MAX_GROUPS)
    if not buckets:
        out["status"] = "NO_SCORED_EVIDENCE"
    return out

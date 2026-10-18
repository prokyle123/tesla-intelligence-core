"""M11: episode-balanced, same-target thermal challenge, research only.

A forecast is matched to ONE inferred, source-time GHOST vehicle_events
interval, with deterministic last-started tie breaking. Aggregate first by
event and then weight events equally. No exact event times/IDs are returned.

Episodes are mutable/inferred engine outputs, not verified independent trips.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
import math
from pathlib import Path
import sqlite3
import time

from .frozen_challenger import (
    _load, _source_schema, _uri, MAX_POST_FREEZE,
)
from .prospective_truth_watch import MIN_SCORE, MIN_EVIDENCE_DAYS

MIN_EPISODES=5
MAX_EPISODE_GROUPS=6000
ALLOWED_EVENTS=("drive","charge","park","sleep","cold_soak","precondition")
NOTES=[
    "Episodes come from GHOST's inferred vehicle_events, not independent or externally verified trip labels.",
    "Forecasts are assigned to the latest-starting event covering their SOURCE prediction timestamp.",
    "Each event contributes one mean error regardless of its number of predictions; all three models use identical forecast targets.",
    "Overlapping events are resolved deterministically; later event-engine rewrites can change a retrospective summary.",
    "Coverage excludes unmatched or incomplete forecast/event records; do not treat missing context as zero-error predictions.",
    "Five inferred episodes, three UTC days and 100 matched forecasts are only research triage thresholds, not statistically independent samples.",
    "Challenger inputs are reconstructed from stored source telemetry, not a signed prediction-time feature snapshot.",
    "No scheduling, training, network transfers, model promotion or vehicle actions.",
]

def _result(status):
    return {
        "status":status,"scope":"LOCAL_GHOST_ONLY",
        "research":"EPISODE_BALANCED_THREE_WAY_CHALLENGE",
        "matched_forecasts":0,"unmatched_event_forecasts":0,
        "incomplete_matched_forecasts":0,
        "model_groups":[],"groups_omitted":0,
        "min_episodes":MIN_EPISODES,
        "min_evidence_days":MIN_EVIDENCE_DAYS,
        "min_forecasts":MIN_SCORE,
        "limitations":NOTES,
        "production_changes":False,"network_uploads":False,
        "can_promote":False,"automatic_execution":False,
    }

def _safe_metric(values):
    if not values:return None
    x=sum(values)/len(values)
    return round(x*1.8,2) if math.isfinite(x) and x>=0 else None

def episode_challenge(source_db,watch_file,challenger_file, *, now=None):
    out=_result("NOT_FROZEN")
    if not Path(challenger_file).is_file():
        return out
    source=Path(source_db).expanduser().resolve()
    candidate,watch=_load(source,Path(watch_file).expanduser().absolute(),challenger_file)
    wall=time.time() if now is None else float(now)
    if not math.isfinite(wall) or wall<candidate["created_at"]:
        raise ValueError("Evaluation timestamp precedes frozen challenger.")
    if not source.is_file():
        out["status"]="SOURCE_UNAVAILABLE"
        return out

    coefficients={c["horizon_minutes"]:c["alpha"] for c in candidate["candidates"]}
    locked=[
        (m["model"],m["generation"],m["horizon_minutes"],
         coefficients[m["horizon_minutes"]])
        for m in watch["models"] if m["horizon_minutes"] in coefficients
    ]
    if not locked:
        out["status"]="NO_LOCKED_MODELS_WITH_CANDIDATES"
        return out

    with closing(sqlite3.connect(_uri(source),uri=True,timeout=10)) as con:
        con.row_factory=sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        _source_schema(con)
        events={row["name"] for row in con.execute("PRAGMA table_info(vehicle_events)")}
        if not {"id","car_id","event_type","start_ts","end_ts"}<=events:
            out["status"]="EVENT_SCHEMA_UNAVAILABLE"
            return out
        criteria="""a.id>? AND a.predicted_at>? AND a.target_ts>?
                     AND a.resolved_at>=? AND a.resolved_at<=?
                     AND a.status='resolved' AND a.target_field='battery_temp_c'"""
        params=(candidate["max_forecast_id"],candidate["cutoff"],
                candidate["cutoff"],candidate["created_at"],wall)
        total=con.execute(
            "SELECT COUNT(*) FROM prediction_audit a WHERE "+criteria,params
        ).fetchone()[0]
        if total>MAX_POST_FREEZE:
            out["status"]="CAPACITY_REVIEW_REQUIRED"
            return out

        placeholders=" UNION ALL ".join("SELECT ? name,? gen,? horizon,? alpha"
                                       for _ in locked)
        bindings=tuple(v for row in locked for v in row)
        types=",".join("?" for _ in ALLOWED_EVENTS)
        # All aggregation is in SQLite; Python only reads one bounded row per
        # inferred event/model, never any GPS/route/timestamps or raw forecasts.
        sql=f"""
        WITH frozen(name,gen,horizon,alpha) AS ({placeholders}),
        source_rows AS (
          SELECT a.model_name name,a.generation gen,a.horizon_minutes horizon,
                 e.id event_id,e.event_type event_type,
                 CAST(e.start_ts/86400 AS INTEGER) event_day,
                 COUNT(*) forecast_count,
                 SUM(CASE WHEN t.battery_temp_c IS NOT NULL
                           AND t.outside_temp_c IS NOT NULL
                           AND a.actual_value IS NOT NULL
                           AND a.predicted_value IS NOT NULL
                          THEN 1 ELSE 0 END) complete,
                 AVG(CASE WHEN t.battery_temp_c IS NOT NULL
                           AND t.outside_temp_c IS NOT NULL
                           AND a.actual_value IS NOT NULL
                           AND a.predicted_value IS NOT NULL
                     THEN ABS(a.predicted_value-a.actual_value) END) production_error,
                 AVG(CASE WHEN t.battery_temp_c IS NOT NULL
                           AND t.outside_temp_c IS NOT NULL
                           AND a.actual_value IS NOT NULL
                           AND a.predicted_value IS NOT NULL
                     THEN ABS(t.battery_temp_c-a.actual_value) END) persistence_error,
                 AVG(CASE WHEN t.battery_temp_c IS NOT NULL
                           AND t.outside_temp_c IS NOT NULL
                           AND a.actual_value IS NOT NULL
                           AND a.predicted_value IS NOT NULL
                     THEN ABS(t.battery_temp_c+
                        f.alpha*(t.outside_temp_c-t.battery_temp_c)-
                        a.actual_value) END) challenger_error
          FROM prediction_audit a
          JOIN frozen f ON f.name=a.model_name AND f.gen=a.generation
                        AND f.horizon=a.horizon_minutes
          LEFT JOIN telemetry t ON t.id=a.source_telemetry_id
          LEFT JOIN vehicle_events e ON e.id=(
               SELECT ev.id FROM vehicle_events ev
               WHERE ev.car_id=t.car_id
                 AND ev.start_ts<=a.predicted_at
                 AND ev.end_ts>=a.predicted_at
                 AND ev.end_ts>ev.start_ts
                 AND ev.event_type IN ({types})
               ORDER BY ev.start_ts DESC,ev.id DESC LIMIT 1
          )
          WHERE {criteria}
          GROUP BY a.model_name,a.generation,a.horizon_minutes,e.id
        )
        SELECT * FROM source_rows LIMIT ?
        """
        rows=con.execute(sql,(*bindings,*ALLOWED_EVENTS,*params,
                              MAX_EPISODE_GROUPS+1)).fetchall()

    if len(rows)>MAX_EPISODE_GROUPS:
        out["status"]="EVENT_CAPACITY_REVIEW_REQUIRED"
        return out

    groups=defaultdict(lambda:{"forecast_count":0,"days":set(),
                                "prod":[],"base":[],"candidate":[]})
    for row in rows:
        count=int(row["forecast_count"] or 0)
        if row["event_id"] is None:
            out["unmatched_event_forecasts"]+=count
            continue
        valid=int(row["complete"] or 0)
        out["incomplete_matched_forecasts"]+=count-valid
        if not valid:
            continue
        errors=[row["production_error"],row["persistence_error"],
                row["challenger_error"]]
        if not all(x is not None and math.isfinite(float(x)) and
                   float(x)>=0 for x in errors):
            out["incomplete_matched_forecasts"]+=valid
            continue
        out["matched_forecasts"]+=valid
        key=(row["name"],row["gen"],row["horizon"],row["event_type"])
        g=groups[key]
        g["forecast_count"]+=valid
        g["days"].add(int(row["event_day"]))
        for bucket,value in zip(("prod","base","candidate"),errors):
            g[bucket].append(float(value))

    for key,g in groups.items():
        prod=_safe_metric(g["prod"])
        base=_safe_metric(g["base"])
        challenger=_safe_metric(g["candidate"])
        episodes=len(g["prod"])
        days=len(g["days"])
        enough=(episodes>=MIN_EPISODES and days>=MIN_EVIDENCE_DAYS
                and g["forecast_count"]>=MIN_SCORE)
        if not enough:
            assessment="INSUFFICIENT_EPISODE_EVIDENCE"
        elif challenger is None or prod is None or base is None:
            assessment="INVALID_AGGREGATE_ERROR"
        elif challenger+0.5<min(prod,base):
            assessment="CHALLENGER_BETTER_IN_INFERRED_EPISODES"
        elif challenger>=min(prod,base)+0.5:
            assessment="CHALLENGER_WORSE_THAN_REFERENCE"
        else:
            assessment="NO_CLEAR_EPISODE_BALANCED_ADVANTAGE"
        out["model_groups"].append({
            "model":key[0],"generation":key[1],"horizon_minutes":key[2],
            "event_type":key[3],
            "forecast_count":g["forecast_count"],
            "episodes":episodes,"evidence_days":days,
            "production_mae_f":prod,
            "persistence_mae_f":base,
            "challenger_mae_f":challenger,
            "challenger_advantage_vs_production_f":(
                round(prod-challenger,2) if prod is not None and challenger is not None else None),
            "challenger_advantage_vs_persistence_f":(
                round(base-challenger,2) if base is not None and challenger is not None else None),
            "assessment":assessment,
        })
    out["model_groups"].sort(
        key=lambda r:(-r["forecast_count"],r["model"],r["event_type"]))
    out["status"]=("EPISODE_EVIDENCE_AVAILABLE" if out["matched_forecasts"]
                   else "NO_MATCHED_EPISODE_EVIDENCE")
    return out

"""GENESIS M7: matched production-versus-persistence outcome challenge.

For each scored forecast with an actual temperature, compare its model
prediction against the pack temperature at the *same forecast source*.
Both forecasts are scored against the SAME recorded future actual.
Read-only, local-only, no training or model promotion.
"""
from __future__ import annotations

from contextlib import closing
import math
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import quote

DAY=86400
WINDOW_DAYS=7
MAX_RESULTS=24
MIN_PAIR_COUNT=100
SAFE_NAME=re.compile(r"^[a-zA-Z0-9_.:-]{1,80}$")

def _base(status):
    return {
        "status":status,"scope":"LOCAL_GHOST_ONLY",
        "research":"MATCHED_PRODUCTION_VS_PERSISTENCE",
        "groups":[],
        "eligible_pairs":0,
        "incomplete_pairs":0,
        "limitations":[
            "The persistence baseline predicts the starting battery temperature remains unchanged.",
            "Model and baseline use exactly the same future outcome and source telemetry for each scored pair.",
            "Results use resolution-time cohorts and are observational, not independently frozen prospective trials.",
            "Forecasts can be correlated and may share the same vehicle state and future observation.",
            "A historical win does not establish causal skill or qualify a production-model change."
        ],
        "production_changes":False,"network_uploads":False,
        "can_promote":False,"automatic_execution":False
    }

def _metric(row):
    n=int(row["n"] or 0)
    a,b=row["model_error_c"],row["persistence_error_c"]
    if not n or a is None or b is None or not math.isfinite(float(a)) or not math.isfinite(float(b)):
        return {"samples":n,"model_mae_f":None,"persistence_mae_f":None,
                "model_advantage_f":None,"model_win_percent":None}
    a=float(a)*1.8
    b=float(b)*1.8
    return {
        "samples":n,
        "model_mae_f":round(a,2),
        "persistence_mae_f":round(b,2),
        "model_advantage_f":round(b-a,2),
        "model_win_percent":round(100*int(row["wins"] or 0)/n,1)
    }

def paired_baseline(source_db: Path, *, now: float | None=None) -> dict:
    out=_base("SOURCE_UNAVAILABLE")
    when=time.time() if now is None else float(now)
    if not math.isfinite(when) or when<=0:return out
    try:
        path=Path(source_db).expanduser().resolve(strict=True)
        if not path.is_file():return out
        uri="file:"+quote(str(path),safe="/")+"?mode=ro"
        with closing(sqlite3.connect(uri,uri=True,timeout=5)) as con:
            con.row_factory=sqlite3.Row
            con.execute("PRAGMA query_only=ON")
            ap={r["name"] for r in con.execute("PRAGMA table_info(prediction_audit)")}
            tp={r["name"] for r in con.execute("PRAGMA table_info(telemetry)")}
            if not {"status","target_field","resolved_at","model_name",
                    "horizon_minutes","generation","predicted_value",
                    "actual_value","source_telemetry_id"}.issubset(ap) or not {
                    "id","car_id","battery_temp_c"}.issubset(tp):
                out["status"]="SCHEMA_UNAVAILABLE"
                return out
            if con.execute("SELECT COUNT(DISTINCT car_id) FROM telemetry").fetchone()[0]>1:
                out["status"]="MULTIVEHICLE_ISOLATION_REQUIRED"
                return out
            cutoff=when-2*WINDOW_DAYS*DAY
            split=when-WINDOW_DAYS*DAY
            where="""a.status='resolved' AND a.target_field='battery_temp_c'
                     AND a.resolved_at>=? AND a.resolved_at<=?"""
            coverage=con.execute(f"""
                SELECT COUNT(*) all_scored,
                    SUM(CASE WHEN t.battery_temp_c IS NULL
                                  OR a.actual_value IS NULL
                                  OR a.predicted_value IS NULL
                             THEN 0 ELSE 1 END) matched
                FROM prediction_audit a
                LEFT JOIN telemetry t ON t.id=a.source_telemetry_id
                WHERE {where}
            """,(cutoff,when)).fetchone()
            out["eligible_pairs"]=int(coverage["matched"] or 0)
            out["incomplete_pairs"]=int(coverage["all_scored"] or 0)-out["eligible_pairs"]
            rows=con.execute(f"""
                SELECT a.model_name name,a.horizon_minutes horizon,
                    a.generation generation,
                    CASE WHEN a.resolved_at>=? THEN 1 ELSE 0 END recent,
                    COUNT(*) n,
                    AVG(ABS(a.predicted_value-a.actual_value)) model_error_c,
                    AVG(ABS(t.battery_temp_c-a.actual_value)) persistence_error_c,
                    SUM(CASE WHEN ABS(a.predicted_value-a.actual_value)
                                  < ABS(t.battery_temp_c-a.actual_value)
                             THEN 1 ELSE 0 END) wins
                FROM prediction_audit a
                JOIN telemetry t ON t.id=a.source_telemetry_id
                WHERE {where}
                    AND a.predicted_value IS NOT NULL
                    AND a.actual_value IS NOT NULL
                    AND t.battery_temp_c IS NOT NULL
                GROUP BY name,horizon,generation,recent
            """,(split,cutoff,when)).fetchall()
    except (sqlite3.Error,OSError,ValueError,OverflowError,TypeError):
        return out

    grouped={}
    for row in rows:
        name,horizon,gen=row["name"],row["horizon"],row["generation"]
        if not isinstance(name,str) or not SAFE_NAME.fullmatch(name):continue
        if type(horizon)!=int or not 1<=horizon<=1440:continue
        if type(gen)!=int or not 0<=gen<=1000000:continue
        key=name,horizon,gen
        item=grouped.setdefault(key,{
            "model":name,"horizon_minutes":horizon,"generation":gen,
            "recent":None,"previous":None
        })
        item["recent" if row["recent"] else "previous"]=_metric(row)
    for item in grouped.values():
        # Keep the same response schema even when a generation has zero
        # observations in one week. Missing is not a zero-error score.
        empty=_metric({"n":0,"model_error_c":None,"persistence_error_c":None,"wins":0})
        current=item["recent"] or empty.copy()
        prior=item["previous"] or empty.copy()
        item["recent"]=current
        item["previous"]=prior
        n=current["samples"]
        if n<MIN_PAIR_COUNT or current["model_advantage_f"] is None:
            decision="INSUFFICIENT_PAIRED_EVIDENCE"
        elif current["model_advantage_f"]<=-0.5:
            decision="PERSISTENCE_BETTER_REVIEW"
        elif current["model_advantage_f"]>=0.5:
            decision="MODEL_BETTER_HISTORICALLY"
        else:
            decision="NO_CLEAR_PAIRED_ADVANTAGE"
        item["assessment"]=decision
    values=sorted(grouped.values(),
        key=lambda item:(-item["recent"]["samples"],item["model"],item["horizon_minutes"],-item["generation"]))
    out["groups"]=values[:MAX_RESULTS]
    out["groups_omitted"]=max(0,len(values)-MAX_RESULTS)
    out["status"]="OK" if out["eligible_pairs"] else "NO_COMPLETE_PAIRS"
    return out

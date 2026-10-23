"""GENESIS M6: read-only context and research priorities for production truth.

Context is observed at the *forecast source* sample, not throughout the
forecast horizon. Aggregate-only: never returns sample times, routes, VINs,
car IDs, row IDs, model weights, or individual readings. No vehicle commands.
"""
from __future__ import annotations

from contextlib import closing
import math
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import quote

DAY = 86400
MAX_GROUPS = 40
MIN_GROUP_SCORES = 100
MODEL_SAFE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
WINDOW_DAYS = 7
NOTES = [
    "Groups use telemetry captured when each forecast was made, not conditions over its forecast horizon.",
    "All percentages describe resolved predictions, not independent driving or charging sessions.",
    "Ambient and vehicle-state dimensions reuse predictions and must never be summed together.",
    "Poor performance in a condition is association, not evidence that condition caused error.",
    "Research suggestions are fixed, read-only diagnostic plans; no automatic experiments or model promotion.",
]
DIMS = ("ambient", "vehicle_state", "heater")
SUGGESTIONS = {
    "ambient": "Check whether source ambient temperature and pack-minus-ambient offset explain this model's error; match on horizon and model generation.",
    "vehicle_state": "Verify forecast-source state and compare matched driving/charging/idle periods; inspect regime changes during the forecast horizon.",
    "heater": "Check sensor coverage and reported heater activation; do not interpret a missing heater flag as OFF.",
}

def _base(status: str):
    return {
        "status": status, "scope": "LOCAL_GHOST_ONLY",
        "windows": {"recent_days": WINDOW_DAYS, "previous_days": WINDOW_DAYS},
        "dimensions": [], "priorities": [],
        "matched_source_predictions": 0, "unmatched_source_predictions": 0,
        "limitations": NOTES,
        "network_uploads": False, "production_changes": False,
        "can_promote": False, "automatic_execution": False,
    }

def _cols(con, name: str):
    return {r["name"] for r in con.execute(f"PRAGMA table_info({name})")}

def _dim_expr(dimension: str, cols: set[str]):
    if dimension == "ambient" and "outside_temp_c" in cols:
        return """CASE
         WHEN t.id IS NULL OR t.outside_temp_c IS NULL THEN 'UNKNOWN'
         WHEN t.outside_temp_c <= 0 THEN 'AT_OR_BELOW_32F'
         WHEN t.outside_temp_c <= 10 THEN 'ABOVE_32_TO_50F'
         WHEN t.outside_temp_c <= 20 THEN 'ABOVE_50_TO_68F'
         ELSE 'ABOVE_68F' END"""
    if dimension == "vehicle_state" and "state" in cols:
        # Descriptive source telemetry only. Not inferred trip/charge truth.
        return """CASE
         WHEN t.id IS NULL OR t.state IS NULL THEN 'UNKNOWN'
         WHEN LOWER(t.state)='driving' THEN 'REPORTED_DRIVING'
         WHEN LOWER(t.state)='charging' THEN 'REPORTED_CHARGING'
         WHEN LOWER(t.state)='asleep' THEN 'REPORTED_ASLEEP'
         WHEN LOWER(t.state) IN ('online','awake') THEN 'REPORTED_ONLINE'
         ELSE 'OTHER_REPORTED_STATE' END"""
    if dimension == "heater" and "battery_heater_on" in cols:
        return """CASE
         WHEN t.id IS NULL OR t.battery_heater_on IS NULL THEN 'UNKNOWN'
         WHEN t.battery_heater_on=1 THEN 'REPORTED_ON'
         WHEN t.battery_heater_on=0 THEN 'REPORTED_OFF'
         ELSE 'UNKNOWN' END"""
    return None

def _report_row(row) -> dict:
    count=int(row["n"] or 0)
    avg=row["mae_c"]
    signed=row["signed_mean_c"]
    sn=int(row["signed_n"] or 0)
    return {
        "samples": count,
        "mae_f": round(1.8 * float(avg),2) if avg is not None and math.isfinite(float(avg)) else None,
        "within_2f_percent": round(100*int(row["hits"] or 0)/count,1) if count else None,
        "above_5f_percent": round(100*int(row["severe"] or 0)/count,1) if count else None,
        "signed_samples": sn,
        "signed_bias_f": round(1.8 * float(signed),2) if sn and signed is not None and math.isfinite(float(signed)) else None,
    }

def _status(recent, previous, generations) -> str:
    if recent["samples"] < MIN_GROUP_SCORES or previous["samples"] < MIN_GROUP_SCORES:
        return "INSUFFICIENT_COMPARABLE_EVIDENCE"
    if len(generations)!=1 or None in generations:
        return "GENERATION_CHANGED_OR_MIXED"
    if recent["mae_f"] is None or previous["mae_f"] is None:
        return "ERROR_UNAVAILABLE"
    delta=recent["mae_f"] - previous["mae_f"]
    hits=recent["within_2f_percent"] - previous["within_2f_percent"]
    if delta >= .5 and hits <= -5: return "WORSENING_TO_INVESTIGATE"
    if delta <= -.5 and hits >= 5: return "IMPROVING_TO_INVESTIGATE"
    return "NO_STRONG_HEURISTIC_CHANGE"

def thermal_context(source_db: Path, *, now: float | None=None) -> dict:
    result=_base("SOURCE_UNAVAILABLE")
    when=time.time() if now is None else float(now)
    if not math.isfinite(when) or when<=0: return result
    try:
        path=Path(source_db).expanduser().resolve(strict=True)
        if not path.is_file(): return result
        uri="file:"+quote(str(path),safe="/")+"?mode=ro"
        with closing(sqlite3.connect(uri,uri=True,timeout=5)) as con:
            con.row_factory=sqlite3.Row
            con.execute("PRAGMA query_only=ON")
            prediction_cols=_cols(con,"prediction_audit")
            telemetry_cols=_cols(con,"telemetry")
            if not {"id","car_id"}.issubset(telemetry_cols) or not {
                "status","target_field","resolved_at","model_name",
                "generation","horizon_minutes","source_telemetry_id","abs_error"
            }.issubset(prediction_cols):
                result["status"]="SCHEMA_UNAVAILABLE"
                return result
            if con.execute("SELECT COUNT(DISTINCT car_id) FROM telemetry").fetchone()[0] > 1:
                result["status"]="MULTIVEHICLE_ISOLATION_REQUIRED"
                return result
            start=when-2*WINDOW_DAYS*DAY
            split=when-WINDOW_DAYS*DAY
            cond="""a.status='resolved' AND a.target_field='battery_temp_c'
                AND a.resolved_at >= ? AND a.resolved_at <= ?
                AND a.abs_error IS NOT NULL AND a.abs_error >= 0"""
            coverage=con.execute(f"""
                SELECT COUNT(*) n,
                    SUM(CASE WHEN t.id IS NULL THEN 1 ELSE 0 END) missing
                FROM prediction_audit a LEFT JOIN telemetry t
                     ON t.id=a.source_telemetry_id
                WHERE {cond}
            """,(start,when)).fetchone()
            result["matched_source_predictions"]=int(coverage["n"] or 0)-int(coverage["missing"] or 0)
            result["unmatched_source_predictions"]=int(coverage["missing"] or 0)
            signed=("""
                SUM(CASE WHEN a.signed_error IS NOT NULL THEN 1 ELSE 0 END) signed_n,
                AVG(a.signed_error) signed_mean_c
            """ if "signed_error" in prediction_cols else
                "0 signed_n, NULL signed_mean_c")
            data=[]
            for dimension in DIMS:
                expression=_dim_expr(dimension,telemetry_cols)
                if expression is None: continue
                rows=con.execute(f"""
                    SELECT a.model_name model, a.horizon_minutes horizon,
                        CASE WHEN a.resolved_at >= ? THEN 1 ELSE 0 END recent,
                        {expression} grp, COUNT(*) n,
                        AVG(a.abs_error) mae_c,
                        SUM(CASE WHEN a.abs_error*1.8<=2 THEN 1 ELSE 0 END) hits,
                        SUM(CASE WHEN a.abs_error*1.8>5 THEN 1 ELSE 0 END) severe,
                        {signed},
                        MIN(a.generation) min_gen, MAX(a.generation) max_gen
                    FROM prediction_audit a LEFT JOIN telemetry t
                         ON t.id=a.source_telemetry_id
                    WHERE {cond}
                    GROUP BY model, horizon, recent, grp
                """,(split,start,when)).fetchall()
                pairs={}
                for row in rows:
                    name,horizon=row["model"],row["horizon"]
                    if not isinstance(name,str) or not MODEL_SAFE.fullmatch(name): continue
                    if type(horizon)!=int or horizon<1 or horizon>1440: continue
                    key=(name,horizon,row["grp"])
                    item=pairs.setdefault(key,{
                        "dimension":dimension,"group":row["grp"],
                        "model":name,"horizon_minutes":horizon,
                        "recent":{"samples":0,"mae_f":None,"within_2f_percent":None},
                        "previous":{"samples":0,"mae_f":None,"within_2f_percent":None},
                        "_gens":{},
                    })
                    period="recent" if row["recent"] else "previous"
                    item[period]=_report_row(row)
                    item["_gens"][period]=(row["min_gen"],row["max_gen"])
                for row in pairs.values():
                    gens=set()
                    for period in ("recent","previous"):
                        a,b=row["_gens"].get(period,(None,None))
                        gens.add(a if a is not None and a==b else None)
                    del row["_gens"]
                    row["assessment"]=_status(row["recent"],row["previous"],gens)
                    row["delta_mae_f"]=(round(row["recent"]["mae_f"]-row["previous"]["mae_f"],2)
                        if row["assessment"] not in {
                            "INSUFFICIENT_COMPARABLE_EVIDENCE",
                            "GENERATION_CHANGED_OR_MIXED","ERROR_UNAVAILABLE"}
                        else None)
                    data.append(row)
    except (OSError,ValueError,sqlite3.Error,OverflowError,TypeError):
        return result

    # Limit response size. Prioritize verified worsening segments over noisy
    # single-digit samples; preserve separate generation safety status.
    data.sort(key=lambda x:(0 if x["assessment"]=="WORSENING_TO_INVESTIGATE" else 1,
                            -(x["recent"]["samples"]+x["previous"]["samples"]),
                            x["dimension"],x["model"],x["group"]))
    result["dimensions"]=data[:MAX_GROUPS]
    priorities=[]
    for item in data:
        if item["assessment"]!="WORSENING_TO_INVESTIGATE": continue
        if len(priorities)>=5:break
        priorities.append({
            "kind":"REVIEW_MODEL_CONTEXT",
            "state":"PROPOSED_NOT_EXECUTED",
            "model":item["model"],
            "horizon_minutes":item["horizon_minutes"],
            "dimension":item["dimension"],
            "group":item["group"],
            "samples_recent":item["recent"]["samples"],
            "samples_previous":item["previous"]["samples"],
            "mae_change_f":item["delta_mae_f"],
            "question":SUGGESTIONS[item["dimension"]],
            "read_only":True,
            "requires_operator_review":True,
        })
    result["priorities"]=priorities
    result["groups_omitted"]=max(0,len(data)-MAX_GROUPS)
    result["status"]="OK" if result["matched_source_predictions"] or result["unmatched_source_predictions"] else "NO_SCORED_EVIDENCE"
    return result

"""M8 manual prospective production truth-watch, separate from M3 candidate shadow.

Freeze a watermark of already-existing GHOST forecasts. Future inspections
score ONLY later-created predictions with later forecast/target timestamps,
comparing incumbent forecasts with same-event persistence. Neither candidate
model training nor verified arrival-time provenance is claimed. No timers.
"""
from __future__ import annotations
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import quote

VERSION="GENESIS_PROSPECTIVE_TRUTH_1"
MAX_POST_FREEZE=200000
MAX_MODELS=20
MIN_SCORE=100
MIN_EVIDENCE_DAYS=3  # Diversity check only; forecast rows remain correlated.
_NAME=re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
REQ_AUDIT={"id","predicted_at","target_ts","resolved_at","status",
           "target_field","model_name","generation","horizon_minutes",
           "predicted_value","actual_value","source_telemetry_id"}
REQ_TELEM={"id","car_id","battery_temp_c"}
CAVEATS=[
    "Freeze is manual and irreversible for this ledger; a new trial needs a new private file.",
    "Both the production forecast and persistence use the same scored future temperature.",
    "Post-freeze is defined using forecast record IDs and source timestamps, not verified ingestion times.",
    "Existing GHOST models are observed as a diagnostic: no challenger is trained or promoted here.",
    "Overlapping predictions can share the same outcome and are not independent sessions.",
    "Assessment requires coverage across at least three different UTC resolution days; days do not guarantee independent episodes.",
    "Model name/horizon/generation is locked; artifact-byte immutability is not yet verified.",
]

def _uri(p):
    return "file:"+quote(str(p.resolve()),safe="/")+"?mode=ro"

def _digest(p):
    return hashlib.sha256(str(p.resolve()).encode()).hexdigest()

def _source(con):
    a={r[1] for r in con.execute("PRAGMA table_info(prediction_audit)")}
    t={r[1] for r in con.execute("PRAGMA table_info(telemetry)")}
    if not (REQ_AUDIT<=a and REQ_TELEM<=t):
        raise ValueError("Required GHOST scored outcome fields are unavailable.")
    if con.execute("SELECT COUNT(DISTINCT car_id) FROM telemetry").fetchone()[0]>1:
        raise ValueError("Multiple vehicles need separate GENESIS research ledgers.")

def _path(p: Path,source: Path, *, existing: bool):
    p=Path(p).expanduser().absolute()
    src=Path(source).expanduser().resolve()
    if p.is_symlink() or p.resolve()==src or p.suffix!=".json":
        raise ValueError("Private JSON ledger must not be a symlink or production DB.")
    if existing:
        if not p.is_file() or p.stat().st_mode & 0o077:
            raise ValueError("No readable private frozen watch exists.")
    else:
        if p.exists():
            raise ValueError("Watch already frozen. Refusing overwrite.")
        if not p.parent.is_dir() or p.parent.is_symlink() or p.parent.stat().st_mode & 0o077:
            raise ValueError("Create a private 0700 state directory first.")
    return p

def freeze_watch(source_db: Path,state_file: Path, *, now: float|None=None):
    source=Path(source_db).expanduser().resolve(strict=True)
    state=_path(state_file,source,existing=False)
    wall=time.time() if now is None else float(now)
    if not math.isfinite(wall) or wall<=0:raise ValueError("Invalid freeze time.")
    with closing(sqlite3.connect(_uri(source),uri=True,timeout=5)) as con:
        con.execute("PRAGMA query_only=ON")
        _source(con)
        high=con.execute("SELECT COALESCE(MAX(id),0),COALESCE(MAX(predicted_at),0) FROM prediction_audit").fetchone()
        # One version per model/horizon, locked before any future evidence.
        observed=con.execute("""
            SELECT model_name,horizon_minutes,MAX(generation) gen
            FROM prediction_audit
            WHERE target_field='battery_temp_c'
            GROUP BY model_name,horizon_minutes
            ORDER BY model_name,horizon_minutes
        """).fetchall()
    models=[]
    for name,horizon,gen in observed:
        if isinstance(name,str) and _NAME.fullmatch(name) and type(horizon)==int and 1<=horizon<=1440 and type(gen)==int and 0<=gen<=1000000:
            models.append({"model":name,"horizon_minutes":horizon,"generation":gen})
    if not models or len(models)>MAX_MODELS:
        raise ValueError("No valid bounded set of model versions to freeze.")
    private={
        "version":VERSION,
        "source_digest":_digest(source),
        "created_at":wall,
        "cutoff":max(wall,float(high[1] or 0)),
        "max_forecast_id":int(high[0]),
        "models":models
    }
    fd=os.open(state,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(private,f,sort_keys=True,separators=(",",":"),allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        state.unlink(missing_ok=True)
        raise
    return {"status":"FROZEN_AWAITING_NEW_SCORES","scope":"LOCAL_GHOST_ONLY",
            "frozen_models":models,"can_promote":False,
            "production_changes":False,"network_uploads":False,
            "automatic_execution":False}

def _load(source,state):
    s=_path(state,source,existing=True)
    if s.stat().st_size>8192:raise ValueError("Unexpected watch ledger size.")
    data=json.loads(s.read_text(encoding="utf-8"))
    if not isinstance(data,dict) or set(data)!={"version","source_digest","created_at","cutoff","max_forecast_id","models"}:
        raise ValueError("Invalid watch ledger schema.")
    if data["version"]!=VERSION or data["source_digest"]!=_digest(source):
        raise ValueError("Watch ledger belongs to another code/source version.")
    if (type(data["max_forecast_id"])!=int or data["max_forecast_id"]<0
        or any(not isinstance(data[k],(float,int)) or not math.isfinite(data[k]) or data[k]<=0 for k in ("created_at","cutoff"))):
        raise ValueError("Invalid frozen forecast watermark.")
    models=data["models"]
    if not isinstance(models,list) or not 1<=len(models)<=MAX_MODELS:
        raise ValueError("Invalid model versions.")
    for row in models:
        if (not isinstance(row,dict) or set(row)!={"model","horizon_minutes","generation"}
            or not isinstance(row["model"],str) or not _NAME.fullmatch(row["model"])
            or type(row["horizon_minutes"])!=int or not 1<=row["horizon_minutes"]<=1440
            or type(row["generation"])!=int or not 0<=row["generation"]<=1000000):
            raise ValueError("Invalid model version entry.")
    return data

def _empty(status):
    return {"status":status,"scope":"LOCAL_GHOST_ONLY","research":VERSION,
            "eligible_pairs":0,"incomplete_pairs":0,"new_generation_pairs":0,
            "min_evidence_days":MIN_EVIDENCE_DAYS,
            "models":[],"limitations":CAVEATS,"production_changes":False,
            "network_uploads":False,"can_promote":False,
            "automatic_execution":False}

def check_watch(source_db: Path,state_file: Path, *,now: float|None=None):
    source=Path(source_db).expanduser().resolve()
    out=_empty("NOT_FROZEN")
    if not Path(state_file).is_file():return out
    frozen=_load(source,state_file)
    wall=time.time() if now is None else float(now)
    if not math.isfinite(wall) or wall<frozen["created_at"]:
        raise ValueError("Check must run after freeze.")
    if not source.is_file():return _empty("SOURCE_UNAVAILABLE")
    with closing(sqlite3.connect(_uri(source),uri=True,timeout=5)) as con:
        con.row_factory=sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        _source(con)
        conditions="""a.id > ? AND a.predicted_at > ? AND a.target_ts > ?
            AND a.resolved_at >= ? AND a.resolved_at <= ?
            AND a.status='resolved' AND a.target_field='battery_temp_c'"""
        args=(frozen["max_forecast_id"],frozen["cutoff"],
              frozen["cutoff"],frozen["created_at"],wall)
        # Protect Pi resources: refuse unbounded scans rather than truncate.
        total=con.execute("SELECT COUNT(*) FROM prediction_audit a WHERE "+conditions,args).fetchone()[0]
        if total>MAX_POST_FREEZE:
            out["status"]="CAPACITY_REVIEW_REQUIRED"
            return out
        rows=con.execute(f"""
            SELECT a.model_name name,a.horizon_minutes horizon,
                   a.generation gen,COUNT(*) scored,
                   COUNT(DISTINCT CASE WHEN t.battery_temp_c IS NOT NULL
                        AND a.actual_value IS NOT NULL AND a.predicted_value IS NOT NULL
                        THEN CAST(a.resolved_at / 86400 AS INTEGER) END) evidence_days,
                   SUM(CASE WHEN t.battery_temp_c IS NULL OR
                          a.actual_value IS NULL OR a.predicted_value IS NULL
                       THEN 0 ELSE 1 END) complete,
                   AVG(CASE WHEN t.battery_temp_c IS NOT NULL AND
                       a.actual_value IS NOT NULL AND a.predicted_value IS NOT NULL
                       THEN ABS(a.predicted_value-a.actual_value) END) model_mae_c,
                   AVG(CASE WHEN t.battery_temp_c IS NOT NULL AND
                       a.actual_value IS NOT NULL AND a.predicted_value IS NOT NULL
                       THEN ABS(t.battery_temp_c-a.actual_value) END) persist_mae_c,
                   SUM(CASE WHEN t.battery_temp_c IS NOT NULL AND
                       a.actual_value IS NOT NULL AND a.predicted_value IS NOT NULL
                       AND ABS(a.predicted_value-a.actual_value) <
                           ABS(t.battery_temp_c-a.actual_value)
                       THEN 1 ELSE 0 END) wins
            FROM prediction_audit a LEFT JOIN telemetry t ON t.id=a.source_telemetry_id
            WHERE {conditions}
            GROUP BY a.model_name,a.horizon_minutes,a.generation
        """,args).fetchall()
    by={(m["model"],m["horizon_minutes"],m["generation"]):m for m in frozen["models"]}
    data={}
    unmatched=0
    incomplete=0
    completed=0
    for row in rows:
        key=(row["name"],row["horizon"],row["gen"])
        count=int(row["scored"] or 0)
        if key not in by:
            unmatched+=count
            continue
        n=int(row["complete"] or 0)
        incomplete+=count-n
        completed+=n
        days=int(row["evidence_days"] or 0)
        if n:
            a=float(row["model_mae_c"])*1.8
            b=float(row["persist_mae_c"])*1.8
            if not math.isfinite(a) or not math.isfinite(b):
                incomplete+=n
                completed-=n
                continue
            a,b=round(a,2),round(b,2)
            advantage=round(b-a,2)
        else:a=b=advantage=None
        data[key]={"model":key[0],"horizon_minutes":key[1],"generation":key[2],
                   "samples":n,"evidence_days":days,
                   "model_mae_f":a,"persistence_mae_f":b,
                   "model_advantage_f":advantage,
                   "model_win_percent":round(100*int(row["wins"] or 0)/n,1) if n else None,
                   "assessment":("INSUFFICIENT_FUTURE_EVIDENCE" if n<MIN_SCORE else
                     "INSUFFICIENT_TEMPORAL_COVERAGE" if days<MIN_EVIDENCE_DAYS else
                     "PERSISTENCE_BETTER_REVIEW" if advantage<=-.5 else
                     "MODEL_BETTER_ON_POST_FREEZE_SCORES" if advantage>=.5 else
                     "NO_CLEAR_ADVANTAGE")}
    out["eligible_pairs"]=completed
    out["incomplete_pairs"]=incomplete
    out["new_generation_pairs"]=unmatched
    out["models"]=[data[k] if k in data else
        {"model":k[0],"horizon_minutes":k[1],"generation":k[2],
         "samples":0,"evidence_days":0,"model_mae_f":None,"persistence_mae_f":None,
         "model_advantage_f":None,"model_win_percent":None,
         "assessment":"AWAITING_FUTURE_EVIDENCE"} for k in by]
    out["status"]="POST_FREEZE_EVIDENCE_AVAILABLE" if completed else "AWAITING_FUTURE_EVIDENCE"
    return out

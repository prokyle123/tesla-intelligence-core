"""M10 research-only, freeze-once physics challenger vs production GHOST.

The deterministic model T+h = T0 + alpha_h*(outside0-T0) is fitted ONLY from
resolved historical outcomes preceding the explicit candidate freeze. It is
evaluated later against production and persistence on the SAME resolved GHOST
events. Prediction reconstructions use stored forecast-source sensors; source
immutability/ingestion chronology are not proven. No timers or promotion.
"""
from __future__ import annotations
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time

from .prospective_truth_watch import (
    _load as _watch_load, _uri, _source, _digest, MAX_POST_FREEZE,
    MIN_SCORE, MIN_EVIDENCE_DAYS,
)

VERSION="GENESIS_THERMAL_CHALLENGER_1"
MAX_CANDIDATES=10
MAX_TRAINING_ROWS=150000
DAY=86400
TRAIN_DAYS=21
HOLDOUT_DAYS=7
MIN_TRAIN=120
MIN_VALID=60
REQUIRED_TELEMETRY={"id","car_id","battery_temp_c","outside_temp_c"}
REQUIRED_AUDIT={"id","predicted_at","target_ts","resolved_at","status",
                "target_field","model_name","horizon_minutes","generation",
                "source_telemetry_id","predicted_value","actual_value"}
NOTES=[
    "Frozen candidate coefficients are fitted using only pre-freeze resolved target observations.",
    "Candidate, incumbent and persistence use the SAME future target and stored forecast-source sample.",
    "Candidate values are reconstructed at scoring time from stored source telemetry; source data immutability is not verified.",
    "The fixed candidate uses source ambient and pack temperature only; no future sensor input or vehicle control.",
    "Forecast rows may be heavily correlated; 3 UTC days are NOT 3 independent trips.",
    "Historic model/holdout choices were explored, so validation is not an untouched independent trial.",
    "No artifact signature, ingestion-time attestations, autonomous scheduling, promotion or Hive transfer.",
]
SCHEMA_KEYS={"version","source_digest","watch_digest","created_at","cutoff",
             "max_forecast_id","candidates","artifact_sha256"}

def _path(p, *, exists):
    p=Path(p).expanduser().absolute()
    if p.suffix!=".json" or p.is_symlink():
        raise ValueError("Challenger file must be an ordinary .json file.")
    if exists:
        if not p.is_file() or p.stat().st_mode & 0o077 or p.stat().st_size>8192:
            raise ValueError("Challenger freeze must be an existing private bounded file.")
    else:
        if p.exists() or not p.parent.is_dir() or p.parent.is_symlink() or p.parent.stat().st_mode & 0o077:
            raise ValueError("Challenger freeze requires new file under private 0700 folder.")
    return p

def _hash_bytes(p):
    if p.is_symlink() or not p.is_file() or p.stat().st_mode & 0o077 or p.stat().st_size>8192:
        raise ValueError("Existing prospective truth watch is not a private bounded file.")
    return hashlib.sha256(p.read_bytes()).hexdigest()

def _canon(data):
    return json.dumps(data,sort_keys=True,separators=(",",":"),allow_nan=False)

def _source_schema(con):
    _source(con)
    t={r[1] for r in con.execute("PRAGMA table_info(telemetry)")}
    a={r[1] for r in con.execute("PRAGMA table_info(prediction_audit)")}
    if not REQUIRED_TELEMETRY<=t or not REQUIRED_AUDIT<=a:
        raise ValueError("Temperature and source audit fields are required.")

def _history_stats(con, horizon, begin, end, *, alpha=None):
    # Source-available and target-recorded comparisons are bounded by resolved
    # time; complete targets must exist before freeze. Never load individual
    # rows, route data, car IDs, or exact timestamps into the program.
    criteria="""a.status='resolved' AND a.target_field='battery_temp_c'
      AND a.horizon_minutes=? AND a.resolved_at>=? AND a.resolved_at<?
      AND a.predicted_at<=? AND a.target_ts<=?
      AND a.actual_value IS NOT NULL AND t.battery_temp_c IS NOT NULL
      AND t.outside_temp_c IS NOT NULL"""
    args=(horizon,begin,end,end,end)
    x="(t.outside_temp_c-t.battery_temp_c)"
    y="(a.actual_value-t.battery_temp_c)"
    if alpha is None:
        query=f"""SELECT COUNT(*) n,COUNT(DISTINCT CAST(a.resolved_at/86400 AS INTEGER)) days,
            SUM({x}*{y}) numer,SUM({x}*{x}) denom
            FROM prediction_audit a JOIN telemetry t ON t.id=a.source_telemetry_id
            WHERE {criteria}"""
    else:
        query=f"""SELECT COUNT(*) n,COUNT(DISTINCT CAST(a.resolved_at/86400 AS INTEGER)) days,
            AVG(ABS(({x}*?)-{y})) challenger_c,
            AVG(ABS({y})) persistence_c
            FROM prediction_audit a JOIN telemetry t ON t.id=a.source_telemetry_id
            WHERE {criteria}"""
        args=(float(alpha),*args)
    return con.execute(query,args).fetchone()

def freeze_challenger(source_db,watch_file,challenger_file, *, now=None):
    source=Path(source_db).expanduser().resolve(strict=True)
    watch=Path(watch_file).expanduser().absolute()
    target=_path(challenger_file,exists=False)
    if target.resolve() in {source,watch.resolve()}:
        raise ValueError("Challenger artifact must be separate from original source/watch.")
    parent=_watch_load(source,watch)
    watch_digest=_hash_bytes(watch)
    wall=time.time() if now is None else float(now)
    if not math.isfinite(wall) or wall<parent["created_at"]:
        raise ValueError("Challenger freeze must be after the original watch.")
    candidates=[]
    with closing(sqlite3.connect(_uri(source),uri=True,timeout=10)) as con:
        con.row_factory=sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        _source_schema(con)
        high=con.execute("SELECT COALESCE(MAX(id),0),COALESCE(MAX(predicted_at),0) FROM prediction_audit").fetchone()
        earliest=wall-TRAIN_DAYS*DAY
        holdout=wall-HOLDOUT_DAYS*DAY
        rows=con.execute("""SELECT COUNT(*) FROM prediction_audit
          WHERE status='resolved' AND target_field='battery_temp_c'
            AND resolved_at>=? AND resolved_at<=?""",(earliest,wall)).fetchone()[0]
        if rows>MAX_TRAINING_ROWS:
            raise ValueError("Historical sample volume above bounded training budget.")
        horizons=sorted({m["horizon_minutes"] for m in parent["models"]})
        if len(horizons)>MAX_CANDIDATES:
            raise ValueError("Research exceeds maximum distinct forecast horizons.")
        for horizon in horizons:
            training=_history_stats(con,horizon,earliest,holdout)
            count=int(training["n"] or 0)
            if count<MIN_TRAIN or float(training["denom"] or 0)<1e-8:
                continue
            alpha=max(0.,min(1.,float(training["numer"])/float(training["denom"])))
            alpha=round(alpha,5)
            validation=_history_stats(con,horizon,holdout,wall,alpha=alpha)
            n=int(validation["n"] or 0)
            if n<MIN_VALID or int(validation["days"] or 0)<3:
                continue
            candidate_f=float(validation["challenger_c"])*1.8
            persist_f=float(validation["persistence_c"])*1.8
            if not all(map(math.isfinite,(alpha,candidate_f,persist_f))):
                continue
            candidates.append({
                "horizon_minutes":horizon,"alpha":alpha,
                "training_samples":count,
                "training_days":int(training["days"] or 0),
                "validation_samples":n,
                "validation_days":int(validation["days"] or 0),
                "validation_candidate_mae_f":round(candidate_f,2),
                "validation_persistence_mae_f":round(persist_f,2),
                "historical_status":("PAST_HOLDOUT_BETTER_THAN_PERSISTENCE"
                  if candidate_f+0.5<persist_f else "PAST_HOLDOUT_NOT_CONVINCING")
            })
    if not candidates:
        raise ValueError("No horizon has adequate pre-freeze training and holdout evidence.")
    payload={"version":VERSION,"source_digest":_digest(source),
             "watch_digest":watch_digest,"created_at":wall,
             "cutoff":max(wall,float(high[1] or 0),parent["cutoff"]),
             "max_forecast_id":max(int(high[0]),parent["max_forecast_id"]),
             "candidates":candidates}
    digest=hashlib.sha256(_canon(payload).encode()).hexdigest()
    payload["artifact_sha256"]=digest
    encoded=_canon(payload)
    if len(encoded)>8192:
        raise ValueError("Challenger artifact exceeds size guard.")
    fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            f.write(encoded+"\n")
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return {"status":"FROZEN_CHALLENGER_RESEARCH_ONLY",
            "scope":"LOCAL_GHOST_ONLY","candidates":candidates,
            "min_evidence_days":MIN_EVIDENCE_DAYS,
            "production_changes":False,"network_uploads":False,
            "can_promote":False,"automatic_execution":False}

def _load(source,watch,challenger):
    path=_path(challenger,exists=True)
    data=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data,dict) or set(data)!=SCHEMA_KEYS:
        raise ValueError("Invalid frozen challenger artifact schema.")
    saved=data.copy()
    digest=saved.pop("artifact_sha256")
    if not isinstance(digest,str) or hashlib.sha256(_canon(saved).encode()).hexdigest()!=digest:
        raise ValueError("Challenger artifact integrity mismatch.")
    if (data["version"]!=VERSION or data["source_digest"]!=_digest(source)
        or data["watch_digest"]!=_hash_bytes(watch)):
        raise ValueError("Challenger belongs to a different source or M9 watch.")
    parent=_watch_load(source,watch)
    if (type(data["max_forecast_id"])!=int or data["max_forecast_id"]<parent["max_forecast_id"]
        or any(type(data[k]) not in (float,int) or not math.isfinite(data[k]) or
          data[k]<parent["created_at"] for k in ("created_at","cutoff"))):
        raise ValueError("Invalid challenger boundary.")
    cs=data["candidates"]
    if not isinstance(cs,list) or not 1<=len(cs)<=MAX_CANDIDATES:
        raise ValueError("Invalid challenger count.")
    expected={m["horizon_minutes"] for m in parent["models"]}
    used=set()
    for x in cs:
        if (not isinstance(x,dict) or set(x)!={"horizon_minutes","alpha","training_samples",
            "training_days","validation_samples","validation_days",
            "validation_candidate_mae_f","validation_persistence_mae_f","historical_status"}):
            raise ValueError("Invalid challenger coefficients.")
        h=x["horizon_minutes"]
        if (type(h)!=int or h not in expected or h in used
            or type(x["alpha"]) not in (float,int) or not math.isfinite(x["alpha"])
            or not 0<=x["alpha"]<=1):
            raise ValueError("Frozen coefficient outside approved bounds.")
        used.add(h)
    return data,parent

def challenger_status(source_db,watch_file,challenger_file, *, now=None):
    out={"status":"NOT_FROZEN","scope":"LOCAL_GHOST_ONLY",
         "challenger":"AMBIENT_RELAXATION_FROZEN_V1",
         "matched_pairs":0,"incomplete_pairs":0,"generation_excluded":0,
         "unsupported_horizon_pairs":0,"missing_ambient_pairs":0,"models":[],"limitations":NOTES,
         "production_changes":False,"network_uploads":False,
         "can_promote":False,"automatic_execution":False}
    if not Path(challenger_file).is_file():
        return out
    source=Path(source_db).expanduser().resolve()
    data,parent=_load(source,Path(watch_file).expanduser().absolute(),challenger_file)
    wall=time.time() if now is None else float(now)
    if not math.isfinite(wall) or wall<data["created_at"]:
        raise ValueError("Cannot evaluate before frozen challenger boundary.")
    if not source.is_file():
        out["status"]="SOURCE_UNAVAILABLE"
        return out
    coeff={x["horizon_minutes"]:x for x in data["candidates"]}
    locked={(x["model"],x["generation"],x["horizon_minutes"])
            for x in parent["models"]}
    with closing(sqlite3.connect(_uri(source),uri=True,timeout=10)) as con:
        con.row_factory=sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        _source_schema(con)
        where="""a.id>? AND a.predicted_at>? AND a.target_ts>?
                 AND a.resolved_at>=? AND a.resolved_at<=?
                 AND a.status='resolved' AND a.target_field='battery_temp_c'"""
        args=(data["max_forecast_id"],data["cutoff"],
              data["cutoff"],data["created_at"],wall)
        total=con.execute("SELECT COUNT(*) FROM prediction_audit a WHERE "+where,args).fetchone()[0]
        if total>MAX_POST_FREEZE:
            out["status"]="CAPACITY_REVIEW_REQUIRED"
            return out
        # Parameterized frozen recipe per horizon; never allow model text or
        # dynamic Python expressions to enter the SQL command.
        expressions=" UNION ALL ".join("SELECT ? h, ? alpha" for _ in coeff)
        ordered=[(h,coeff[h]["alpha"]) for h in sorted(coeff)]
        bindings=tuple(v for pair in ordered for v in pair)
        # Each observed forecast appears once: candidate/production/persistence
        # compared only where future actual and initial pack+ambient all exist.
        rows=con.execute(f"""
          WITH recipes(h,alpha) AS ({expressions})
          SELECT a.model_name name,a.generation generation,
                 a.horizon_minutes horizon, COUNT(*) total,
                 SUM(CASE WHEN t.battery_temp_c IS NOT NULL
                           AND t.outside_temp_c IS NOT NULL
                           AND a.actual_value IS NOT NULL AND a.predicted_value IS NOT NULL
                     THEN 1 ELSE 0 END) paired,
                 SUM(CASE WHEN t.outside_temp_c IS NULL
                     THEN 1 ELSE 0 END) missing_ambient,
                 COUNT(DISTINCT CASE WHEN t.battery_temp_c IS NOT NULL
                           AND t.outside_temp_c IS NOT NULL
                           AND a.actual_value IS NOT NULL AND a.predicted_value IS NOT NULL
                     THEN CAST(a.resolved_at/86400 AS INTEGER) END) days,
                 AVG(CASE WHEN t.battery_temp_c IS NOT NULL AND t.outside_temp_c IS NOT NULL
                      AND a.actual_value IS NOT NULL AND a.predicted_value IS NOT NULL
                     THEN ABS(a.predicted_value-a.actual_value) END) production_c,
                 AVG(CASE WHEN t.battery_temp_c IS NOT NULL AND t.outside_temp_c IS NOT NULL
                      AND a.actual_value IS NOT NULL AND a.predicted_value IS NOT NULL
                     THEN ABS(t.battery_temp_c-a.actual_value) END) persistence_c,
                 AVG(CASE WHEN t.battery_temp_c IS NOT NULL AND t.outside_temp_c IS NOT NULL
                      AND a.actual_value IS NOT NULL AND a.predicted_value IS NOT NULL
                     THEN ABS((t.battery_temp_c+
                       recipes.alpha*(t.outside_temp_c-t.battery_temp_c))-a.actual_value) END) challenger_c
          FROM prediction_audit a
          JOIN recipes ON recipes.h=a.horizon_minutes
          LEFT JOIN telemetry t ON t.id=a.source_telemetry_id
          WHERE {where}
          GROUP BY a.model_name,a.generation,a.horizon_minutes
        """,(*bindings,*args)).fetchall()
        covered=con.execute(f"""SELECT a.model_name name,a.generation gen,
             a.horizon_minutes horizon,COUNT(*) n
             FROM prediction_audit a WHERE {where}
             GROUP BY a.model_name,a.generation,a.horizon_minutes""",args).fetchall()
    emitted={}
    for row in rows:
        key=(row["name"],row["generation"],row["horizon"])
        count=int(row["total"] or 0)
        if key not in locked:
            continue
        n=int(row["paired"] or 0)
        out["matched_pairs"]+=n
        out["incomplete_pairs"]+=count-n
        out["missing_ambient_pairs"]+=int(row["missing_ambient"] or 0)
        h=row["horizon"]
        days=int(row["days"] or 0)
        metrics={}
        for name,keyname in (("production_c","production_mae_f"),
                             ("persistence_c","persistence_mae_f"),
                             ("challenger_c","challenger_mae_f")):
            val=row[name]
            metrics[keyname]=round(float(val)*1.8,2) if n and val is not None and math.isfinite(float(val)) else None
        c=metrics["challenger_mae_f"]
        p=metrics["production_mae_f"]
        base=metrics["persistence_mae_f"]
        enough=n>=MIN_SCORE and days>=MIN_EVIDENCE_DAYS
        if not enough:
            status="INSUFFICIENT_FUTURE_EVIDENCE"
        elif c is None or p is None or base is None:
            status="ERROR_UNAVAILABLE"
        elif c+0.5<min(p,base):
            status="CHALLENGER_BETTER_ON_FUTURE_SCORES"
        elif c>=min(p,base)+0.5:
            status="CHALLENGER_WORSE_THAN_BEST_REFERENCE"
        else:
            status="NO_CLEAR_CHALLENGER_ADVANTAGE"
        emitted[key]={
            "model":key[0],"generation":key[1],"horizon_minutes":h,
            "samples":n,"evidence_days":days,
            "alpha":coeff[h]["alpha"],
            **metrics,
            "challenger_advantage_vs_production_f":round(p-c,2) if c is not None and p is not None else None,
            "challenger_advantage_vs_persistence_f":round(base-c,2) if c is not None and base is not None else None,
            "assessment":status}
    for row in covered:
        key=(row["name"],row["gen"],row["horizon"])
        if key[2] not in coeff:
            out["unsupported_horizon_pairs"]+=int(row["n"] or 0)
        elif key not in locked:
            out["generation_excluded"]+=int(row["n"] or 0)
    for model in parent["models"]:
        key=(model["model"],model["generation"],model["horizon_minutes"])
        if model["horizon_minutes"] not in coeff:
            continue
        if key not in emitted:
            emitted[key]={
                "model":key[0],"generation":key[1],"horizon_minutes":key[2],
                "samples":0,"evidence_days":0,"alpha":coeff[key[2]]["alpha"],
                "production_mae_f":None,"persistence_mae_f":None,
                "challenger_mae_f":None,
                "challenger_advantage_vs_production_f":None,
                "challenger_advantage_vs_persistence_f":None,
                "assessment":"AWAITING_FUTURE_EVIDENCE"}
    out["models"]=sorted(emitted.values(),key=lambda x:(x["model"],x["horizon_minutes"]))
    out["candidates"]=[{
        "horizon_minutes":x["horizon_minutes"],
        "alpha":x["alpha"],
        "training_samples":x["training_samples"],
        "validation_samples":x["validation_samples"],
        "historical_status":x["historical_status"]} for x in data["candidates"]]
    out["status"]="POST_FREEZE_CHALLENGE_AVAILABLE" if out["matched_pairs"] else "AWAITING_FUTURE_EVIDENCE"
    out["min_evidence_days"]=MIN_EVIDENCE_DAYS
    return out

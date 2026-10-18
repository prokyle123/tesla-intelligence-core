"""Read-only local GHOST evidence for an integrated Hive dashboard.

Never infer active Hive contributors from local telemetry, and never expose
route/vehicle identifiers or individual records. The existing Home dashboard,
collector, neural training and Classic SQLite schema remain unchanged.

This endpoint neither uploads data nor enrolls users. Consent and transport
are a separate reviewed milestone.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import math
import json
import os
import urllib.request
from pathlib import Path
import sqlite3
import time
from urllib.parse import quote

from flask import Blueprint, jsonify, render_template
from . import config

bp = Blueprint("ghost_hive_local", __name__)
TEMP_ERROR_GOAL_F=2.0
MONTHS=7


def _periods(now:float) -> list[str]:
    dt=datetime.fromtimestamp(now,timezone.utc)
    year,month=dt.year,dt.month
    vals=[]
    for _ in range(MONTHS):
        vals.append(f"{year:04d}-{month:02d}")
        month-=1
        if month==0:
            month=12
            year-=1
    return vals[::-1]


def _read_only(path:Path) -> sqlite3.Connection:
    resolved=Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError("Local GHOST telemetry database is unavailable")
    uri="file:"+quote(str(resolved),safe="/")+"?mode=ro"
    con=sqlite3.connect(uri,uri=True,timeout=3)
    con.row_factory=sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def _num(v,places=1):
    try:
        value=float(v)
    except (ValueError,TypeError,OverflowError):
        return None
    return round(value,places) if math.isfinite(value) else None


def _private_consent():
    result={"mode":"OFF","last_success_month":None}
    try:
        root=Path(os.environ.get(
            "GHOST_HIVE_CLIENT_STATE_DIR",
            str(Path.home()/"genesis-product/state/hive-client"))).expanduser()
        policy=root/"real-consent.json"
        if policy.is_file() and not policy.is_symlink() and not policy.stat().st_mode & 0o077:
            data=json.loads(policy.read_text())
            if data.get("policy")=="MONTHLY_BATTERY_TEMP_ERROR_V1":
                result["mode"]="OPTED_IN" if data.get("mode")=="OPTED_IN" else "OFF"
        receipt=root/"last-receipt.json"
        if receipt.is_file() and not receipt.is_symlink() and not receipt.stat().st_mode & 0o077:
            data=json.loads(receipt.read_text())
            result["last_success_month"]=data.get("month")
    except (OSError,ValueError,TypeError,json.JSONDecodeError):
        pass
    return result


def _local_coordinator():
    # Only loopback to the independent Hive process; no remote network calls
    # or Tesla polling in the Home web request path.
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:8778/v1/public-network",timeout=.6) as response:
            r=json.load(response)
        if r.get("schema")!="ghost-hive-public-v1":
            return None
        return r
    except (OSError,ValueError,TypeError,json.JSONDecodeError):
        return None


def _empty():
    return {
      "scope":"LOCAL_GHOST_ONLY",
      "hive":{"status":"NOT_CONNECTED","contribution":"OFF",
              "accepted_uploads":0,"real_transfer_enabled":False},
      "local":{"telemetry_samples":None,"predictions_scored":None,
               "temp_predictions_scored":None,"temp_mae_f":None,
               "within_2f_percent":None,"pending_predictions":None,
               "drive_events":None,"last_sample_age_minutes":None},
      "fleet":{"participating_vehicles":None,"predictions_checked":None,
               "accuracy_percent":None,"countries":None,
               "prediction_improvement_percent":None,
               "regions":[],"available":False},
      "monthly":[],
      "contribution_activity":[],
      "privacy":{"coarse_regions_enabled":False,"raw_trips_shared":False,
                 "gps_shared":False,"anonymous":False},
      "disclaimer":"Only verified local model scores are shown. No Hive fleet totals or locations are asserted without confirmed submissions.",
    }


def _month_label(period):
    return datetime.strptime(period,"%Y-%m").strftime("%b %Y")


def local_snapshot(path:Path|None=None, *, now:float|None=None)->dict:
    result=_empty()
    when=time.time() if now is None else float(now)
    periods=_periods(when)
    for period in periods:
        result["monthly"].append({
            "period":period,"label":_month_label(period),
            "predictions":0,"temp_predictions":0,
            "temp_mae_f":None,"within_2f_percent":None,
        })
    if path is None:
        path=config.DB_PATH
    try:
        with closing(_read_only(path)) as con:
            tables={r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "telemetry" in tables:
                telemetry_columns={r[1] for r in con.execute("PRAGMA table_info(telemetry)")}
                if "car_id" in telemetry_columns:
                    count=con.execute("SELECT COUNT(DISTINCT car_id) FROM telemetry").fetchone()[0]
                    if count>1:
                        result["error"]="MULTIPLE_VEHICLES_REQUIRE_PER_VEHICLE_ISOLATION"
                        return result
                row=con.execute("SELECT COUNT(*) n,MAX(ts) latest FROM telemetry").fetchone()
                result["local"]["telemetry_samples"]=int(row["n"])
                stamp=_num(row["latest"])
                if stamp is not None:
                    result["local"]["last_sample_age_minutes"]=_num(max(0,when-stamp)/60)
            if "vehicle_events" in tables:
                result["local"]["drive_events"]=int(con.execute(
                    "SELECT COUNT(*) FROM vehicle_events WHERE lower(event_type) IN ('drive','driving')"
                ).fetchone()[0])
            if "prediction_audit" not in tables:
                return result
            # The evidence ledger distinguishes predictions from raw telemetry.
            counts=con.execute("""
                SELECT SUM(CASE WHEN status='resolved' THEN 1 ELSE 0 END) resolved,
                       SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) pending
                FROM prediction_audit
            """).fetchone()
            result["local"]["predictions_scored"]=int(counts["resolved"] or 0)
            result["local"]["pending_predictions"]=int(counts["pending"] or 0)
            temp=con.execute("""
                SELECT COUNT(*) n,AVG(abs_error) mae,
                    SUM(CASE WHEN abs_error * 1.8 <= ? THEN 1 ELSE 0 END) hits
                FROM prediction_audit
                WHERE status='resolved' AND target_field='battery_temp_c'
                  AND abs_error IS NOT NULL AND abs_error>=0
            """,(TEMP_ERROR_GOAL_F,)).fetchone()
            n=int(temp["n"] or 0)
            result["local"]["temp_predictions_scored"]=n
            result["local"]["temp_mae_f"]=_num(temp["mae"]*1.8,2) if n else None
            result["local"]["within_2f_percent"]=_num(100*int(temp["hits"] or 0)/n) if n else None
            start=periods[0]
            monthrows=con.execute("""
                SELECT strftime('%Y-%m',resolved_at,'unixepoch') period,
                    COUNT(*) n,
                    SUM(CASE WHEN target_field='battery_temp_c'
                             AND abs_error IS NOT NULL AND abs_error>=0
                             THEN 1 ELSE 0 END) temp_n,
                    AVG(CASE WHEN target_field='battery_temp_c'
                             AND abs_error IS NOT NULL AND abs_error>=0
                             THEN abs_error END) temp_mae,
                    SUM(CASE WHEN target_field='battery_temp_c'
                             AND abs_error IS NOT NULL AND abs_error>=0
                             AND abs_error * 1.8 <= ?
                             THEN 1 ELSE 0 END) temp_hits
                FROM prediction_audit
                WHERE status='resolved' AND resolved_at IS NOT NULL
                  AND resolved_at>=? AND resolved_at<=?
                GROUP BY strftime('%Y-%m',resolved_at,'unixepoch')
            """,(TEMP_ERROR_GOAL_F,
                 datetime.fromisoformat(start+"-01").replace(tzinfo=timezone.utc).timestamp(),
                 when)).fetchall()
            bymonth={r["period"]:r for r in monthrows}
            for month in result["monthly"]:
                row=bymonth.get(month["period"])
                if row is None:
                    continue
                month["predictions"]=int(row["n"] or 0)
                tn=int(row["temp_n"] or 0)
                month["temp_predictions"]=tn
                if tn:
                    month["temp_mae_f"]=_num(float(row["temp_mae"])*1.8,2)
                    month["within_2f_percent"]=_num(
                        100*int(row["temp_hits"] or 0)/tn)
            # Daily scored-outcome counts only; no trip timestamps, routes or IDs.
            week_start=when-6*86400
            daily=con.execute("""
                SELECT strftime('%Y-%m-%d',resolved_at,'unixepoch') day,
                       COUNT(*) n FROM prediction_audit
                WHERE status='resolved' AND resolved_at>=? AND resolved_at<=?
                GROUP BY strftime('%Y-%m-%d',resolved_at,'unixepoch')
            """,(week_start,when)).fetchall()
            result["contribution_activity"]=[
                {"day":row["day"],"local_predictions_scored":int(row["n"])}
                for row in daily
            ]
    except (sqlite3.Error,FileNotFoundError,ValueError,OverflowError):
        result["error"]="LOCAL_RESEARCH_DATABASE_UNAVAILABLE"
    # Aggregate transport status never depends on the private telemetry
    # table. It is read only after the existing local evidence snapshot.
    consent=_private_consent()
    result["hive"]["contribution"]=consent["mode"]
    result["hive"]["last_success_month"]=consent["last_success_month"]
    hub=_local_coordinator()
    if hub is not None:
        result["fleet"]["available"]=True
        result["fleet"]["coordinator_connected"]=True
        result["fleet"]["participating_vehicles"]=hub.get("reporting_nodes")
        result["fleet"]["predictions_checked"]=hub.get("predictions_checked")
        result["fleet"]["mean_error_f"]=hub.get("mean_error_f")
        result["fleet"]["monthly"]=hub.get("monthly",[])
    else:
        result["fleet"]["coordinator_connected"]=False
    return result


@bp.get("/hive")
def hive_home():
    return render_template("hive.html")


@bp.get("/api/hive/local")
def hive_local():
    response=jsonify(local_snapshot())
    response.headers["Cache-Control"]="no-store"
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["Referrer-Policy"]="no-referrer"
    return response

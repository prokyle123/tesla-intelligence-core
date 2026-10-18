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
    result={"mode":"OFF","last_success_month":None,"last_success_at_utc":None,"hourly_enabled":False}
    try:
        root=Path(os.environ.get(
            "GHOST_HIVE_CLIENT_STATE_DIR",
            str(Path.home()/"genesis-product/state/hive-client"))).expanduser()
        policy=root/"real-consent.json"
        if policy.is_file() and not policy.is_symlink() and not policy.stat().st_mode & 0o077:
            data=json.loads(policy.read_text())
            if data.get("policy")=="MONTHLY_BATTERY_TEMP_ERROR_V1":
                result["mode"]="OPTED_IN" if data.get("mode")=="OPTED_IN" else "OFF"
                result["hourly_enabled"]=(result["mode"]=="OPTED_IN" and data.get("schedule")=="hourly")
        receipt=root/"last-receipt.json"
        if receipt.is_file() and not receipt.is_symlink() and not receipt.stat().st_mode & 0o077:
            data=json.loads(receipt.read_text())
            result["last_success_month"]=data.get("month")
            result["last_success_at_utc"]=data.get("time_utc")
    except (OSError,ValueError,TypeError,json.JSONDecodeError):
        pass
    result["region_code"]=None
    try:
        region=root/"regional-consent.json"
        if region.is_file() and not region.is_symlink() and not region.stat().st_mode & 0o077:
            optional=json.loads(region.read_text())
            result["region_code"]=optional.get("region_code") if optional.get("enabled") is True else None
    except (ValueError,OSError,TypeError,UnboundLocalError):
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
    result["hive"]["last_success_at_utc"]=consent.get("last_success_at_utc")
    result["hive"]["hourly_enabled"]=consent.get("hourly_enabled",False)
    result["hive"]["region_code"]=consent.get("region_code")
    result["hive"]["real_transfer_enabled"]=consent.get("hourly_enabled",False)
    hub=_local_coordinator()
    if hub is not None:
        result["fleet"]["available"]=True
        result["fleet"]["coordinator_connected"]=True
        result["fleet"]["participating_vehicles"]=hub.get("reporting_nodes")
        result["fleet"]["predictions_checked"]=hub.get("predictions_checked")
        result["fleet"]["mean_error_f"]=hub.get("mean_error_f")
        result["fleet"]["monthly"]=hub.get("monthly",[])
        result["fleet"]["regions"]=hub.get("regions",[])
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


# Owner-authorized actions are isolated to this Hive blueprint. The existing
# Home dashboard and all of its other routes remain unchanged.
import hashlib as _hashlib
import hmac as _hmac
import subprocess as _subprocess
import sys as _sys
import threading as _threading
from flask import request as _request

_CONTROL_LOCK=_threading.Lock()
_ALLOWED_ACTIONS=frozenset(("preview","consent","join","send","disable","revoke"))


def _client_root() -> Path:
    return Path(os.environ.get(
        "GHOST_HIVE_CLIENT_STATE_DIR",
        str(Path.home()/"genesis-product/state/hive-client"))).expanduser().absolute()


def _operator_permitted() -> bool:
    # Strict same-origin JSON POST plus out-of-band local per-install key.
    # No cookie session, wildcard CORS or browser-persisted credential.
    if _request.mimetype!="application/json" or _request.content_length is None or _request.content_length>1024:
        return False
    origin=_request.headers.get("Origin","")
    if not origin or origin!=_request.host_url.rstrip("/"):
        return False
    # For this local developer preview, an authenticated SSH-forwarded
    # 127.0.0.1 connection is the owner authentication boundary. Never
    # trust arbitrary tailnet/LAN/browser clients or proxy headers.
    if (_request.remote_addr in ("127.0.0.1","::1")
        and _request.host in ("127.0.0.1:8766","[::1]:8766")
        and origin in ("http://127.0.0.1:8766","http://[::1]:8766")
        and not any(h in _request.headers for h in
            ("Forwarded","X-Forwarded-For","X-Forwarded-Host","X-Real-IP"))):
        return True
    key=_client_root()/"dashboard-admin.token"
    if not key.is_file() or key.is_symlink() or key.stat().st_mode & 0o077:
        return False
    expected=key.read_text().strip()
    provided=_request.headers.get("X-Ghost-Hive-Owner","")
    return bool(40<=len(provided)<=256 and len(expected)>=40 and
                _hmac.compare_digest(provided,expected))


def _hourly_service_ready() -> bool:
    # The UI must not promise hourly delivery if no timer is active.
    try:
        proc=_subprocess.run(
            ["systemctl","is-active","--quiet","ghost-hive-hourly.timer"],
            timeout=3,capture_output=True,check=False)
        return proc.returncode==0
    except (OSError,_subprocess.SubprocessError):
        return False


def _run_hive_action(action:str,*,month:str|None=None,region_code:str|None=None) -> dict:
    """Execute reviewed standalone monthly-aggregate module, not a shell."""
    if action not in (_ALLOWED_ACTIONS | {"sync-now","region-set","region-clear"}):
        raise ValueError("Unsupported action")
    app=Path(os.environ.get("GHOST_HIVE_CODE_DIR",
        str(Path.home()/"genesis-product/current"))).expanduser().absolute()
    if not (app/"genesis/hive_member.py").is_file():
        raise RuntimeError("Hive research client is not installed")
    args=[_sys.executable,"-m","genesis.hive_member",
          "--state-dir",str(_client_root()),
          "--source-db",str(config.DB_PATH)]
    if action in ("region-set","region-clear"):
        args=[_sys.executable,"-m","genesis.hive_region_client",
              "--state-dir",str(_client_root()),
              "set" if action=="region-set" else "clear"]
        if action=="region-set":
            if region_code not in (
                "NORTH_AMERICA_WEST","NORTH_AMERICA_EAST","SOUTH_AMERICA",
                "EUROPE","AFRICA","ASIA","OCEANIA"):
                raise ValueError("Broad region not approved")
            args.extend(["--region-code",region_code])
    elif action=="sync-now":
        args=[_sys.executable,"-m","genesis.hive_hourly",
              "--state-dir",str(_client_root()),
              "--source-db",str(config.DB_PATH)]
    elif action in ("consent","join"):
        args.extend(["consent","--i-understand-pseudonymous-aggregate-sharing"])
        if action=="join":
            args.append("--hourly")
    elif action=="revoke":
        args.extend(["revoke-remote","--confirm-delete"])
    elif action=="send":
        args.extend(["send","--month",month or "","--confirm-upload"])
    elif action=="preview":
        args.extend(["preview","--month",month or ""])
    else:
        args.append("disable")
    worker=_subprocess.run(args,cwd=app,timeout=40 if action=="sync-now" else 25,capture_output=True,text=True,
        env={"HOME":str(Path.home()),"PATH":"/usr/bin:/bin","PYTHONPATH":str(app)},
        check=True)
    data=json.loads(worker.stdout)
    if not isinstance(data,dict):
        raise ValueError("Unexpected Hive reply")
    return data


def _approved_month(payload:dict)->str|None:
    month=payload.get("month")
    if not isinstance(month,str) or len(month)!=7:
        return None
    from datetime import datetime as _datetime
    try:
        when=_datetime.strptime(month,"%Y-%m")
        if when.strftime("%Y-%m")!=month:
            return None
        return month
    except ValueError:
        return None


def _payload_fingerprint(payload:dict)->str:
    # A changed monthly report cannot be uploaded behind an outdated preview.
    content=json.dumps(payload,sort_keys=True,separators=(",",":")).encode()
    return _hashlib.sha256(content).hexdigest()


@bp.post("/api/hive/control/<action>")
def hive_control(action:str):
    if action not in _ALLOWED_ACTIONS:
        return jsonify({"error":"UNKNOWN_ACTION"}),404
    if not _operator_permitted():
        return jsonify({"error":"OWNER_AUTHORIZATION_REQUIRED"}),403
    payload=_request.get_json(silent=True)
    if not isinstance(payload,dict):
        return jsonify({"error":"INVALID_REQUEST"}),400
    if not _CONTROL_LOCK.acquire(blocking=False):
        return jsonify({"error":"HIVE_OPERATION_IN_PROGRESS"}),409
    try:
        month=None
        if action in ("preview","send"):
            month=_approved_month(payload)
            if not month:
                return jsonify({"error":"SELECT_A_VALID_UTC_MONTH"}),400
        if action in ("consent","join") and payload.get("acknowledge_pseudonymous_sharing") is not True:
            return jsonify({"error":"INFORMED_CONSENT_REQUIRED"}),400
        if action=="join" and payload.get("allow_hourly_aggregates") is not True:
            return jsonify({"error":"HOURLY_TRANSFER_CONSENT_REQUIRED"}),400
        if action=="join" and payload.get("region_code") is not None and payload.get("region_code") not in (
            "NORTH_AMERICA_WEST","NORTH_AMERICA_EAST","SOUTH_AMERICA","EUROPE","AFRICA","ASIA","OCEANIA"):
            return jsonify({"error":"INVALID_OPTIONAL_BROAD_REGION"}),400
        if action=="join" and not _hourly_service_ready():
            return jsonify({"error":"HOURLY_TRANSFER_TIMER_NOT_RUNNING"}),503
        if action=="send":
            if payload.get("confirm_this_exact_report") is not True:
                return jsonify({"error":"EXPLICIT_SEND_CONFIRMATION_REQUIRED"}),400
            fingerprint=payload.get("preview_sha256")
            if not isinstance(fingerprint,str) or len(fingerprint)!=64:
                return jsonify({"error":"PREVIEW_REQUIRED"}),400
            current=_run_hive_action("preview",month=month)
            if (not current.get("eligible") or not current.get("payload") or
                not _hmac.compare_digest(fingerprint,_payload_fingerprint(current["payload"]))):
                return jsonify({"error":"REPORT_CHANGED_REFRESH_PREVIEW"}),409
        if action=="revoke" and payload.get("confirmation")!="DELETE":
            return jsonify({"error":"TYPE_DELETE_TO_CONFIRM"}),400
        result=_run_hive_action(action,month=month)
        if action=="join" and result.get("mode")=="OPTED_IN":
            # Immediate first contribution after informed consent. A failed
            # first attempt MUST leave opted-in state active for timer retry.
            # No additional consent or new payload fields are inferred.
            try:
                first=_run_hive_action("sync-now")
                result["first_upload"]={
                    "state":first.get("state","UNKNOWN"),
                    "month":first.get("month"),
                    "network_request":bool(first.get("network_request",False))}
            except (_subprocess.SubprocessError,ValueError,RuntimeError,OSError,json.JSONDecodeError):
                result["first_upload"]={"state":"RETRY_SCHEDULED","network_request":False}
            if payload.get("region_code"):
                # A distinct optional informed selection. No geolocation inference.
                try:
                    result["region_update"]=_run_hive_action(
                        "region-set",region_code=payload["region_code"])
                except (_subprocess.SubprocessError,ValueError,RuntimeError,OSError,json.JSONDecodeError):
                    result["region_update"]={"regional_sharing":"NOT_CONFIRMED"}
            else:
                # Rejoining without choosing a region MUST NOT silently retain a
                # previous published regional consent.
                try:
                    result["region_update"]=_run_hive_action("region-clear")
                except (_subprocess.SubprocessError,ValueError,RuntimeError,OSError,json.JSONDecodeError):
                    result["region_update"]={"regional_sharing":"REMOTE_REMOVAL_NOT_CONFIRMED"}
        if action=="disable":
            # Explicit OFF: disable future uploads and separately request
            # deletion of any previous regional placement.
            try:
                result["region_update"]=_run_hive_action("region-clear")
            except (_subprocess.SubprocessError,ValueError,RuntimeError,OSError,json.JSONDecodeError):
                result["region_update"]={"regional_sharing":"REMOTE_REMOVAL_NOT_CONFIRMED"}
        if action=="preview" and result.get("eligible") and result.get("payload"):
            result["preview_sha256"]=_payload_fingerprint(result["payload"])
        response=jsonify(result)
        response.headers["Cache-Control"]="no-store"
        response.headers["X-Content-Type-Options"]="nosniff"
        return response
    except (_subprocess.SubprocessError,ValueError,RuntimeError,OSError,json.JSONDecodeError):
        return jsonify({"error":"HIVE_ACTION_FAILED_CHECK_LOCAL_CONFIGURATION"}),503
    finally:
        _CONTROL_LOCK.release()

from __future__ import annotations

import math
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import json
import hmac
import hashlib
import random
import threading
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from . import config, db
from .starlink_local import read_power as _starlink_read_power
from . import ecoflow_mqtt
from .features import MODEL_SPECS
from .predict import current_predictions

try:
    VERSION = Path("/opt/ghost-tesla-ai/VERSION").read_text().strip() or "0.4.1"
except Exception:
    VERSION = "0.4.1"
app = Flask(__name__, template_folder="/opt/ghost-tesla-ai/web/templates")
from .v3_api import bp as v3_bp
app.register_blueprint(v3_bp)
from .v4_api import bp as v4_bp
app.register_blueprint(v4_bp)

MAE_GOALS = {
    "soc_60m": 2.0,
    "soc_180m": 3.0,
    "cabin_temp_60m": 2.0,
    "pack_temp_60m": 2.0,
    "pack_temp_180m": 3.0,
    "cold_pack_60m": 2.5,
    "charge_soc_60m": 2.0,
    "precondition_pack_30m": 3.0,
    "park_soc_180m": 2.0,
}
MODEL_ACCENTS = {"soc_60m":"violet","soc_180m":"cyan","cabin_temp_60m":"amber","pack_temp_60m":"blue","pack_temp_180m":"blue","cold_pack_60m":"cyan","charge_soc_60m":"green","precondition_pack_30m":"amber","park_soc_180m":"violet"}
TARGET_FIELDS = {name: spec["target"] for name, spec in MODEL_SPECS.items()}

_SYSTEM_STATUS_CACHE = {"at": 0.0, "value": {}}
_ECOFLOW_CACHE = {"at": 0.0, "value": {"configured": False, "status": "unconfigured"}, "refreshing": False}
_ECOFLOW_LOCK = threading.Lock()


def _read_text(path, default=""):
    try:
        return Path(path).read_text().strip()
    except Exception:
        return default


def _run_quick(args, timeout=1.5):
    try:
        r=subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def _ping_ms(host, timeout_s=1):
    try:
        r=subprocess.run(["ping","-n","-c","1","-W",str(int(timeout_s)),host], capture_output=True, text=True, timeout=timeout_s+0.8, check=False)
        if r.returncode != 0:
            return None
        out=(r.stdout or "") + " " + (r.stderr or "")
        m=re.search(r"time[=<]([0-9.]+)\s*ms",out)
        if m:
            return round(float(m.group(1)),1)
        if "time<1 ms" in out:
            return 0.9
    except Exception:
        pass
    return None


def _active_wifi_ssid():
    out=_run_quick(["nmcli","-t","-f","ACTIVE,SSID","dev","wifi"],1.4)
    for line in out.splitlines():
        if line.startswith("yes:"):
            return line[4:].replace("\\:",":").strip()
    return None


def _default_iface():
    out=_run_quick(["ip","route","show","default"],1.0)
    m=re.search(r"\bdev\s+(\S+)",out)
    return m.group(1) if m else None



_CPU_STAT_PREV = None

def _cpu_times():
    """Return (total_jiffies, idle_jiffies) from aggregate /proc/stat."""
    try:
        line=_read_text('/proc/stat').splitlines()[0].split()
        if not line or line[0] != 'cpu':
            return None
        vals=[int(x) for x in line[1:]]
        if len(vals) < 4:
            return None
        # Linux CPU fields: user nice system idle iowait irq softirq steal ...
        # guest/guest_nice are already included in user/nice, so do not add them.
        tracked=vals[:8]
        total=sum(tracked)
        idle=vals[3] + (vals[4] if len(vals) > 4 else 0)
        return total,idle
    except Exception:
        return None

def _cpu_util_pct():
    """Overall CPU busy percentage since the previous sample."""
    global _CPU_STAT_PREV
    cur=_cpu_times()
    if cur is None:
        return None
    prev=_CPU_STAT_PREV
    _CPU_STAT_PREV=cur
    if prev is None:
        return None
    dt=cur[0]-prev[0]
    di=cur[1]-prev[1]
    if dt <= 0:
        return None
    busy=(dt-di)/dt*100.0
    return round(max(0.0,min(100.0,busy)),1)

# Prime the baseline when the web process imports this module so the first
# dashboard request can normally show CPU utilization immediately.
_CPU_STAT_PREV = _cpu_times()

def _system_status(now=None):
    now=float(now or time.time())
    cached=_SYSTEM_STATUS_CACHE.get("value") or {}
    if cached and now-float(_SYSTEM_STATUS_CACHE.get("at") or 0) < 15:
        return cached

    # Pi health from local kernel/procfs; no extra service required.
    temp_raw=_read_text('/sys/class/thermal/thermal_zone0/temp')
    try:
        cpu_c=float(temp_raw)/1000.0
        cpu_f=round(cpu_c*9/5+32,1)
    except Exception:
        cpu_c=cpu_f=None

    mem={}
    for line in _read_text('/proc/meminfo').splitlines():
        if ':' in line:
            k,v=line.split(':',1)
            try: mem[k]=float(v.strip().split()[0])
            except Exception: pass
    total=mem.get('MemTotal'); avail=mem.get('MemAvailable')
    ram_pct=None if not total else round(max(0.0,min(100.0,(total-(avail or 0))/total*100.0)),1)
    cpu_util=_cpu_util_pct()
    try: load1=round(float(_read_text('/proc/loadavg').split()[0]),2)
    except Exception: load1=None
    try: uptime_s=int(float(_read_text('/proc/uptime').split()[0]))
    except Exception: uptime_s=None
    try:
        disk=shutil.disk_usage('/')
        disk_pct=round((disk.used/disk.total)*100.0,1) if disk.total else None
    except Exception:
        disk_pct=None

    ssid=_active_wifi_ssid()
    iface=_default_iface()
    wan_ms=_ping_ms('1.1.1.1',1)
    dish_ms=_ping_ms('192.168.100.1',1)
    starlink_detected=bool((ssid and 'STARLINK' in ssid.upper()) or dish_ms is not None)

    # The Starlink dish exposes its own electrical power through the local
    # gRPC history ring. Query only when the dish appears locally reachable;
    # this avoids adding a multi-second timeout to every status refresh when
    # the Pi is away from the Starlink LAN.
    starlink_power={'ok':False,'power_w':None,'source':'dish_get_history.power_in','error':None}
    if dish_ms is not None:
        try:
            starlink_power=_starlink_read_power()
        except Exception as e:
            starlink_power={'ok':False,'power_w':None,'source':'dish_get_history.power_in','error':f'{type(e).__name__}: {e}'}

    value={
        'generated_at':now,
        'pi':{
            'hostname':socket.gethostname(),
            'cpu_temp_c':None if cpu_c is None else round(cpu_c,1),
            'cpu_temp_f':cpu_f,
            'ram_used_pct':ram_pct,
            'cpu_util_pct':cpu_util,
            'load_1m':load1,
            'uptime_s':uptime_s,
            'disk_used_pct':disk_pct,
        },
        'network':{
            'ssid':ssid,
            'default_iface':iface,
            'wan_online':wan_ms is not None,
            'wan_latency_ms':wan_ms,
            'starlink_detected':starlink_detected,
            'dish_reachable':dish_ms is not None,
            'dish_latency_ms':dish_ms,
            'starlink_power_w':starlink_power.get('power_w'),
            'starlink_power_source':starlink_power.get('source'),
            'starlink_power_error':starlink_power.get('error'),
        }
    }
    _SYSTEM_STATUS_CACHE['at']=now
    _SYSTEM_STATUS_CACHE['value']=value
    return value



def _flatten_payload(value, prefix="", out=None):
    if out is None:
        out={}
    if isinstance(value, dict):
        for k,v in value.items():
            key=f"{prefix}.{k}" if prefix else str(k)
            _flatten_payload(v,key,out)
    elif isinstance(value, list):
        for i,v in enumerate(value):
            key=f"{prefix}.{i}" if prefix else str(i)
            _flatten_payload(v,key,out)
    else:
        out[prefix]=value
    return out


def _quota_number(flat, candidates):
    # River 3 firmware/API revisions use several naming shapes. Prefer exact
    # leaf-name matches, then suffix matches, while accepting only finite numbers.
    items=list(flat.items())
    for cand in candidates:
        cl=cand.lower()
        for k,v in items:
            leaf=k.rsplit('.',1)[-1].lower()
            if leaf == cl:
                try:
                    x=float(v)
                    if math.isfinite(x): return x
                except Exception:
                    pass
    for cand in candidates:
        cl=cand.lower()
        for k,v in items:
            if k.lower().endswith(cl):
                try:
                    x=float(v)
                    if math.isfinite(x): return x
                except Exception:
                    pass
    return None


def _ecoflow_fetch():
    key=config.ECOFLOW_ACCESS_KEY
    secret=config.ECOFLOW_SECRET_KEY
    sn=config.ECOFLOW_RIVER3_SN
    if not (key and secret and sn):
        return {
            'configured':False,
            'status':'unconfigured',
            'device':'RIVER 3',
            'message':'Add EcoFlow API key, secret, and River 3 serial to ghost.env',
        }

    nonce=str(random.randint(100000,999999))
    timestamp=str(int(time.time()*1000))
    params={'sn':sn}
    query=urllib.parse.urlencode(sorted(params.items()))
    base_headers={'accessKey':key,'nonce':nonce,'timestamp':timestamp}
    sign_header='&'.join(f"{k}={base_headers[k]}" for k in sorted(base_headers))
    sign_string=f"{query}&{sign_header}" if query else sign_header
    signature=hmac.new(secret.encode('utf-8'),sign_string.encode('utf-8'),hashlib.sha256).hexdigest()
    headers={**base_headers,'sign':signature,'Accept':'application/json','User-Agent':'GHOST-Tesla-AI/0.8.26'}
    url=f"{config.ECOFLOW_API_BASE}/iot-open/sign/device/quota/all?{query}"
    req=urllib.request.Request(url,headers=headers,method='GET')
    started=time.time()
    try:
        with urllib.request.urlopen(req,timeout=config.ECOFLOW_TIMEOUT_SECONDS) as resp:
            payload=json.loads(resp.read().decode('utf-8','replace'))
        code=payload.get('code')
        if code not in (None,0,'0','0000'):
            raise RuntimeError(f"EcoFlow API {code}: {payload.get('message') or payload.get('msg') or 'request failed'}")
        data=payload.get('data') or {}
        flat=_flatten_payload(data)

        soc=_quota_number(flat,['cmsBattSoc','bmsBattSoc','f32ShowSoc','soc'])
        # Prefer a BMS/cell temperature over controller temperatures.
        temp_c=_quota_number(flat,['bmsMaxCellTemp','maxCellTemp','temp','bmsMinCellTemp','minCellTemp'])
        out_w=_quota_number(flat,['powGetAc','powGetAcOut','outputWatts'])
        in_w=_quota_number(flat,['powGetAcIn','inputWatts'])
        remain_min=_quota_number(flat,['cmsDsgRemTime','bmsDsgRemTime','remainTime'])
        charge_min=_quota_number(flat,['cmsChgRemTime','bmsChgRemTime'])
        soh=_quota_number(flat,['cmsBattSoh','bmsBattSoh','realSoh','soh'])
        cycles=_quota_number(flat,['cycles'])

        # Some heartbeat payloads label remainTime as minutes, others integrations
        # expose an already-normalized value. Values larger than a week are ignored.
        if remain_min is not None and remain_min > 10080:
            remain_min=None
        if charge_min is not None and charge_min > 10080:
            charge_min=None
        temp_f=None if temp_c is None else round(temp_c*9/5+32,1)

        return {
            'configured':True,
            'status':'online',
            'online':True,
            'device':'RIVER 3',
            'serial_tail':sn[-6:],
            'soc':None if soc is None else round(soc,1),
            'battery_temp_c':None if temp_c is None else round(temp_c,1),
            'battery_temp_f':temp_f,
            'input_w':None if in_w is None else round(in_w,1),
            'output_w':None if out_w is None else round(out_w,1),
            'remaining_min':None if remain_min is None else int(round(remain_min)),
            'charge_remaining_min':None if charge_min is None else int(round(charge_min)),
            'soh':None if soh is None else round(soh,1),
            'cycles':None if cycles is None else int(round(cycles)),
            'updated_at':time.time(),
            'latency_ms':round((time.time()-started)*1000,0),
        }
    except Exception as e:
        return {
            'configured':True,
            'status':'offline',
            'online':False,
            'device':'RIVER 3',
            'serial_tail':sn[-6:],
            'error':f"{type(e).__name__}: {e}",
            'updated_at':time.time(),
        }


def _ecoflow_refresh_worker():
    try:
        value=_ecoflow_fetch()
        with _ECOFLOW_LOCK:
            previous=_ECOFLOW_CACHE.get('value') or {}
            # If a refresh fails, retain the last good measurements but mark them stale.
            if value.get('online') is False and previous.get('online') is True:
                merged=dict(previous)
                merged.update({
                    'online':False,
                    'status':'stale',
                    'error':value.get('error'),
                    'last_attempt_at':value.get('updated_at'),
                })
                value=merged
            _ECOFLOW_CACHE['value']=value
            _ECOFLOW_CACHE['at']=time.time()
    finally:
        with _ECOFLOW_LOCK:
            _ECOFLOW_CACHE['refreshing']=False


def _ecoflow_status(now=None):
    # RIVER 3 / R651 is listed by EcoFlow's Open API but quota/all is blocked
    # with code 1006. Use the same private app-MQTT transport as the EcoFlow
    # mobile app instead. Older/non-River devices retain the public REST path.
    sn=(config.ECOFLOW_RIVER3_SN or '').upper()
    if sn.startswith(('R641','R651')):
        return ecoflow_mqtt.status()

    now=float(now or time.time())
    configured=bool(config.ECOFLOW_ACCESS_KEY and config.ECOFLOW_SECRET_KEY and config.ECOFLOW_RIVER3_SN)
    with _ECOFLOW_LOCK:
        value=dict(_ECOFLOW_CACHE.get('value') or {})
        age=now-float(_ECOFLOW_CACHE.get('at') or 0)
        refreshing=bool(_ECOFLOW_CACHE.get('refreshing'))
        if not configured:
            return {
                'configured':False,
                'status':'unconfigured',
                'device':'RIVER 3',
                'message':'EcoFlow credentials not configured',
            }
        if (not value.get('configured') or age >= config.ECOFLOW_POLL_SECONDS) and not refreshing:
            _ECOFLOW_CACHE['refreshing']=True
            threading.Thread(target=_ecoflow_refresh_worker,name='ghost-ecoflow-refresh',daemon=True).start()
            refreshing=True
        value.setdefault('configured',True)
        value.setdefault('device','RIVER 3')
        value['refreshing']=refreshing
        if _ECOFLOW_CACHE.get('at'):
            value['cache_age_s']=round(max(0.0,age),1)
        return value

def f2(c):
    return None if c is None else round(float(c) * 9 / 5 + 32, 1)

def age(ts):
    return None if not ts else max(0, int(time.time() - float(ts)))

def _finite(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except Exception: return None

def _readiness(model_name: str, run=None, source_rows: int = 0) -> int:
    full_evidence=max(int(config.MIN_TRAIN_ROWS)*6,720)
    rows=int(run["rows_total"] if run is not None else source_rows or 0)
    evidence=min(100.0,rows/full_evidence*100.0)
    if run is None or run["mae"] is None: return int(round(evidence*.35))
    mae=_finite(run["mae"]); goal=float(MAE_GOALS.get(model_name,2.0))
    validation=0.0 if mae is None else max(0.0,min(100.0,100.0*(1.0-mae/(goal*4.0))))
    promoted=10.0 if bool(run["promoted"]) else 0.0
    return int(round(min(100.0,evidence*.45+validation*.45+promoted)))

def _direction(latest, previous):
    if latest is None or previous is None or latest["mae"] is None or previous["mae"] is None: return "stable"
    a,b=_finite(latest["mae"]),_finite(previous["mae"])
    if a is None or b is None or b<=0: return "stable"
    if a/b<=.98: return "improving"
    if a/b>=1.02: return "declining"
    return "stable"

def _mae_display(model_name, mae):
    if mae is None: return None, MODEL_SPECS[model_name]["unit"]
    v=float(mae); unit=MODEL_SPECS[model_name]["unit"]
    if unit=="C": return round(v*9/5,2),"°F"
    return round(v,2),unit

def _prediction_display(p):
    out=dict(p)
    if out.get("error"): return out
    if out.get("unit")=="C":
        if out.get("value") is not None: out["value_display"]=round(float(out["value"])*9/5+32,1)
        if out.get("mae") is not None: out["mae_display"]=round(float(out["mae"])*9/5,2)
        out["unit_display"]="°F"
    else:
        out["value_display"]=None if out.get("value") is None else round(float(out["value"]),1)
        out["mae_display"]=None if out.get("mae") is None else round(float(out["mae"]),2)
        out["unit_display"]=out.get("unit") or ""
    return out

def _source_sample_counts(con):
    fields=sorted(set(TARGET_FIELDS.values()))
    expr=",".join([f"SUM(CASE WHEN {f} IS NOT NULL THEN 1 ELSE 0 END) AS {f}" for f in fields])
    row=con.execute(f"SELECT COUNT(*) AS n,{expr} FROM telemetry").fetchone()
    return {"total":int(row["n"] or 0),**{f:int(row[f] or 0) for f in fields}}

def _quality(con,total):
    fields=[
        ("battery_level","Battery SOC"),("usable_battery_level","Usable SOC"),("outside_temp_c","Outside temperature"),
        ("inside_temp_c","Cabin temperature"),("battery_temp_c","Pack temperature"),("module_temp_min_c","Module minimum"),
        ("module_temp_max_c","Module maximum"),("pack_voltage_v","Pack voltage"),("pack_current_a","Pack current"),
        ("battery_heater_on","Battery heater"),("charging_state","Charging state"),("charger_power_kw","Charge power"),
        ("power_kw","Vehicle power"),("pack_power_kw","Derived pack power"),("charge_input_kw","Derived charge input"),("module_temp_spread_c","Module spread"),("energy_remaining_kwh","Energy remaining")]
    if total<=0: return [{"field":f,"label":label,"rows":0,"pct":0.0} for f,label in fields]
    expr=",".join([f"SUM(CASE WHEN {f} IS NOT NULL THEN 1 ELSE 0 END) AS {f}" for f,_ in fields])
    row=con.execute(f"SELECT {expr} FROM telemetry").fetchone()
    return [{"field":f,"label":label,"rows":int(row[f] or 0),"pct":round(100.0*int(row[f] or 0)/total,1)} for f,label in fields]

def _build_model_payload(con, source_counts):
    run_rows=con.execute("SELECT * FROM model_runs ORDER BY trained_at ASC,id ASC").fetchall(); by_model=defaultdict(list)
    for r in run_rows: by_model[r["model_name"]].append(r)
    cards=[]
    for name,spec in MODEL_SPECS.items():
        runs=by_model.get(name,[]); latest=runs[-1] if runs else None; previous=runs[-2] if len(runs)>1 else None
        active=next((r for r in reversed(runs) if bool(r["promoted"])),None)
        source_rows=int(source_counts.get(spec["target"],0)); score_run=active or latest; readiness=_readiness(name,score_run,source_rows)
        mae_display,mae_unit=_mae_display(name,None if score_run is None else score_run["mae"])
        history=[{"ts":float(r["trained_at"]),"generation":int(r["generation"]),"readiness":_readiness(name,r,source_rows),"mae":_finite(r["mae"]),"promoted":bool(r["promoted"])} for r in runs[-14:]]
        cards.append({"name":name,"label":spec["label"],"target":spec["target"],"horizon_minutes":int(spec["horizon"]),"unit":spec["unit"],"regime":spec.get("regime"),
            "accent":MODEL_ACCENTS.get(name,"cyan"),"generation":0 if active is None else int(active["generation"]),"latest_generation":0 if latest is None else int(latest["generation"]),
            "backend":"sklearn_histgb" if active is None else active["backend"],"rows":0 if score_run is None else int(score_run["rows_total"]),
            "source_rows":source_rows,"mae":None if score_run is None else _finite(score_run["mae"]),"mae_display":mae_display,"mae_unit":mae_unit,
            "rmse":None if score_run is None else _finite(score_run["rmse"]),"r2":None if score_run is None else _finite(score_run["r2"]),
            "promoted":active is not None,"trained_at":None if score_run is None else float(score_run["trained_at"]),
            "candidate_mae":None if latest is None or active is latest else _finite(latest["mae"]),"candidate_generation":None if latest is None or active is latest else int(latest["generation"]),
            "validation_strategy":None if score_run is None or "validation_strategy" not in score_run.keys() else score_run["validation_strategy"],
            "feature_version":None if score_run is None or "feature_version" not in score_run.keys() else score_run["feature_version"],
            "readiness":readiness,"direction":_direction(latest,previous),"history":history})
    return cards,run_rows

def _checkpoint_payload(run_rows,source_counts):
    buckets=defaultdict(dict); bucket_times={}
    for r in run_rows:
        b=int(float(r["trained_at"])//600)*600; buckets[b][r["model_name"]]=r; bucket_times[b]=max(float(r["trained_at"]),bucket_times.get(b,0))
    out=[]
    for b in sorted(buckets)[-12:]:
        values={}; scores=[]
        for name,spec in MODEL_SPECS.items():
            r=buckets[b].get(name)
            if r is None: values[name]=None
            else:
                score=_readiness(name,r,int(source_counts.get(spec["target"],0))); values[name]=score; scores.append(score)
        out.append({"ts":bucket_times[b],"overall":None if not scores else int(round(sum(scores)/len(scores))),"models":values})
    return out

def _truth_payload(con):
    rows=con.execute("SELECT * FROM prediction_audit ORDER BY predicted_at DESC LIMIT 1000").fetchall()
    by=defaultdict(list); pending=missed=resolved=0
    for r in rows:
        st=r['status']; pending+=st=='pending'; missed+=st=='missed'; resolved+=st=='resolved'; by[r['model_name']].append(r)
    models=[]
    for name,spec in MODEL_SPECS.items():
        rr=[r for r in by.get(name,[]) if r['status']=='resolved' and r['abs_error'] is not None]
        allm=by.get(name,[]); mres=len(rr); mmiss=sum(r['status']=='missed' for r in allm); mpend=sum(r['status']=='pending' for r in allm)
        if spec['unit']=='C': tol=3/1.8; factor=1.8; unit='°F'
        else: tol=2.5; factor=1.0; unit='%'
        mae=(sum(float(r['abs_error']) for r in rr)/mres) if mres else None
        bias=(sum(float(r['signed_error']) for r in rr)/mres) if mres else None
        hit=(100.0*sum(float(r['abs_error'])<=tol for r in rr)/mres) if mres else None
        coverage=(100.0*mres/(mres+mmiss)) if mres+mmiss else None
        # Trust is deliberately not called accuracy: it rewards real resolved evidence,
        # hit rate and resolution coverage and is capped until evidence accumulates.
        trust=0
        if mres:
            trust=int(round(min(100, min(40,mres/25*40) + (hit or 0)*.45 + (coverage or 0)*.15)))
        models.append({'name':name,'label':spec['label'],'resolved':mres,'pending':mpend,'missed':mmiss,'mae':None if mae is None else round(mae*factor,2),
            'bias':None if bias is None else round(bias*factor,2),'unit':unit,'hit_rate':None if hit is None else round(hit,1),
            'coverage':None if coverage is None else round(coverage,1),'trust':trust})
    recent=[]
    for r in rows[:40]:
        spec=MODEL_SPECS.get(r['model_name'],{}); unit=spec.get('unit',''); factor=1.8 if unit=='C' else 1.0; offset=32 if unit=='C' else 0
        pred=float(r['predicted_value']); actual=r['actual_value']
        recent.append({'predicted_at':float(r['predicted_at']),'target_ts':float(r['target_ts']),'model':r['model_name'],'label':spec.get('label',r['model_name']),
            'generation':int(r['generation']),'status':r['status'],'predicted':round(pred*factor+offset,2) if unit=='C' else round(pred,2),
            'actual':None if actual is None else (round(float(actual)*factor+offset,2) if unit=='C' else round(float(actual),2)),
            'error':None if r['abs_error'] is None else round(float(r['abs_error'])*factor,2),'unit':'°F' if unit=='C' else unit})
    scored=[m for m in models if m['resolved']]
    overall=int(round(sum(m['trust'] for m in scored)/len(scored))) if scored else 0
    return {'overall_trust':overall,'resolved':resolved,'pending':pending,'missed':missed,'models':models,'recent':recent}

def _slope(points,key):
    pts=[(float(r['ts']),_finite(r[key])) for r in points if r[key] is not None]
    pts=[p for p in pts if p[1] is not None]
    if len(pts)<3: return None
    t0=pts[0][0]; xs=[(t-t0)/3600 for t,_ in pts]; ys=[y for _,y in pts]
    xm=sum(xs)/len(xs); ym=sum(ys)/len(ys); den=sum((x-xm)**2 for x in xs)
    if den<=0: return None
    c_per_hr=sum((x-xm)*(y-ym) for x,y in zip(xs,ys))/den
    return round(c_per_hr*1.8,2)

def _thermal_payload(con,latest):
    if latest is None: return {'series':[],'current':{},'stats':{}}
    car=latest['car_id']; now=float(latest['ts']); since=now-48*3600
    rows=con.execute('''SELECT ts,outside_temp_c,inside_temp_c,battery_temp_c,module_temp_min_c,module_temp_max_c,battery_level,
                        battery_heater_on,climate_on,speed_kmh,pack_voltage_v,pack_current_a,energy_remaining_kwh
                        FROM telemetry WHERE car_id=? AND ts>=? ORDER BY ts''',(car,since)).fetchall()
    step=max(1,math.ceil(len(rows)/280)); sampled=rows[::step]
    if rows and sampled[-1]['ts']!=rows[-1]['ts']: sampled.append(rows[-1])
    series=[{'ts':float(r['ts']),'outside_f':f2(r['outside_temp_c']),'cabin_f':f2(r['inside_temp_c']),'pack_f':f2(r['battery_temp_c']),
             'module_min_f':f2(r['module_temp_min_c']),'module_max_f':f2(r['module_temp_max_c']),'soc':_finite(r['battery_level']),
             'heater':bool(r['battery_heater_on']) if r['battery_heater_on'] is not None else None} for r in sampled]
    parked=[r for r in rows if (r['speed_kmh'] is None or abs(float(r['speed_kmh']))<1) and not bool(r['climate_on']) and float(r['ts'])>=now-6*3600]
    mn=_finite(latest['module_temp_min_c']); mx=_finite(latest['module_temp_max_c'])
    current={'pack_f':f2(latest['battery_temp_c']),'outside_f':f2(latest['outside_temp_c']),'cabin_f':f2(latest['inside_temp_c']),
             'module_min_f':f2(mn),'module_max_f':f2(mx),'module_spread_f':None if mn is None or mx is None else round((mx-mn)*1.8,2),
             'pack_voltage_v':_finite(latest['pack_voltage_v']),'pack_current_a':_finite(latest['pack_current_a']),
             'energy_remaining_kwh':_finite(latest['energy_remaining_kwh']),'battery_heater_on':bool(latest['battery_heater_on']) if latest['battery_heater_on'] is not None else None}
    seven=now-7*86400
    st=con.execute('''SELECT MIN(outside_temp_c) min_out,MIN(battery_temp_c) min_pack,
        SUM(CASE WHEN outside_temp_c<0 THEN 1 ELSE 0 END) freezing_samples,
        SUM(CASE WHEN battery_heater_on=1 THEN 1 ELSE 0 END) heater_samples,
        SUM(CASE WHEN battery_temp_c IS NOT NULL THEN 1 ELSE 0 END) thermal_rows
        FROM telemetry WHERE car_id=? AND ts>=?''',(car,seven)).fetchone()
    pack=_finite(latest['battery_temp_c']); outside=_finite(latest['outside_temp_c']); current_a=_finite(latest['pack_current_a'])
    stress='UNKNOWN'
    if current_a is not None:
        a=abs(current_a); stress='LOW' if a<50 else 'MODERATE' if a<150 else 'HIGH'
    stats={'pack_cooling_f_per_hr':_slope(parked,'battery_temp_c'),'cabin_cooling_f_per_hr':_slope(parked,'inside_temp_c'),
           'pack_to_ambient_f':None if pack is None or outside is None else round((pack-outside)*1.8,1),
           'coldest_outside_7d_f':f2(st['min_out']),'coldest_pack_7d_f':f2(st['min_pack']),
           'freezing_samples_7d':int(st['freezing_samples'] or 0),'heater_samples_7d':int(st['heater_samples'] or 0),
           'thermal_rows_7d':int(st['thermal_rows'] or 0),'battery_stress':stress}
    return {'series':series,'current':current,'stats':stats}

def _neural_payload(quality,total,span_days):
    q={x['field']:x['pct'] for x in quality}; essential=[q.get('battery_level',0),q.get('outside_temp_c',0),q.get('inside_temp_c',0),q.get('battery_temp_c',0)]
    completeness=sum(essential)/len(essential); row_score=min(100,total/10000*100); span_score=min(100,span_days/30*100)
    score=int(round(row_score*.5+completeness*.3+span_score*.2))
    state='READY FOR EXPERIMENT' if score>=80 else 'CANDIDATE SOON' if score>=55 else 'COLLECTING'
    return {'score':score,'state':state,'row_score':round(row_score,1),'completeness':round(completeness,1),'span_score':round(span_score,1),'target_rows':10000}

def _insights(latest,model_cards,count,truth,thermal,backfill):
    items=[]
    if latest is None:
        return [{'level':'high','icon':'database','title':'Waiting for vehicle data','detail':'No Tesla telemetry has reached the local learning database yet.'}]
    outside_f=f2(latest['outside_temp_c']); pack_f=f2(latest['battery_temp_c']); sample_age=age(latest['ts'])
    if backfill.get('status')=='running': items.append({'level':'good','icon':'database','title':'Historical bootstrap is running','detail':f"Imported {backfill.get('inserted',0):,} new states so far."})
    if sample_age is not None and sample_age>900: items.append({'level':'info','icon':'clock','title':'Vehicle sample is cached/stale','detail':f'Latest real telemetry is {sample_age//60} minutes old; this is normal while the Tesla sleeps.'})
    if outside_f is not None and outside_f<32: items.append({'level':'warn','icon':'snow','title':'Freezing conditions are feeding the learner','detail':f'Outside temperature is {outside_f:.1f}°F.'})
    if pack_f is None: items.append({'level':'info','icon':'thermo','title':'Waiting for pack thermal telemetry','detail':'Historical Tessie states can supply module min/max and unlock Pack Thermal AI.'})
    if thermal.get('current',{}).get('module_spread_f') is not None and thermal['current']['module_spread_f']>8: items.append({'level':'warn','icon':'thermo','title':'Module temperature spread elevated','detail':f"Current module spread is {thermal['current']['module_spread_f']:.1f}°F."})
    if truth.get('resolved',0)==0 and any(m['promoted'] for m in model_cards): items.append({'level':'info','icon':'brain','title':'Truth Engine armed','detail':'Production predictions are now being frozen and will be scored when their future observations arrive.'})
    waiting=[m for m in model_cards if m['generation']==0]
    if waiting: items.append({'level':'info','icon':'brain','title':f"{len(waiting)} model{'s' if len(waiting)!=1 else ''} still collecting",'detail':'Historical bootstrap and new telemetry will increase time-shifted training evidence.'})
    if not items: items.append({'level':'good','icon':'check','title':'Learning pipeline looks healthy','detail':f'{count:,} local telemetry samples are available and production truth scoring is active.'})
    return items[:6]

@app.get('/')
def index(): return render_template('index.html',version=VERSION)

@app.get('/api/health')
def health(): return jsonify({'ok':True,'version':VERSION,'time':time.time()})

@app.get('/api/status')
def status():
    db.init_db()
    with db.connect() as con:
        latest=con.execute('SELECT * FROM telemetry ORDER BY ts DESC LIMIT 1').fetchone()
        count=int(con.execute('SELECT COUNT(*) n FROM telemetry').fetchone()['n'] or 0)
        first=con.execute('SELECT MIN(ts) t FROM telemetry').fetchone()['t']; last=con.execute('SELECT MAX(ts) t FROM telemetry').fetchone()['t']
        source_counts=_source_sample_counts(con); quality=_quality(con,count); model_cards,run_rows=_build_model_payload(con,source_counts); checkpoints=_checkpoint_payload(run_rows,source_counts)
        truth=_truth_payload(con); thermal=_thermal_payload(con,latest)
    car=None
    if latest:
        car={k:latest[k] for k in latest.keys() if k not in {'raw_json','car_id'}}
        car['vin_tail']=str(latest['car_id'] or '')[-6:]
        car.update({'outside_temp_f':f2(latest['outside_temp_c']),'inside_temp_f':f2(latest['inside_temp_c']),'battery_temp_f':f2(latest['battery_temp_c']),
                    'module_temp_min_f':f2(latest['module_temp_min_c']),'module_temp_max_f':f2(latest['module_temp_max_c']),'age_seconds':age(latest['ts'])})
    source=db.get_state('source',{}) or {}; collector=db.get_state('collector',{}) or {}; tessie=db.get_state('tessie',{}) or {}; mqtt=db.get_state('mqtt',{}) or {}
    training=db.get_state('training',{}) or {}; backfill=db.get_state('backfill',{}) or {}; truth_state=db.get_state('truth_engine',{}) or {}
    promoted=[m for m in model_cards if m['promoted']]; improving=[m for m in model_cards if m['direction']=='improving']; latest_model=max((m for m in model_cards if m['trained_at']),key=lambda x:x['trained_at'],default=None)
    readiness=int(round(sum(m['readiness'] for m in model_cards)/len(model_cards))) if model_cards else 0
    pipeline={'collecting':0,'training':0,'validating':0,'promoted':0,'predicting':0}
    for m in model_cards:
        if m['generation']==0: pipeline['collecting']+=1
        elif m['promoted']: pipeline['promoted']+=1; pipeline['predicting']+=1
        else: pipeline['validating']+=1
    if training.get('status')=='running': pipeline['training']=len(model_cards)
    predictions=[_prediction_display(p) for p in current_predictions()]
    try: db_size=config.DB_PATH.stat().st_size
    except Exception: db_size=0
    model_bytes=0
    try:
        for p in Path(config.MODEL_DIR).rglob('*'):
            if p.is_file(): model_bytes+=p.stat().st_size
    except Exception: pass
    finished=training.get('finished_at'); last_train_at=float(finished) if finished else (latest_model['trained_at'] if latest_model else None)
    span_days=0.0 if not first or not last else max(0.0,(float(last)-float(first))/86400.0)
    recent_runs=[]
    for r in run_rows[-40:][::-1]:
        md,mu=_mae_display(r['model_name'],r['mae']); recent_runs.append({'model':r['model_name'],'label':MODEL_SPECS.get(r['model_name'],{}).get('label',r['model_name']),
            'generation':int(r['generation']),'trained_at':float(r['trained_at']),'rows':int(r['rows_total']),'mae_display':md,'mae_unit':mu,'promoted':bool(r['promoted'])})
    neural=_neural_payload(quality,count,span_days); insights=_insights(latest,model_cards,count,truth,thermal,backfill)
    try:
        from .neural_governor import status as neural_governor_status
        neural_governor=neural_governor_status()
    except Exception as e:
        neural_governor={'enabled':False,'error':f'{type(e).__name__}: {e}'}
    return jsonify({'version':VERSION,'telemetry_rows':count,'first_sample_at':first,'last_sample_at':last,'dataset_span_days':round(span_days,2),'latest':car,
        'mqtt':mqtt,'tessie':tessie,'source':source,'collector':collector,'training':training,'backfill':backfill,'truth_state':truth_state,'truth':truth,'thermal':thermal,'neural':neural,'neural_governor':neural_governor,
        'models':model_cards,'predictions':predictions,'checkpoints':checkpoints,'quality':quality,'insights':insights,'recent_runs':recent_runs,
        'summary':{'readiness':readiness,'promoted_models':len(promoted),'improving_models':len(improving),'training_evidence':count,'latest_model':latest_model,'last_train_at':last_train_at,
                   'pipeline':pipeline,'min_train_rows':int(config.MIN_TRAIN_ROWS),'db_size_bytes':db_size,'model_size_bytes':model_bytes},
        'system':_system_status(),
        'ecoflow':_ecoflow_status(),
        'neural_backend':'governed_pytorch_gru_with_tree_fallback','local_db':str(config.DB_PATH)})

@app.post('/api/train')
def train():
    if (config.DATA_DIR/'training.lock').exists(): return jsonify({'ok':False,'status':'busy'}),409
    subprocess.Popen([sys.executable,'-m','ghost_tesla_ai.trainer','--model','all'],cwd='/opt/ghost-tesla-ai',stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    return jsonify({'ok':True,'status':'started'})

@app.post('/api/backfill')
def backfill():
    cur=db.get_state('backfill',{}) or {}
    if cur.get('status')=='running': return jsonify({'ok':False,'status':'busy'}),409
    body=request.get_json(silent=True) or {}; days=max(1,min(int(body.get('days',30)),365)); interval=max(60,min(int(body.get('interval',300)),3600))
    subprocess.Popen([sys.executable,'-m','ghost_tesla_ai.backfill','--days',str(days),'--interval',str(interval),'--train-after'],cwd='/opt/ghost-tesla-ai',stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    return jsonify({'ok':True,'status':'started','days':days,'interval':interval})

@app.post('/api/audit')
def audit():
    from .prediction_audit import resolve_due_predictions
    return jsonify({'ok':True,**resolve_due_predictions()})

if __name__=='__main__':
    db.init_db(); app.run(host=config.HOST,port=config.PORT,threaded=True)

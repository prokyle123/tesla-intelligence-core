from __future__ import annotations
import json,math,time
from pathlib import Path
from . import db
from .features import MODEL_SPECS,LEGACY_FEATURES,live_vector,spec_applicable
from .backends.sklearn_histgb import SklearnHistGBBackend

_MODEL_CACHE={}

def _load(path:str):
    p=Path(path); key=(str(p),p.stat().st_mtime if p.exists() else 0)
    if key not in _MODEL_CACHE:
        _MODEL_CACHE[key]=SklearnHistGBBackend.load(path)
        if len(_MODEL_CACHE)>16:
            # Keep current artifacts hot without letting stale generations accumulate forever.
            for k in list(_MODEL_CACHE)[:-8]:_MODEL_CACHE.pop(k,None)
    return _MODEL_CACHE[key]

def _features(run):
    try:
        v=json.loads(run['features_json'] or '[]'); return v if isinstance(v,list) and v else LEGACY_FEATURES
    except Exception:return LEGACY_FEATURES

def capture_predictions(source_telemetry_id:int)->int:
    db.init_db()
    with db.connect() as con:
        row=con.execute('SELECT * FROM telemetry WHERE id=?',(int(source_telemetry_id),)).fetchone(); runs=con.execute('SELECT * FROM model_runs WHERE promoted=1 ORDER BY model_name').fetchall()
    if not row or not runs:return 0
    made=0
    with db.connect() as con:
        for r in runs:
            spec=MODEL_SPECS.get(r['model_name'])
            if not spec or not r['artifact_path']:continue
            if not spec_applicable(spec,row):continue
            try:
                pred=float(_load(r['artifact_path']).predict([live_vector(row,_features(r))])[0])
                if not math.isfinite(pred):continue
                cur=con.execute('''INSERT OR IGNORE INTO prediction_audit(predicted_at,target_ts,model_name,generation,horizon_minutes,target_field,predicted_value,source_telemetry_id,status)
                                   VALUES(?,?,?,?,?,?,?,?, 'pending')''',(float(row['ts']),float(row['ts'])+int(spec['horizon'])*60,r['model_name'],int(r['generation']),int(spec['horizon']),spec['target'],pred,int(row['id'])))
                if cur.rowcount==1:made+=1
            except Exception:continue
    return made

def _tolerance_seconds(horizon_minutes:int)->float:
    return max(600.0,min(3600.0,horizon_minutes*60*0.20))

def resolve_due_predictions(now_ts:float|None=None)->dict:
    db.init_db(); now_ts=float(now_ts or time.time()); resolved=missed=0
    with db.connect() as con:
        due=con.execute("SELECT * FROM prediction_audit WHERE status='pending' AND target_ts<=? ORDER BY target_ts LIMIT 1000",(now_ts,)).fetchall()
        allowed={spec['target'] for spec in MODEL_SPECS.values()}
        for a in due:
            src=con.execute('SELECT car_id FROM telemetry WHERE id=?',(a['source_telemetry_id'],)).fetchone(); car=None if not src else src['car_id']; tol=_tolerance_seconds(int(a['horizon_minutes'])); field=a['target_field']
            if field not in allowed:continue
            cand=con.execute(f'''SELECT id,ts,{field} AS actual FROM telemetry WHERE car_id=? AND {field} IS NOT NULL AND ts BETWEEN ? AND ? ORDER BY ABS(ts-?) ASC LIMIT 1''',(car,float(a['target_ts'])-tol,float(a['target_ts'])+tol,float(a['target_ts']))).fetchone()
            if cand:
                actual=float(cand['actual']); pred=float(a['predicted_value']); signed=pred-actual
                con.execute("UPDATE prediction_audit SET actual_value=?,signed_error=?,abs_error=?,actual_telemetry_id=?,resolved_at=?,resolution_gap_seconds=?,status='resolved' WHERE id=?",(actual,signed,abs(signed),int(cand['id']),time.time(),abs(float(cand['ts'])-float(a['target_ts'])),int(a['id']))); resolved+=1
            elif now_ts>float(a['target_ts'])+tol:
                con.execute("UPDATE prediction_audit SET resolved_at=?,status='missed' WHERE id=?",(time.time(),int(a['id']))); missed+=1
    return {'resolved':resolved,'missed':missed}

def on_new_sample(source_telemetry_id:int)->dict:
    try:
        with db.connect() as con:r=con.execute('SELECT ts FROM telemetry WHERE id=?',(int(source_telemetry_id),)).fetchone()
        res=resolve_due_predictions(float(r['ts']) if r else None); res['captured']=capture_predictions(source_telemetry_id); db.set_state('truth_engine',{'status':'online','at':time.time(),**res}); return res
    except Exception as e:
        out={'status':'error','at':time.time(),'error':f'{type(e).__name__}: {e}'}; db.set_state('truth_engine',out); return out

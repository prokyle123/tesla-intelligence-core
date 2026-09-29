from __future__ import annotations
import json, math, time
import numpy as np
from sklearn.metrics import mean_absolute_error,mean_squared_error,r2_score
from . import db,config
from .backends.sklearn_histgb import SklearnHistGBBackend

TRIP_FEATURES=['distance_mi','start_soc','start_pack_c','avg_outside_c','hour_sin','hour_cos']
PRECONDITION_FEATURES=['start_pack_c','outside_c','target_delta_c','start_soc','plugged_fraction','wall_kw','hour_sin','hour_cos']
SPECS={
 'trip_soc_drop':{'target':'soc_drop','label':'Trip SOC drop','unit':'%','kind':'trip','features':TRIP_FEATURES,'min_rows':20},
 'trip_energy_kwh':{'target':'energy_kwh','label':'Trip energy','unit':'kWh','kind':'trip','features':TRIP_FEATURES,'min_rows':20},
 'precondition_duration_min':{'target':'duration_min','label':'Preconditioning duration','unit':'min','kind':'precondition','features':PRECONDITION_FEATURES,'min_rows':40},
}

def _f(v):
    try:
        x=float(v);return x if math.isfinite(x) else None
    except Exception:return None

def _metadata(r):
    try:
        d=json.loads(r['metadata_json'] or '{}')
        return d if isinstance(d,dict) else {}
    except Exception:return {}

def _clock(ts):
    lt=time.localtime(float(ts));hour=lt.tm_hour+lt.tm_min/60;a=2*math.pi*hour/24
    return math.sin(a),math.cos(a)

def _trip_features(r):
    hs,hc=_clock(r['start_ts'])
    return [float(r['distance_km'])*0.621371,float(r['start_soc']),float(r['start_pack_c']),float(r['avg_outside_c']),hs,hc]

def _precondition_features(r):
    meta=_metadata(r);hs,hc=_clock(r['start_ts'])
    start_soc=_f(r['start_soc']);plugged=_f(meta.get('plugged_fraction'));wall=_f(r['avg_charge_power_kw'])
    return [float(r['start_pack_c']),float(r['avg_outside_c']),float(r['pack_change_c']),50.0 if start_soc is None else start_soc,
            0.0 if plugged is None else plugged,0.0 if wall is None else wall,hs,hc]

def _dataset(name):
    spec=SPECS[name]
    with db.connect() as con:
        if spec['kind']=='precondition':
            rows=con.execute("""SELECT * FROM vehicle_events WHERE event_type='precondition'
                                AND duration_min IS NOT NULL AND start_pack_c IS NOT NULL
                                AND pack_change_c IS NOT NULL AND avg_outside_c IS NOT NULL ORDER BY start_ts""").fetchall()
        else:
            rows=con.execute("""SELECT * FROM vehicle_events WHERE event_type='drive' AND distance_km>=3
                                AND start_soc IS NOT NULL AND start_pack_c IS NOT NULL
                                AND avg_outside_c IS NOT NULL ORDER BY start_ts""").fetchall()
    X=[];y=[];ts=[]
    for r in rows:
        if spec['kind']=='precondition':
            dur=_f(r['duration_min']);delta=_f(r['pack_change_c'])
            if dur is None or delta is None or dur<5 or dur>120 or delta<0.5 or delta>25:continue
            X.append(_precondition_features(r));y.append(dur);ts.append(float(r['start_ts']))
        elif name=='trip_soc_drop':
            ch=_f(r['soc_change'])
            if ch is None or ch>=0 or -ch>70:continue
            X.append(_trip_features(r));y.append(-ch);ts.append(float(r['start_ts']))
        else:
            target=_f(r['energy_used_kwh'])
            if target is None or target<=0 or target>100:continue
            X.append(_trip_features(r));y.append(target);ts.append(float(r['start_ts']))
    return X,y,ts

def _next_gen(name):
    with db.connect() as con:r=con.execute('SELECT MAX(generation) g FROM event_model_runs WHERE model_name=?',(name,)).fetchone()
    return int((r['g'] or 0)+1)

def _active(name):
    with db.connect() as con:return con.execute('SELECT * FROM event_model_runs WHERE model_name=? AND promoted=1 ORDER BY generation DESC LIMIT 1',(name,)).fetchone()

def _precondition_rate_baseline(Xtr,ytr,Xte,yte):
    rates=[]
    for x,dur in zip(Xtr,ytr):
        delta=float(x[2]);hours=float(dur)/60.0
        if delta>0 and hours>0:rates.append(delta/hours)
    if not rates:return None
    rate=float(np.median(np.asarray(rates,float)))
    if rate<=0.05:return None
    bp=np.asarray([max(0.0,float(x[2])/rate*60.0) for x in Xte],float)
    return float(mean_absolute_error(np.asarray(yte,float),bp))

def train_one(name):
    spec=SPECS[name];X,y,ts=_dataset(name);n=len(y);need=int(spec.get('min_rows',20))
    if n<need:return {'model':name,'status':'waiting','rows':n,'need':need}
    split=max(12,int(n*.8));split=min(split,n-5)
    Xtr,Xte=np.asarray(X[:split],float),np.asarray(X[split:],float);ytr,yte=np.asarray(y[:split],float),np.asarray(y[split:],float)
    model=SklearnHistGBBackend().fit(Xtr,ytr);pred=model.predict(Xte)
    mae=float(mean_absolute_error(yte,pred));rmse=float(math.sqrt(mean_squared_error(yte,pred)));r2=float(r2_score(yte,pred)) if len(yte)>1 else float('nan')
    gen=_next_gen(name);d=config.MODEL_DIR/'event_models'/name;d.mkdir(parents=True,exist_ok=True);artifact=d/f'gen-{gen:04d}.joblib';model.save(artifact)
    old=_active(name);fallback_mae=_precondition_rate_baseline(Xtr,ytr,Xte,yte) if spec['kind']=='precondition' else None
    if old is not None and old['mae'] is not None:
        baseline=float(old['mae']);promote=mae<=baseline*(1.0-config.PROMOTE_IMPROVEMENT);comparison=f'previous champion MAE={baseline:.4f}'
    elif fallback_mae is not None:
        baseline=float(fallback_mae);promote=mae<=baseline;comparison=f'learned heat-rate fallback MAE={baseline:.4f}'
    else:
        baseline=None;promote=True;comparison='no prior baseline'
    note=('chronological event-level holdout; preconditioning duration from observed thermal events; ' if spec['kind']=='precondition'
          else 'chronological event-level holdout; whole drives only; ')+comparison
    with db.connect() as con:
        if promote:con.execute('UPDATE event_model_runs SET promoted=0 WHERE model_name=?',(name,))
        con.execute("""INSERT INTO event_model_runs(model_name,generation,trained_at,rows_total,rows_train,rows_test,mae,rmse,r2,promoted,artifact_path,features_json,target,notes)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (name,gen,time.time(),n,len(ytr),len(yte),mae,rmse,r2,int(promote),str(artifact),json.dumps(spec['features']),spec['target'],note))
    return {'model':name,'status':'trained','generation':gen,'rows':n,'mae':mae,'rmse':rmse,'r2':r2,'promoted':promote,'comparison_baseline_mae':baseline,'fallback_mae':fallback_mae}

def train_all():
    out=[]
    for name in SPECS:
        try:out.append(train_one(name))
        except Exception as e:out.append({'model':name,'status':'error','error':f'{type(e).__name__}: {e}'})
    state={'finished_at':time.time(),'results':out};db.set_state('trip_models',state);db.set_state('event_models',state);return out

def model_status():
    out=[]
    with db.connect() as con:
        for name,spec in SPECS.items():
            r=con.execute('SELECT * FROM event_model_runs WHERE model_name=? AND promoted=1 ORDER BY generation DESC LIMIT 1',(name,)).fetchone()
            out.append({'name':name,'label':spec['label'],'unit':spec['unit'],'kind':spec['kind'],'generation':0 if not r else int(r['generation']),
                        'rows':0 if not r else int(r['rows_total']),'mae':None if not r else _f(r['mae']),'r2':None if not r else _f(r['r2']),'promoted':bool(r)})
    return out

def current_trip_prediction(distance_mi,start_soc,start_pack_f,outside_f,departure_ts):
    if None in (distance_mi,start_soc,start_pack_f,outside_f,departure_ts):return {}
    hs,hc=_clock(departure_ts)
    X=[[float(distance_mi),float(start_soc),(float(start_pack_f)-32)*5/9,(float(outside_f)-32)*5/9,hs,hc]]
    out={}
    with db.connect() as con:
        for name in ('trip_soc_drop','trip_energy_kwh'):
            r=con.execute('SELECT * FROM event_model_runs WHERE model_name=? AND promoted=1 ORDER BY generation DESC LIMIT 1',(name,)).fetchone()
            if not r:continue
            try:
                val=float(SklearnHistGBBackend.load(r['artifact_path']).predict(X)[0])
                out[name]={'value':val,'mae':_f(r['mae']),'generation':int(r['generation']),'rows':int(r['rows_total'])}
            except Exception:pass
    if 'trip_soc_drop' in out:out['predicted_arrival_soc']=max(0,float(start_soc)-out['trip_soc_drop']['value'])
    if 'trip_energy_kwh' in out and float(distance_mi)>0:out['predicted_wh_per_mile']=out['trip_energy_kwh']['value']*1000/float(distance_mi)
    return out

def current_precondition_prediction(start_pack_f,target_pack_f,outside_f,plugged_in=False,wall_kw=None,start_soc=None,departure_ts=None):
    start=_f(start_pack_f);target=_f(target_pack_f);outside=_f(outside_f)
    if start is None or target is None or outside is None:return {}
    delta_f=target-start
    if delta_f<=0.25:return {'minutes':0,'raw_minutes':0.0,'source':'not_needed','confidence':'HIGH','target_delta_f':round(max(0.0,delta_f),1)}
    r=_active('precondition_duration_min')
    if not r or not r['artifact_path']:return {}
    ts=float(departure_ts or time.time());hs,hc=_clock(ts)
    start_c=(start-32)/1.8;outside_c=(outside-32)/1.8;delta_c=delta_f/1.8
    X=[[start_c,outside_c,delta_c,50.0 if _f(start_soc) is None else float(start_soc),1.0 if plugged_in else 0.0,
        0.0 if _f(wall_kw) is None else float(wall_kw),hs,hc]]
    try:
        raw=float(SklearnHistGBBackend.load(r['artifact_path']).predict(X)[0]);mae=_f(r['mae']);rows=int(r['rows_total'])
        cushion=2.0 if mae is None else min(8.0,max(2.0,mae*.35))
        minutes=max(1,min(90,int(math.ceil(raw+cushion))))
        confidence='HIGH' if rows>=100 and mae is not None and mae<=8 else ('MEDIUM' if rows>=60 and (mae is None or mae<=15) else 'LOW')
        return {'minutes':minutes,'raw_minutes':round(raw,1),'mae_min':None if mae is None else round(mae,1),'generation':int(r['generation']),'rows':rows,
                'source':'precondition_duration_ml','confidence':confidence,'target_delta_f':round(delta_f,1),'safety_cushion_min':round(cushion,1)}
    except Exception:return {}

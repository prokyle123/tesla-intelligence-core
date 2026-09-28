from __future__ import annotations
import json, math, time
import numpy as np
from sklearn.metrics import mean_absolute_error,mean_squared_error,r2_score
from . import db,config
from .backends.sklearn_histgb import SklearnHistGBBackend

FEATURES=['distance_mi','start_soc','start_pack_c','avg_outside_c','hour_sin','hour_cos']
SPECS={
 'trip_soc_drop':{'target':'soc_drop','label':'Trip SOC drop','unit':'%'},
 'trip_energy_kwh':{'target':'energy_kwh','label':'Trip energy','unit':'kWh'},
}

def _f(v):
    try:
        x=float(v);return x if math.isfinite(x) else None
    except Exception:return None

def _row_features(r):
    ts=float(r['start_ts']);lt=time.localtime(ts);hour=lt.tm_hour+lt.tm_min/60;a=2*math.pi*hour/24
    return [float(r['distance_km'])*0.621371,float(r['start_soc']),float(r['start_pack_c']),float(r['avg_outside_c']),math.sin(a),math.cos(a)]

def _dataset(name):
    with db.connect() as con:
        rows=con.execute("SELECT * FROM vehicle_events WHERE event_type='drive' AND distance_km>=3 AND start_soc IS NOT NULL AND start_pack_c IS NOT NULL AND avg_outside_c IS NOT NULL ORDER BY start_ts").fetchall()
    X=[];y=[];ts=[]
    for r in rows:
        if name=='trip_soc_drop':
            ch=_f(r['soc_change'])
            if ch is None or ch>=0 or -ch>70:continue
            target=-ch
        else:
            target=_f(r['energy_used_kwh'])
            if target is None or target<=0 or target>100:continue
        X.append(_row_features(r));y.append(target);ts.append(float(r['start_ts']))
    return X,y,ts

def _next_gen(name):
    with db.connect() as con:r=con.execute('SELECT MAX(generation) g FROM event_model_runs WHERE model_name=?',(name,)).fetchone()
    return int((r['g'] or 0)+1)

def _active(name):
    with db.connect() as con:return con.execute('SELECT * FROM event_model_runs WHERE model_name=? AND promoted=1 ORDER BY generation DESC LIMIT 1',(name,)).fetchone()

def train_one(name):
    X,y,ts=_dataset(name);n=len(y);need=20
    if n<need:return {'model':name,'status':'waiting','rows':n,'need':need}
    split=max(12,int(n*.8));split=min(split,n-5)
    Xtr=np.asarray(X[:split],float);Xte=np.asarray(X[split:],float);ytr=np.asarray(y[:split],float);yte=np.asarray(y[split:],float)
    model=SklearnHistGBBackend().fit(Xtr,ytr);pred=model.predict(Xte)
    mae=float(mean_absolute_error(yte,pred));rmse=float(math.sqrt(mean_squared_error(yte,pred)));r2=float(r2_score(yte,pred)) if len(yte)>1 else float('nan')
    gen=_next_gen(name);d=config.MODEL_DIR/'event_models'/name;d.mkdir(parents=True,exist_ok=True);artifact=d/f'gen-{gen:04d}.joblib';model.save(artifact)
    old=_active(name);promote=old is None or old['mae'] is None or mae<=float(old['mae'])*(1.0-config.PROMOTE_IMPROVEMENT)
    with db.connect() as con:
        if promote:con.execute('UPDATE event_model_runs SET promoted=0 WHERE model_name=?',(name,))
        con.execute('''INSERT INTO event_model_runs(model_name,generation,trained_at,rows_total,rows_train,rows_test,mae,rmse,r2,promoted,artifact_path,features_json,target,notes)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(name,gen,time.time(),n,len(ytr),len(yte),mae,rmse,r2,int(promote),str(artifact),json.dumps(FEATURES),SPECS[name]['target'],'chronological event-level holdout; whole drives only'))
    return {'model':name,'status':'trained','generation':gen,'rows':n,'mae':mae,'rmse':rmse,'r2':r2,'promoted':promote}

def train_all():
    out=[]
    for name in SPECS:
        try:out.append(train_one(name))
        except Exception as e:out.append({'model':name,'status':'error','error':f'{type(e).__name__}: {e}'})
    db.set_state('trip_models',{'finished_at':time.time(),'results':out});return out

def model_status():
    out=[]
    with db.connect() as con:
        for name,spec in SPECS.items():
            r=con.execute('SELECT * FROM event_model_runs WHERE model_name=? AND promoted=1 ORDER BY generation DESC LIMIT 1',(name,)).fetchone()
            out.append({'name':name,'label':spec['label'],'unit':spec['unit'],'generation':0 if not r else int(r['generation']),'rows':0 if not r else int(r['rows_total']),'mae':None if not r else _f(r['mae']),'r2':None if not r else _f(r['r2']),'promoted':bool(r)})
    return out

def current_trip_prediction(distance_mi,start_soc,start_pack_f,outside_f,departure_ts):
    if None in (distance_mi,start_soc,start_pack_f,outside_f,departure_ts):return {}
    lt=time.localtime(float(departure_ts));hour=lt.tm_hour+lt.tm_min/60;a=2*math.pi*hour/24
    X=[[float(distance_mi),float(start_soc),(float(start_pack_f)-32)*5/9,(float(outside_f)-32)*5/9,math.sin(a),math.cos(a)]]
    out={}
    with db.connect() as con:
        for name,spec in SPECS.items():
            r=con.execute('SELECT * FROM event_model_runs WHERE model_name=? AND promoted=1 ORDER BY generation DESC LIMIT 1',(name,)).fetchone()
            if not r:continue
            try:
                val=float(SklearnHistGBBackend.load(r['artifact_path']).predict(X)[0]);out[name]={'value':val,'mae':_f(r['mae']),'generation':int(r['generation']),'rows':int(r['rows_total'])}
            except Exception:pass
    if 'trip_soc_drop' in out:out['predicted_arrival_soc']=max(0,float(start_soc)-out['trip_soc_drop']['value'])
    if 'trip_energy_kwh' in out and float(distance_mi)>0:out['predicted_wh_per_mile']=out['trip_energy_kwh']['value']*1000/float(distance_mi)
    return out

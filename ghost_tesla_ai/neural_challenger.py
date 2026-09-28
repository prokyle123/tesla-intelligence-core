from __future__ import annotations
import json, math, time
import numpy as np
from sklearn.metrics import mean_absolute_error,mean_squared_error,r2_score
from . import config,db
from .features import MODEL_SPECS,V3_FEATURES,FEATURE_VERSION,build_dataset
from .backends.sklearn_mlp import SklearnMLPBackend

CHALLENGE_MODELS=('soc_60m','pack_temp_60m')

def _next(model_name):
    with db.connect() as con:
        r=con.execute('SELECT MAX(generation) g FROM challenger_runs WHERE model_name=?',(model_name,)).fetchone()
    return int((r['g'] or 0)+1)

def _split(ts,n):
    days=[time.strftime('%Y-%m-%d',time.localtime(t)) for t in ts]
    uniq=[]
    for d in days:
        if not uniq or uniq[-1]!=d: uniq.append(d)
    if len(uniq)>=5:
        cut=uniq[-max(1,int(math.ceil(len(uniq)*.2)))]
        i=next((i for i,d in enumerate(days) if d>=cut),int(n*.8))
        if i>=20 and n-i>=20:return i,'day-blocked chronological holdout'
    return max(1,min(n-20,int(n*.8))),'row-ordered fallback'

def train_challenger(name):
    X,y,ids,ts=build_dataset(name); n=len(y)
    if n<config.NEURAL_MIN_ROWS:
        return {'model':name,'status':'waiting','rows':n,'need':config.NEURAL_MIN_ROWS}
    split,strategy=_split(ts,n); Xtr=np.asarray(X[:split],float); Xte=np.asarray(X[split:],float); ytr=np.asarray(y[:split],float); yte=np.asarray(y[split:],float)
    model=SklearnMLPBackend().fit(Xtr,ytr); pred=model.predict(Xte)
    mae=float(mean_absolute_error(yte,pred)); rmse=float(math.sqrt(mean_squared_error(yte,pred))); r2=float(r2_score(yte,pred)) if len(yte)>1 else float('nan')
    gen=_next(name); d=config.MODEL_DIR/'challengers'/name; d.mkdir(parents=True,exist_ok=True); artifact=d/f'mlp-gen-{gen:04d}.joblib'; model.save(artifact)
    with db.connect() as con:
        con.execute('''INSERT INTO challenger_runs(model_name,backend,generation,trained_at,rows_total,rows_train,rows_test,mae,rmse,r2,artifact_path,features_json,validation_strategy,feature_version,notes)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(name,model.name,gen,time.time(),n,len(ytr),len(yte),mae,rmse,r2,str(artifact),json.dumps(V3_FEATURES),strategy,FEATURE_VERSION,'experimental only; never auto-promoted'))
        champ=con.execute('SELECT mae,generation,promoted FROM model_runs WHERE model_name=? AND feature_version=? ORDER BY generation DESC LIMIT 1',(name,FEATURE_VERSION)).fetchone()
    return {'model':name,'status':'trained','generation':gen,'rows':n,'mae':mae,'rmse':rmse,'r2':r2,'v3_baseline_mae':None if not champ else champ['mae'],'beats_v3_baseline':bool(champ and champ['mae'] is not None and mae<float(champ['mae']))}

def train_challengers():
    out=[]
    for name in CHALLENGE_MODELS:
        try: out.append(train_challenger(name))
        except Exception as e: out.append({'model':name,'status':'error','error':f'{type(e).__name__}: {e}'})
    db.set_state('neural_challenger',{'finished_at':time.time(),'results':out})
    return out

from __future__ import annotations
import argparse, json, math, os, time
from pathlib import Path
import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from . import config, db
from .features import MODEL_SPECS, V3_FEATURES, LEGACY_FEATURES, FEATURE_VERSION, build_dataset, row_to_features
from .backends.sklearn_histgb import SklearnHistGBBackend

LOCK=config.DATA_DIR/'training.lock'


def _version():
    try:
        return Path("/opt/ghost-tesla-ai/VERSION").read_text().strip() or "0.4.1"
    except Exception:
        return "0.4.1"

def active_run(model_name):
    with db.connect() as con:
        return con.execute('SELECT * FROM model_runs WHERE model_name=? AND promoted=1 ORDER BY generation DESC LIMIT 1',(model_name,)).fetchone()

def next_gen(model_name):
    with db.connect() as con:
        row=con.execute('SELECT MAX(generation) g FROM model_runs WHERE model_name=?',(model_name,)).fetchone()
    return int((row['g'] or 0)+1)

def _day_block_split(source_ts,n):
    if n<40: return max(1,n-20),'row-ordered fallback'
    days=[time.strftime('%Y-%m-%d',time.localtime(ts)) for ts in source_ts]
    unique=[]
    for d in days:
        if not unique or unique[-1]!=d: unique.append(d)
    if len(unique)<5:
        return max(1,min(n-20,int(n*.8))),'row-ordered fallback'
    test_days=max(1,int(math.ceil(len(unique)*.20)))
    cutoff_day=unique[-test_days]
    split=next((i for i,d in enumerate(days) if d>=cutoff_day),int(n*.8))
    if split<20 or n-split<20:
        return max(1,min(n-20,int(n*.8))),'row-ordered fallback'
    return split,f'day-blocked chronological holdout ({test_days} whole days)'

def _legacy_baseline_mae(old, test_source_ids, yte):
    """Score a pre-v0.3 champion on the exact v0.3 holdout before replacing it."""
    if old is None or not old['artifact_path'] or not test_source_ids:return None
    try:
        features=json.loads(old['features_json'] or '[]') or LEGACY_FEATURES
    except Exception:features=LEGACY_FEATURES
    try:
        model=SklearnHistGBBackend.load(old['artifact_path'])
        rows={}
        with db.connect() as con:
            ids=list(map(int,test_source_ids))
            for off in range(0,len(ids),800):
                chunk=ids[off:off+800]; qs=','.join('?' for _ in chunk)
                for r in con.execute(f'SELECT * FROM telemetry WHERE id IN ({qs})',chunk).fetchall():rows[int(r['id'])]=r
        X=[]; yy=[]
        for sid,y in zip(test_source_ids,yte):
            r=rows.get(int(sid))
            if r is None:continue
            X.append(row_to_features(r,features,[r])); yy.append(float(y))
        if len(yy)<20:return None
        pr=model.predict(np.asarray(X,dtype=float))
        return float(mean_absolute_error(np.asarray(yy,dtype=float),pr))
    except Exception:return None

def train_one(model_name: str):
    spec=MODEL_SPECS[model_name]
    X,y,source_ids,source_ts=build_dataset(model_name); n=len(y)
    need=max(int(spec.get('min_rows',config.MIN_TRAIN_ROWS)),40)
    if n<need:
        return {'model':model_name,'status':'waiting','rows':n,'need':need,'regime':spec.get('regime')}
    split,strategy=_day_block_split(source_ts,n)
    Xtr,Xte=np.asarray(X[:split],dtype=float),np.asarray(X[split:],dtype=float)
    ytr,yte=np.asarray(y[:split],dtype=float),np.asarray(y[split:],dtype=float)
    model=SklearnHistGBBackend().fit(Xtr,ytr); pred=model.predict(Xte)
    mae=float(mean_absolute_error(yte,pred)); rmse=float(math.sqrt(mean_squared_error(yte,pred)))
    r2=float(r2_score(yte,pred)) if len(yte)>1 else float('nan')
    gen=next_gen(model_name); outdir=config.MODEL_DIR/model_name; outdir.mkdir(parents=True,exist_ok=True)
    artifact=outdir/f'gen-{gen:04d}.joblib'; model.save(artifact)
    old=active_run(model_name)
    compare_mae=None
    if old is not None and ('feature_version' not in old.keys() or old['feature_version']!=FEATURE_VERSION):
        compare_mae=_legacy_baseline_mae(old,source_ids[split:],yte)
    baseline=compare_mae if compare_mae is not None else (None if old is None else old['mae'])
    promote=bool(config.AUTO_PROMOTE and (old is None or baseline is None or mae<=float(baseline)*(1.0-config.PROMOTE_IMPROVEMENT)))
    comparison_note='same-holdout legacy baseline MAE='+str(round(compare_mae,6)) if compare_mae is not None else 'standard champion comparison'
    # A brand-new regime specialist is allowed to become production when it clears
    # its evidence gate; established champions remain until a challenger improves.
    with db.connect() as con:
        if promote: con.execute('UPDATE model_runs SET promoted=0 WHERE model_name=?',(model_name,))
        con.execute('''INSERT INTO model_runs(model_name,backend,generation,trained_at,rows_total,rows_train,rows_test,mae,rmse,r2,promoted,artifact_path,features_json,target,horizon_minutes,notes,validation_strategy,test_start_ts,test_end_ts,regime,feature_version)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (model_name,model.name,gen,time.time(),n,len(ytr),len(yte),mae,rmse,r2,int(promote),str(artifact),json.dumps(V3_FEATURES),spec['target'],spec['horizon'],
                     'v0.3 contextual features + blocked validation; '+comparison_note,strategy,float(source_ts[split]) if split<len(source_ts) else None,float(source_ts[-1]) if source_ts else None,spec.get('regime'),FEATURE_VERSION))
    return {'model':model_name,'status':'trained','generation':gen,'rows':n,'train_rows':len(ytr),'test_rows':len(yte),'mae':mae,'rmse':rmse,'r2':r2,'promoted':promote,'validation':strategy,'regime':spec.get('regime'),'comparison_baseline_mae':compare_mae}

def train_all():
    db.init_db(); results=[]; config.DATA_DIR.mkdir(parents=True,exist_ok=True)
    if LOCK.exists() and time.time()-LOCK.stat().st_mtime<7200: return [{'status':'busy'}]
    LOCK.write_text(str(os.getpid())); db.set_state('training',{'status':'running','started_at':time.time(),'version':_version()})
    try:
        from .event_engine import rebuild_events
        try: event_result=rebuild_events(config.EVENT_LOOKBACK_DAYS)
        except Exception as e: event_result={'status':'error','error':f'{type(e).__name__}: {e}'}
        for name in MODEL_SPECS:
            try: results.append(train_one(name))
            except Exception as e: results.append({'model':name,'status':'error','error':f'{type(e).__name__}: {e}'})
        trip_models=[]
        try:
            from .event_models import train_all as train_trip_models
            trip_models=train_trip_models()
        except Exception as e:
            trip_models=[{'status':'error','error':f'{type(e).__name__}: {e}'}]
        neural=[]
        if config.NEURAL_CHALLENGER:
            try:
                from .neural_challenger import train_challengers
                neural=train_challengers()
            except Exception as e:
                neural=[{'status':'error','error':f'{type(e).__name__}: {e}'}]
        state={'status':'idle','finished_at':time.time(),'results':results,'event_refresh':event_result,'trip_models':trip_models,'neural_challengers':neural,'version':_version()}
        db.set_state('training',state)
        try:
            from .readiness import snapshot_readiness
            state['readiness_snapshot']=snapshot_readiness()
            db.set_state('training',state)
        except Exception: pass
        return results+([{'trip_models':trip_models}] if trip_models else [])+([{'neural_challengers':neural}] if neural else [])
    finally:
        try: LOCK.unlink()
        except FileNotFoundError: pass

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--model',choices=list(MODEL_SPECS)+['all'],default='all'); a=p.parse_args()
    print(json.dumps(train_all() if a.model=='all' else [train_one(a.model)],indent=2))

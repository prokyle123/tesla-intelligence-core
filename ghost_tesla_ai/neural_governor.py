from __future__ import annotations

import json
import math
import time
from . import config, db
from .neural_audit import metrics as truth_metrics

CRITICAL_HEADS = {'soc_60m','pack_60m','soc_180m','pack_180m','pack_360m'}
STAGES = ('TRAINED','SHADOW','TRUTH_QUALIFIED','CANARY','PRODUCTION','ROLLED_BACK','RETIRED')


def _json(v, default):
    try:
        x=json.loads(v) if isinstance(v,str) else v
        return x if x is not None else default
    except Exception:return default


def _latest_run():
    db.init_db()
    with db.connect() as con:
        return con.execute('SELECT * FROM neural_v4_runs ORDER BY generation DESC LIMIT 1').fetchone()


def _run(generation):
    with db.connect() as con:
        return con.execute('SELECT * FROM neural_v4_runs WHERE generation=? ORDER BY id DESC LIMIT 1',(int(generation),)).fetchone()


def _gov(generation):
    with db.connect() as con:
        return con.execute('SELECT * FROM neural_v4_governor WHERE generation=?',(int(generation),)).fetchone()


def _dict(row):
    return None if row is None else dict(row)


def _ensure(generation):
    now=time.time()
    with db.connect() as con:
        con.execute('''INSERT OR IGNORE INTO neural_v4_governor(generation,stage,created_at,updated_at,reason,payload_json)
                       VALUES(?,?,?,?,?,?)''',(int(generation),'TRAINED',now,now,'Awaiting same-holdout governor gate','{}'))
    return _gov(generation)


def _event(generation,from_stage,to_stage,event,detail=None):
    with db.connect() as con:
        con.execute('INSERT INTO neural_v4_governor_events(ts,generation,from_stage,to_stage,event,detail_json) VALUES(?,?,?,?,?,?)',
                    (time.time(),int(generation),from_stage,to_stage,event,json.dumps(detail or {},separators=(',',':'))))


def _update(generation, **fields):
    if not fields:return
    fields['updated_at']=time.time()
    cols=','.join(f'{k}=?' for k in fields)
    vals=list(fields.values())+[int(generation)]
    with db.connect() as con:
        con.execute(f'UPDATE neural_v4_governor SET {cols} WHERE generation=?',vals)


def _transition(generation,to_stage,reason,detail=None):
    row=_ensure(generation); frm=row['stage']
    if frm==to_stage:
        _update(generation,reason=reason,payload_json=json.dumps(detail or {},separators=(',',':')))
        return
    now=time.time(); fields={'stage':to_stage,'reason':reason,'payload_json':json.dumps(detail or {},separators=(',',':'))}
    if to_stage=='SHADOW':fields['shadow_started_at']=now
    elif to_stage=='TRUTH_QUALIFIED':fields['truth_qualified_at']=now
    elif to_stage=='CANARY':fields['canary_started_at']=now
    elif to_stage=='PRODUCTION':fields['production_started_at']=now
    elif to_stage=='ROLLED_BACK':fields['rolled_back_at']=now
    _update(generation,**fields)
    _event(generation,frm,to_stage,'stage_transition',{'reason':reason,**(detail or {})})


def production_generation():
    db.init_db()
    with db.connect() as con:
        r=con.execute("SELECT generation FROM neural_v4_governor WHERE stage='PRODUCTION' ORDER BY production_started_at DESC, generation DESC LIMIT 1").fetchone()
    return None if not r else int(r['generation'])


def _generation_target_names(generation):
    if generation is None:return set()
    run=_run(generation)
    if not run:return set()
    targets=_json(run['targets_json'],[])
    return {str(t.get('name')) for t in targets if isinstance(t,dict) and t.get('name')}


def _holdout_gate(run):
    if not run:return {'ready':False,'pass':False,'reason':'No neural generation.'}
    metrics=_json(run['metrics_json'],{})
    expected=max(5,len(metrics))
    head_rows=[]; passed=0; critical_ok=True; baselines=0
    for name,m in metrics.items():
        imp=m.get('improvement_pct')
        available=m.get('baseline_mae') is not None
        if available:baselines+=1
        imp_frac=(float(imp)/100.0) if imp is not None and math.isfinite(float(imp)) else None
        ok=bool(available and imp_frac is not None and imp_frac>=config.NEURAL_HOLDOUT_MIN_IMPROVEMENT)
        if ok:passed+=1
        if name in CRITICAL_HEADS and not ok:critical_ok=False
        head_rows.append({'name':name,'improvement_pct':imp,'baseline_available':available,'pass':ok})
    ready=baselines>=expected and len(metrics)>=expected
    passed_gate=bool(ready and passed>=config.NEURAL_HOLDOUT_MIN_HEADS and critical_ok)
    reason=(f'Holdout passed: {passed}/{expected} heads clear the champion gate.' if passed_gate else
            (f'Waiting for all {expected} production baselines on the same blocked holdout.' if not ready else f'Holdout blocked: {passed}/{expected} heads pass; all critical heads must win.'))
    return {'ready':ready,'pass':passed_gate,'passed_heads':passed,'expected_heads':expected,'critical_ok':critical_ok,'heads':head_rows,'reason':reason}


def _truth_gate(generation,since=None,min_per_head=None,min_improvement=None):
    min_per_head=int(min_per_head if min_per_head is not None else config.NEURAL_TRUTH_MIN_RESOLVED_PER_HEAD)
    min_improvement=float(min_improvement if min_improvement is not None else config.NEURAL_TRUTH_MIN_IMPROVEMENT)
    expected_names=_generation_target_names(generation)
    rows=truth_metrics(generation=generation,since=since)
    if expected_names:rows=[r for r in rows if r.get('name') in expected_names]
    expected=max(5,len(expected_names) or len(rows))
    passed=0; critical_ok=True; evidence_ok=True; comparable_total=0
    for r in rows:
        n=int(r.get('comparable') or 0); comparable_total+=n
        if n<min_per_head:evidence_ok=False
        imp=r.get('native_improvement')
        ok=bool(n>=min_per_head and imp is not None and float(imp)>=min_improvement)
        r['gate_pass']=ok
        if ok:passed+=1
        if r.get('name') in CRITICAL_HEADS and not ok:critical_ok=False
    ready=bool(len(rows)>=expected and evidence_ok)
    gate=bool(ready and passed>=config.NEURAL_HOLDOUT_MIN_HEADS and critical_ok)
    reason=(f'Live Truth passed: {passed}/{expected} heads beat the served production baseline.' if gate else
            (f'Collecting live Truth: need {min_per_head} baseline-comparable outcomes per head.' if not ready else f'Live Truth blocked: {passed}/{expected} heads pass; critical heads must improve.'))
    return {'ready':ready,'pass':gate,'passed_heads':passed,'expected_heads':expected,'critical_ok':critical_ok,'comparable_total':comparable_total,'min_per_head':min_per_head,'min_improvement_pct':round(min_improvement*100,2),'heads':rows,'reason':reason}


def _rollback_gate(generation,since):
    rows=truth_metrics(generation=generation,since=since)
    expected_names=_generation_target_names(generation)
    if expected_names:rows=[r for r in rows if r.get('name') in expected_names]
    ready=True; regressions=[]; mean_imps=[]
    for r in rows:
        if int(r.get('comparable') or 0)<config.NEURAL_ROLLBACK_MIN_NEW_PER_HEAD:
            ready=False
        imp=r.get('native_improvement')
        if imp is not None:
            mean_imps.append(float(imp))
            if r.get('name') in CRITICAL_HEADS and float(imp)<=-config.NEURAL_ROLLBACK_CRITICAL_REGRESSION:
                regressions.append({'name':r.get('name'),'regression_pct':round(-float(imp)*100,2)})
    mean_imp=(sum(mean_imps)/len(mean_imps)) if mean_imps else None
    rollback=bool(ready and (regressions or (mean_imp is not None and mean_imp<=-config.NEURAL_ROLLBACK_MEAN_REGRESSION)))
    return {'ready':ready,'rollback':rollback,'mean_improvement_pct':None if mean_imp is None else round(mean_imp*100,2),'critical_regressions':regressions,'heads':rows}


def _promote(generation, detail):
    # Keep tree champions intact as the safe fallback. Only one neural generation
    # can own the production overlay at a time.
    with db.connect() as con:
        others=con.execute("SELECT generation FROM neural_v4_governor WHERE stage='PRODUCTION' AND generation<>?",(int(generation),)).fetchall()
    for r in others:
        old=int(r['generation'])
        _transition(old,'RETIRED',f'Replaced by neural generation {generation}.',{'replacement_generation':int(generation)})
    _transition(generation,'PRODUCTION','All holdout, live Truth and canary gates passed.',detail)


def cycle():
    db.init_db()
    latest=_latest_run()
    if not config.NEURAL_GOVERNOR_ENABLED or not latest:
        state={'enabled':bool(config.NEURAL_GOVERNOR_ENABLED),'status':'waiting','reason':'No trained neural generation.' if not latest else 'Governor disabled.','at':time.time()}
        db.set_state('neural_governor',state);return state
    generation=int(latest['generation']); row=_ensure(generation); stage=row['stage']
    hold=_holdout_gate(latest)
    _update(generation,holdout_pass=int(bool(hold['pass'])))

    if stage=='TRAINED':
        if hold['pass']:
            _transition(generation,'SHADOW',hold['reason'],{'holdout':hold})
        else:
            _update(generation,reason=hold['reason'],payload_json=json.dumps({'holdout':hold},separators=(',',':')))
    elif stage=='SHADOW':
        truth=_truth_gate(generation)
        _update(generation,truth_pass=int(bool(truth['pass'])))
        if truth['pass']:
            _transition(generation,'TRUTH_QUALIFIED',truth['reason'],{'holdout':hold,'truth':truth})
        else:
            _update(generation,reason=truth['reason'],payload_json=json.dumps({'holdout':hold,'truth':truth},separators=(',',':')))
    elif stage=='TRUTH_QUALIFIED':
        _transition(generation,'CANARY','Truth-qualified challenger entered canary observation.',{'holdout':hold,'truth':_truth_gate(generation)})
    elif stage=='CANARY':
        row=_gov(generation); since=row['canary_started_at'] or row['updated_at']
        canary=_truth_gate(generation,since=since,min_per_head=config.NEURAL_CANARY_MIN_NEW_PER_HEAD,min_improvement=config.NEURAL_CANARY_MIN_IMPROVEMENT)
        _update(generation,canary_pass=int(bool(canary['pass'])))
        if canary['pass'] and config.NEURAL_GOVERNOR_AUTO_PROMOTE:
            _promote(generation,{'holdout':hold,'canary':canary})
        else:
            why=canary['reason'] if not canary['pass'] else 'Canary passed; automatic promotion is disabled.'
            _update(generation,reason=why,payload_json=json.dumps({'holdout':hold,'canary':canary},separators=(',',':')))

    # Rollback guard watches whichever neural generation is actually serving.
    prod=production_generation()
    rollback=None
    if prod is not None:
        prow=_gov(prod)
        since=prow['production_started_at'] if prow else None
        rollback=_rollback_gate(prod,since) if since else None
        if rollback and rollback['rollback']:
            _transition(prod,'ROLLED_BACK','Rollback guard detected sustained live Truth regression versus the fallback champion.',{'rollback':rollback})
        elif rollback:
            _update(prod,rollback_guard='ARMED' if rollback['ready'] else 'COLLECTING')

    state=status()
    state['at']=time.time();db.set_state('neural_governor',state);return state


def status():
    db.init_db(); latest=_latest_run(); latest_gen=int(latest['generation']) if latest else None
    challenger=None
    if latest_gen is not None:
        row=_ensure(latest_gen); hold=_holdout_gate(latest)
        truth=_truth_gate(latest_gen)
        since=row['canary_started_at'] if row and row['stage']=='CANARY' else None
        canary=_truth_gate(latest_gen,since=since,min_per_head=config.NEURAL_CANARY_MIN_NEW_PER_HEAD,min_improvement=config.NEURAL_CANARY_MIN_IMPROVEMENT) if since else None
        challenger={**dict(row),'holdout':hold,'truth':truth,'canary':canary}
        challenger['payload']=_json(challenger.pop('payload_json',None),{})
    prod=production_generation(); prod_row=_gov(prod) if prod is not None else None
    production=None
    if prod_row:
        production=dict(prod_row);production['payload']=_json(production.pop('payload_json',None),{})
        production['rollback']=_rollback_gate(prod,production.get('production_started_at')) if production.get('production_started_at') else None
    with db.connect() as con:
        ev=con.execute('SELECT * FROM neural_v4_governor_events ORDER BY ts DESC LIMIT 30').fetchall()
    timeline=[]
    for r in ev:
        d=dict(r);d['detail']=_json(d.pop('detail_json',None),{});timeline.append(d)
    return {
        'enabled':bool(config.NEURAL_GOVERNOR_ENABLED),
        'auto_promote':bool(config.NEURAL_GOVERNOR_AUTO_PROMOTE),
        'challenger':challenger,
        'production':production,
        'production_generation':prod,
        'fallback':'tree champions retained',
        'thresholds':{
            'holdout_min_heads':int(config.NEURAL_HOLDOUT_MIN_HEADS),
            'holdout_min_improvement_pct':round(config.NEURAL_HOLDOUT_MIN_IMPROVEMENT*100,2),
            'truth_min_resolved_per_head':int(config.NEURAL_TRUTH_MIN_RESOLVED_PER_HEAD),
            'truth_min_improvement_pct':round(config.NEURAL_TRUTH_MIN_IMPROVEMENT*100,2),
            'canary_min_new_per_head':int(config.NEURAL_CANARY_MIN_NEW_PER_HEAD),
            'canary_min_improvement_pct':round(config.NEURAL_CANARY_MIN_IMPROVEMENT*100,2),
            'rollback_min_new_per_head':int(config.NEURAL_ROLLBACK_MIN_NEW_PER_HEAD),
            'rollback_mean_regression_pct':round(config.NEURAL_ROLLBACK_MEAN_REGRESSION*100,2),
            'rollback_critical_regression_pct':round(config.NEURAL_ROLLBACK_CRITICAL_REGRESSION*100,2),
        },
        'timeline':timeline,
        'stages':list(STAGES),
    }

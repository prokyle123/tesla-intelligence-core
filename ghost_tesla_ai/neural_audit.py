from __future__ import annotations
import math,time
from . import db
from .neural_v4 import current_forecast,TARGETS

TARGET_TO_TREE = {
    'soc_60m':'soc_60m',
    'pack_60m':'pack_temp_60m',
    'cabin_60m':'cabin_temp_60m',
    'soc_180m':'soc_180m',
    'pack_180m':'pack_temp_180m',
}


def _f(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except Exception:return None


def _baseline_map(challenger_generation=None):
    # When an older neural generation is already in production, a new challenger
    # is scored against that actually-served neural generation. The production
    # generation itself keeps a tree baseline so rollback always has a known-safe
    # fallback comparison.
    try:
        from .neural_governor import production_generation
        prod=production_generation()
        if prod is not None and challenger_generation is not None and int(prod)!=int(challenger_generation):
            from .neural_v4 import forecast_for_generation
            pf=forecast_for_generation(prod)
            if pf.get('status')=='ready':
                m={}
                for p in pf.get('predictions',[]):
                    model_name=TARGET_TO_TREE.get(p.get('name'))
                    if model_name:
                        m[model_name]={'model':f'neural:{p.get("name")}', 'value':p.get('value'), 'generation':int(prod), 'source_backend':'neural_production'}
                if m:return m
    except Exception:
        pass
    try:
        from .predict import tree_predictions
        return {p.get('model'):p for p in tree_predictions() if p and not p.get('error')}
    except Exception:
        return {}


def _capture_forecast(f):
    if f.get('status')!='ready':return {'captured':0,'status':f.get('status'),'generation':f.get('generation')}
    trees=_baseline_map(f.get('generation')); captured=0; comparable=0
    with db.connect() as con:
        for p in f.get('predictions',[]):
            try:
                tree=trees.get(TARGET_TO_TREE.get(p.get('name')))
                bval=_f(tree.get('value')) if tree else None
                bname=tree.get('model') if tree else None
                bgen=int(tree.get('generation')) if tree and tree.get('generation') is not None else None
                con.execute('''INSERT OR IGNORE INTO neural_v4_audit(
                                  predicted_at,target_ts,generation,target_name,target_field,horizon_minutes,predicted_value,
                                  baseline_predicted_value,baseline_model_name,baseline_generation,source_telemetry_id,status)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (float(f['predicted_at']),float(f['predicted_at'])+int(p['horizon_min'])*60,int(f['generation']),p['name'],p['field'],int(p['horizon_min']),float(p['value']),bval,bname,bgen,int(f['source_telemetry_id']),'pending'))
                changed=con.execute('SELECT changes()').fetchone()[0]
                captured+=changed
                if changed and bval is not None:comparable+=1
            except Exception:
                pass
    return {'captured':captured,'baseline_comparable':comparable,'generation':f.get('generation')}


def capture_current():
    latest=current_forecast()
    results=[_capture_forecast(latest)]
    try:
        from .neural_governor import production_generation
        prod=production_generation()
        if prod is not None and int(prod)!=int(latest.get('generation') or -1):
            from .neural_v4 import forecast_for_generation
            results.append(_capture_forecast(forecast_for_generation(prod)))
    except Exception:
        pass
    return {
        'captured':sum(int(x.get('captured') or 0) for x in results),
        'baseline_comparable':sum(int(x.get('baseline_comparable') or 0) for x in results),
        'generations':[x.get('generation') for x in results if x.get('generation') is not None],
        'details':results,
    }


def resolve_due(now=None):
    now=float(now or time.time()); resolved=missed=0
    with db.connect() as con:
        due=con.execute("SELECT * FROM neural_v4_audit WHERE status='pending' AND target_ts<=? ORDER BY target_ts",(now,)).fetchall()
        for r in due:
            horizon=int(r['horizon_minutes']); tol=max(20*60,int(horizon*60*.25))
            actual=con.execute(f'''SELECT id,ts,{r['target_field']} AS actual FROM telemetry
                                   WHERE {r['target_field']} IS NOT NULL AND ts BETWEEN ? AND ?
                                   ORDER BY ABS(ts-?) LIMIT 1''',(float(r['target_ts'])-tol,float(r['target_ts'])+tol,float(r['target_ts']))).fetchone()
            if actual and actual['actual'] is not None:
                av=float(actual['actual']); pv=float(r['predicted_value']); err=av-pv
                bp=_f(r['baseline_predicted_value']) if 'baseline_predicted_value' in r.keys() else None
                berr=(av-bp) if bp is not None else None
                con.execute('''UPDATE neural_v4_audit SET actual_value=?,signed_error=?,abs_error=?,baseline_signed_error=?,baseline_abs_error=?,
                               actual_telemetry_id=?,resolved_at=?,resolution_gap_seconds=?,status='resolved' WHERE id=?''',
                            (av,err,abs(err),berr,None if berr is None else abs(berr),int(actual['id']),now,abs(float(actual['ts'])-float(r['target_ts'])),int(r['id'])))
                resolved+=1
            elif now>float(r['target_ts'])+tol:
                con.execute("UPDATE neural_v4_audit SET status='missed',resolved_at=? WHERE id=?",(now,int(r['id'])));missed+=1
    return {'resolved':resolved,'missed':missed}


def metrics(generation=None,since=None):
    out=[]
    where=[]; args=[]
    if generation is not None:
        where.append('generation=?');args.append(int(generation))
    if since is not None:
        where.append('predicted_at>=?');args.append(float(since))
    base_where=(' AND '+ ' AND '.join(where)) if where else ''
    with db.connect() as con:
        for t in TARGETS:
            rows=con.execute(f'SELECT * FROM neural_v4_audit WHERE target_name=?{base_where} ORDER BY predicted_at DESC LIMIT 4000',(t['name'],*args)).fetchall()
            rr=[r for r in rows if r['status']=='resolved' and r['abs_error'] is not None]
            comp=[r for r in rr if ('baseline_abs_error' in r.keys() and r['baseline_abs_error'] is not None)]
            pending=sum(r['status']=='pending' for r in rows); missed=sum(r['status']=='missed' for r in rows)
            mae=(sum(float(r['abs_error']) for r in rr)/len(rr)) if rr else None
            bias=(sum(float(r['signed_error']) for r in rr)/len(rr)) if rr else None
            bmae=(sum(float(r['baseline_abs_error']) for r in comp)/len(comp)) if comp else None
            nmae_comp=(sum(float(r['abs_error']) for r in comp)/len(comp)) if comp else None
            improvement=((bmae-nmae_comp)/bmae) if (bmae is not None and nmae_comp is not None and bmae>1e-9) else None
            factor=1.8 if t['unit']=='C' else 1.0
            tol=3/1.8 if t['unit']=='C' else 2.5
            hit=(100*sum(float(r['abs_error'])<=tol for r in rr)/len(rr)) if rr else None
            out.append({
                'name':t['name'],'label':t['label'],'unit':'°F' if t['unit']=='C' else '%',
                'resolved':len(rr),'comparable':len(comp),'pending':pending,'missed':missed,
                'mae':None if mae is None else round(mae*factor,2),'bias':None if bias is None else round(bias*factor,2),
                'hit_rate':None if hit is None else round(hit,1),
                'baseline_mae':None if bmae is None else round(bmae*factor,2),
                'neural_comparable_mae':None if nmae_comp is None else round(nmae_comp*factor,2),
                'live_improvement_pct':None if improvement is None else round(improvement*100.0,2),
                # native metrics are used by the governor to avoid display-unit ambiguity.
                'native_mae':mae,'native_baseline_mae':bmae,'native_neural_comparable_mae':nmae_comp,'native_improvement':improvement,
            })
    return out


def cycle():
    r=resolve_due();c=capture_current();state={'at':time.time(),'resolve':r,'capture':c,'metrics':metrics()};db.set_state('neural_v4_truth',state);return state

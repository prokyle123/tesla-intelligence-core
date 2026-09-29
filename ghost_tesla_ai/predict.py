from __future__ import annotations
import json
from . import db
from .features import MODEL_SPECS,LEGACY_FEATURES,live_vector,spec_applicable
from .backends.sklearn_histgb import SklearnHistGBBackend

NEURAL_TARGET_TO_MODEL = {
    'soc_60m':'soc_60m',
    'pack_60m':'pack_temp_60m',
    'cabin_60m':'cabin_temp_60m',
    'soc_180m':'soc_180m',
    'pack_180m':'pack_temp_180m',
    'pack_360m':'pack_temp_360m',
}


def _features(run):
    try:
        v=json.loads(run['features_json'] or '[]')
        return v if isinstance(v,list) and v else LEGACY_FEATURES
    except Exception:return LEGACY_FEATURES


def tree_predictions():
    """Return only the promoted HistGB production predictions.

    This deliberately bypasses the neural governor overlay so the Truth Engine
    can score neural and tree predictions against the same real outcome.
    """
    with db.connect() as con:
        latest=con.execute('SELECT * FROM telemetry ORDER BY ts DESC LIMIT 1').fetchone()
        runs=con.execute('SELECT * FROM model_runs WHERE promoted=1 ORDER BY model_name').fetchall()
    if not latest:return []
    out=[]
    for r in runs:
        spec=MODEL_SPECS.get(r['model_name'])
        if not spec:continue
        if not spec_applicable(spec,latest):continue
        try:
            X=[live_vector(latest,_features(r))]
            model=SklearnHistGBBackend.load(r['artifact_path']); val=float(model.predict(X)[0])
            out.append({'model':r['model_name'],'label':spec['label'],'value':val,'unit':spec['unit'],'generation':r['generation'],'mae':r['mae'],'horizon_minutes':r['horizon_minutes'],'regime':spec.get('regime'),'feature_version':r['feature_version'] if 'feature_version' in r.keys() else None,'source_backend':'tree_production'})
        except Exception as e:
            out.append({'model':r['model_name'],'error':f'{type(e).__name__}: {e}','source_backend':'tree_production'})
    return out


def _neural_production_overlay():
    try:
        from .neural_governor import production_generation
        gen=production_generation()
        if gen is None:return {},None
        from .neural_v4 import forecast_for_generation
        f=forecast_for_generation(gen)
        if f.get('status')!='ready':return {},gen
        out={}
        for p in f.get('predictions',[]):
            model_name=NEURAL_TARGET_TO_MODEL.get(p.get('name'))
            if not model_name:continue
            spec=MODEL_SPECS.get(model_name) or {}
            out[model_name]={
                'model':model_name,
                'label':spec.get('label') or p.get('label') or model_name,
                'value':p.get('value'),
                'unit':spec.get('unit') or p.get('unit'),
                'generation':int(gen),
                'mae':p.get('holdout_mae'),
                'horizon_minutes':p.get('horizon_min'),
                'regime':None,
                'feature_version':'v4-sequence-1',
                'source_backend':'neural_production',
                'neural_target':p.get('name'),
                'governor_stage':'PRODUCTION',
            }
        return out,gen
    except Exception:
        # Production must fail safe: if a neural artifact cannot be loaded, the
        # already-promoted tree champions continue serving predictions.
        return {},None


def current_predictions():
    trees=tree_predictions()
    neural,gen=_neural_production_overlay()
    if not neural:return trees
    out=[]; seen=set()
    for p in trees:
        name=p.get('model')
        if name in neural:
            out.append(neural[name]); seen.add(name)
        else:
            out.append(p)
    for name,p in neural.items():
        if name not in seen:out.append(p)
    return out

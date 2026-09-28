from __future__ import annotations

from pathlib import Path
import math,time

def _version():
    try:
        return Path("/opt/ghost-tesla-ai/VERSION").read_text().strip() or "0.4.1"
    except Exception:
        return "0.4.1"
from flask import Blueprint,jsonify,request
from . import db,config
from .event_engine import rebuild_events,event_summary,recent_events,routine_profile,learned_dynamics
from .readiness import current_readiness,snapshot_readiness,readiness_history
from .departure_learning import learn_schedule,schedule_status
from .event_models import model_status as trip_model_status
from .winter_board import build_winter_board

bp=Blueprint('v3_api',__name__)

def _f(v):
    try:
        x=float(v);return x if math.isfinite(x) else None
    except Exception:return None

def _challengers():
    out=[]
    with db.connect() as con:
        models=con.execute('SELECT DISTINCT model_name FROM challenger_runs ORDER BY model_name').fetchall()
        for m in models:
            name=m['model_name']
            ch=con.execute('SELECT * FROM challenger_runs WHERE model_name=? ORDER BY generation DESC LIMIT 1',(name,)).fetchone()
            baseline=con.execute('SELECT * FROM model_runs WHERE model_name=? AND feature_version=? ORDER BY generation DESC LIMIT 1',(name,'v3-context-1')).fetchone()
            active=con.execute('SELECT * FROM model_runs WHERE model_name=? AND promoted=1 ORDER BY generation DESC LIMIT 1',(name,)).fetchone()
            if not ch:continue
            cmae=_f(ch['mae']); bmae=None if not baseline else _f(baseline['mae'])
            out.append({'model':name,'backend':ch['backend'],'generation':int(ch['generation']),'trained_at':float(ch['trained_at']),'rows':int(ch['rows_total']),
                        'mae':cmae,'r2':_f(ch['r2']),'baseline_generation':None if not baseline else int(baseline['generation']),'baseline_mae':bmae,
                        'active_generation':None if not active else int(active['generation']),'active_mae':None if not active else _f(active['mae']),
                        'delta_mae':None if cmae is None or bmae is None else round(cmae-bmae,4),'beats_v3_baseline':bool(cmae is not None and bmae is not None and cmae<bmae),
                        'status':'EXPERIMENTAL - NEVER AUTO PROMOTED'})
    state=db.get_state('neural_challenger',{}) or {}
    return {'runs':out,'state':state,'enabled':bool(config.NEURAL_CHALLENGER),'min_rows':int(config.NEURAL_MIN_ROWS)}

@bp.get('/api/v3/overview')
def overview():
    db.init_db()
    return jsonify({'version':_version(),'readiness':current_readiness(),'events':event_summary(),'routine':routine_profile(),'departure_learning':schedule_status(),'dynamics':learned_dynamics(),
                    'challengers':_challengers(),'trip_models':trip_model_status(),'engine':db.get_state('event_engine',{}) or {},'derived':db.get_state('derived_backfill',{}) or {},
                    'intelligence':db.get_state('intelligence_cycle',{}) or {}})

@bp.get('/api/v3/events')
def events():
    limit=request.args.get('limit',80,type=int) or 80
    return jsonify({'summary':event_summary(),'routine':routine_profile(),'departure_learning':schedule_status(),'dynamics':learned_dynamics(),'events':recent_events(limit)})

@bp.get('/api/v3/readiness')
def readiness():
    return jsonify({'current':current_readiness(),'history':readiness_history(120)})

@bp.get('/api/v3/challengers')
def challengers(): return jsonify(_challengers())

@bp.post('/api/v3/rebuild')
def rebuild():
    db.backfill_derived(); ev=rebuild_events(config.EVENT_LOOKBACK_DAYS); dep=learn_schedule(force=True); rd=snapshot_readiness()
    out={'ok':True,'events':ev,'departure_learning':dep,'readiness':rd,'at':time.time()}; db.set_state('intelligence_cycle',out); return jsonify(out)

@bp.get('/api/v3/winter')
def winter_board():
    return jsonify(build_winter_board())

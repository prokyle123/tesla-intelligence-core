from __future__ import annotations
import os,subprocess,sys,time
from pathlib import Path
from flask import Blueprint,jsonify
from . import config,db
from .neural_v4 import status as neural_status,current_forecast
from .neural_audit import metrics as truth_metrics,cycle as truth_cycle
from .neural_governor import status as governor_status,cycle as governor_cycle

bp=Blueprint('v4_api',__name__)


def _systemd_active(unit: str) -> bool:
    try:
        r = subprocess.run(['systemctl','is-active','--quiet',unit], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        return r.returncode == 0
    except Exception:
        return False


def _training_pids():
    """Find actual live neural trainer processes, regardless of how they were launched.

    Dashboard-started training runs are detached Python processes, while scheduled
    runs normally come from systemd. Reading /proc makes the UI reflect either case.
    """
    out=[]
    try:
        for p in Path('/proc').iterdir():
            if not p.name.isdigit():
                continue
            try:
                raw=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
            except Exception:
                continue
            if 'ghost_tesla_ai.neural_v4' in raw and '--train' in raw:
                out.append(int(p.name))
    except Exception:
        pass
    return sorted(set(out))


def _runtime_status(neural):
    now=time.time()
    pids=_training_pids()
    service_active=_systemd_active('ghost-tesla-ai-neural.service')
    training_active=bool(pids) or service_active
    source='systemd' if service_active else ('background' if pids else 'idle')
    forecast=(neural or {}).get('forecast') or {}
    latest=(forecast.get('latest_context') or {})
    row_ts=latest.get('row_ts') or forecast.get('predicted_at')
    try: age=max(0.0, now-float(row_ts)) if row_ts else None
    except Exception: age=None
    lock=config.DATA_DIR/'neural-v4.lock'
    try: lock_age=max(0.0,now-lock.stat().st_mtime) if lock.exists() else None
    except Exception: lock_age=None
    return {
        'training_active': training_active,
        'training_source': source,
        'training_pids': pids,
        'training_service_active': service_active,
        'training_lock_present': lock.exists(),
        'training_lock_age_s': None if lock_age is None else round(lock_age,1),
        'collector_active': _systemd_active('ghost-tesla-ai-collector.service'),
        'intelligence_service_active': _systemd_active('ghost-tesla-ai-intelligence.service'),
        'intelligence_timer_active': _systemd_active('ghost-tesla-ai-intelligence.timer'),
        'neural_timer_active': _systemd_active('ghost-tesla-ai-neural.timer'),
        'inference_just_ran': forecast.get('status') == 'ready',
        'input_age_s': None if age is None else round(age,1),
        'input_fresh': bool(age is not None and age <= 300),
        'automation_ready': _systemd_active('ghost-tesla-ai-collector.service') and _systemd_active('ghost-tesla-ai-intelligence.timer') and _systemd_active('ghost-tesla-ai-neural.timer'),
    }

@bp.get('/api/v4/neural/status')
def status():
    s=neural_status()
    runtime=_runtime_status(s)
    try: version=Path('/opt/ghost-tesla-ai/VERSION').read_text().strip() or '0.8.26'
    except Exception: version='0.8.26'
    return jsonify({
        'version':version,
        'engine':s,
        'runtime':runtime,
        'truth':truth_metrics(),
        'governor':governor_status(),
        'enabled':bool(config.NEURAL_V4_ENABLED),
        'min_rows':int(config.NEURAL_V4_MIN_ROWS),
    })

@bp.get('/api/v4/neural/forecast')
def forecast():
    return jsonify(current_forecast())

@bp.post('/api/v4/neural/train')
def train():
    lock=config.DATA_DIR/'neural-v4.lock'
    state=db.get_state('neural_v4', {}) or {}
    live_pids=_training_pids()
    if live_pids:
        return jsonify({'ok':True,'status':'busy','message':'PyTorch training is already running.',
                        'epoch':state.get('epoch',0),'max_epochs':state.get('max_epochs'),
                        'phase':state.get('phase'),'started_at':state.get('started_at'),'pids':live_pids})
    if lock.exists() and time.time()-lock.stat().st_mtime<4*3600:
        return jsonify({'ok':True,'status':'busy','message':'PyTorch training is already running.',
                        'epoch':state.get('epoch',0),'max_epochs':state.get('max_epochs'),
                        'phase':state.get('phase'),'started_at':state.get('started_at')})
    if lock.exists():
        try: lock.unlink()
        except Exception: pass
    log=config.DATA_DIR/'neural-v4-train.log'
    with open(log,'ab',buffering=0) as f:
        p=subprocess.Popen([sys.executable,'-m','ghost_tesla_ai.neural_v4','--train'],cwd='/opt/ghost-tesla-ai',stdout=f,stderr=f,start_new_session=True)
    return jsonify({'ok':True,'status':'started','message':'PyTorch challenger started.',
                    'log':str(log),'pid':p.pid})

@bp.get('/api/v4/neural/log')
def log_tail():
    log=config.DATA_DIR/'neural-v4-train.log'
    if not log.exists():
        return jsonify({'lines':[],'text':'No neural training log yet.'})
    try:
        lines=log.read_text(errors='replace').splitlines()[-120:]
    except Exception as e:
        return jsonify({'lines':[],'text':f'Could not read log: {type(e).__name__}: {e}'})
    return jsonify({'lines':lines,'text':'\n'.join(lines)})

@bp.post('/api/v4/neural/audit')
def audit():
    truth=truth_cycle()
    governor=governor_cycle()
    return jsonify({'ok':True,'truth':truth,'governor':governor})

@bp.post('/api/v4/neural/governor')
def governor():
    return jsonify({'ok':True,'governor':governor_cycle()})

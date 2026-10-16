"""Additive read-only report routes. Never reads vehicle secrets into HTML."""
from pathlib import Path
import json,time
from flask import Blueprint, jsonify, render_template
from . import config

bp=Blueprint('ghost_trip_quality_v3',__name__)
REPORT_DIR=Path(config.get('GHOST_QUALITY_DIR', str(config.DATA_DIR / 'quality')))
REPORT=REPORT_DIR / 'v3-latest.json'

@bp.get('/trip-quality')
def trip_quality_page():
    return render_template('trip_quality_v31.html')

@bp.get('/api/trip-quality/v3')
def trip_quality_data():
    try:
        data=json.loads(REPORT.read_text(encoding='utf-8'))
        data['ok']=True
        data['report_age_min']=round(max(0,time.time()-float(data['generated_epoch']))/60,1)
        return jsonify(data)
    except Exception as exc:
        return jsonify({'ok':False,'error':'Report unavailable','type':type(exc).__name__}),503


# GHOST TRIP-QUALITY-V31: additive read-only endpoint. Existing v3 API retained.
@bp.get('/api/trip-quality/v31')
def trip_quality_v31_data():
    try:
        path=REPORT_DIR / 'v31-latest.json'
        value=json.loads(path.read_text(encoding='utf-8'))
        value['ok']=True
        value['report_age_min']=round(max(0,time.time()-float(value['generated_epoch']))/60,1)
        return jsonify(value)
    except Exception as exc:
        return jsonify({'ok':False,'error':'v3.1 report unavailable','type':type(exc).__name__}),503

# GHOST-TRIP-QUALITY-V32: read-only alternative metrics; prior APIs preserved.
@bp.get('/api/trip-quality/v32')
def trip_quality_v32_data():
    try:
        path=REPORT_DIR / 'v32-latest.json'
        value=json.loads(path.read_text(encoding='utf-8'))
        value['ok']=True
        value['report_age_min']=round(max(0,time.time()-float(value['generated_epoch']))/60,1)
        return jsonify(value)
    except Exception as exc:
        return jsonify({'ok':False,'error':'v3.2 report unavailable','type':type(exc).__name__}),503

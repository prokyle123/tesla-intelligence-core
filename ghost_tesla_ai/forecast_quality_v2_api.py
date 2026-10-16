"""Isolated read-only Flask view of the hourly Forecast Quality v2 report."""
from pathlib import Path
import json,time
from flask import Blueprint,jsonify,render_template

bp=Blueprint('ghost_forecast_quality_v2',__name__)
REPORT=Path('/home/ghost/ghost-forecast-quality/v2-latest.json')

@bp.get('/forecast-quality')
def page():
    return render_template('forecast_quality_v2.html')

@bp.get('/api/forecast-quality/v2')
def data():
    try:
        d=json.loads(REPORT.read_text(encoding='utf-8'))
        d['ok']=True
        d['age_minutes']=round(max(0.0,time.time()-float(d['generated_epoch']))/60,1)
        return jsonify(d)
    except Exception as e:
        return jsonify({'ok':False,'reason':'Report not yet ready','detail':type(e).__name__}),503

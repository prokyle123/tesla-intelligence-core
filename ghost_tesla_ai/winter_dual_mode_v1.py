"""GHOST Winter Board switchable current/next scoring, v1.

This is a presentation-only supplementary computation. It never changes
production readiness or forecasts, and does not train or actuate the car.
"""
from __future__ import annotations

from contextlib import closing
import math
import os
from pathlib import Path
import sqlite3
import time

DAY = 86400.0
HISTORY = Path(os.environ.get('GHOST_SCORE_HISTORY_DIR', '/var/lib/ghost-tesla-ai/winter-score-history')) / 'scores.sqlite3'


def number(value):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def clamp(value, lower=0.0, upper=100.0):
    return max(lower, min(upper, value))


def calculate_now(board):
    """Current-input counterpart to the existing four-component weighted score.

    SOC trip reserve is explicitly a reference-commute scenario, NOT a
    live verified-route prediction. No departure SOC credit is granted.
    """
    cur = board.get('current') or {}
    dep = board.get('departure') or {}
    future = board.get('score_breakdown') or {}
    soc = number(cur.get('soc'))
    pack = number(cur.get('pack_f'))
    ambient = number(cur.get('outside_f'))
    if soc is None or pack is None:
        return {'available': False, 'status': 'LEARNING', 'reason': 'Current pack temperature or battery SOC is unavailable.', 'score_breakdown': {'human_penalties': [], 'human_checks': []}}
    target = number(dep.get('charge_target_soc')) or 80.0
    target = max(1.0, target)
    departure_soc = number(dep.get('departure_soc'))
    predicted_arrival = number(dep.get('arrival_soc'))
    # This is an approximate *reference* drive consumption from production
    # planning, which may not match the car's present location or next route.
    reference_drop = None
    if departure_soc is not None and predicted_arrival is not None:
        drop = departure_soc - predicted_arrival
        if 0 <= drop <= 60:
            reference_drop = drop
    arrival_now = None if reference_drop is None else max(0.0, soc - reference_drop)
    thermal = 100.0 if pack >= 50 else clamp((pack - 20.0) * 100.0 / 30.0)
    reserve = 50.0 if arrival_now is None else clamp((arrival_now - 10.0) * 5.0)
    charge = clamp(soc / target * 100.0)
    evidence_src = next((x for x in (future.get('components') or []) if x.get('key') == 'evidence'), None)
    evidence = number((evidence_src or {}).get('raw_score'))
    evidence = 0.0 if evidence is None else clamp(evidence)
    rich_penalty = number(future.get('rich_context_penalty')) or 0.0
    reasons = [
        ('thermal', 'Current pack temperature', 45.0, thermal,
         f'Measured pack {pack:.1f}°F; full thermal credit begins at 50°F.'),
        ('arrival_soc', 'Leave-now reference-trip reserve', 35.0, reserve,
         'No reliable reference trip consumption; provisional half-credit, not a route prediction.' if arrival_now is None else
         f'If driving the reference trip immediately: ~{arrival_now:.0f}% estimated arrival SOC (not location-verified).'),
        ('departure_charge', 'Battery charge right now', 10.0, charge,
         f'Measured SOC {soc:.0f}% compared with {target:.0f}% preferred target.'),
        ('evidence', 'Evidence confidence', 10.0, evidence,
         f'Original readiness evidence {evidence:.0f}%; not a measure of live route certainty.')
    ]
    components=[]
    human=[]
    for key, label, weight, raw, description in reasons:
        points = round(weight * raw / 100.0, 2)
        penalty = round(weight-points, 2)
        components.append({'key':key,'label':label,'weight':weight,'raw_score':round(raw,2),'points':points,'penalty':penalty,'reason':description})
        if penalty >= 0.025:
            readings={
                'thermal':f'{pack:.1f}°F / 50°F full credit',
                'arrival_soc':('UNKNOWN REFERENCE' if arrival_now is None else f'~{arrival_now:.0f}% reference arrival'),
                'departure_charge':f'{soc:.0f}% / {target:.0f}%',
                'evidence':f'{evidence:.0f}% evidence',
            }
            human.append({'key':'now_'+key,'label':label.upper(),'value':readings[key], 'detail':description, 'severity':'warn' if penalty < 8 else 'bad','score_penalty':penalty,'score_source':key})
    remaining_rich = rich_penalty
    for penalty in (future.get('execution_penalties') or []):
        raw_points = number(penalty.get('points')) or 0.0
        p = min(raw_points, remaining_rich)
        if p >= 0.025:
            remaining_rich -= p
            human.append({'key':'now_execution_'+str(penalty.get('key') or 'condition'),'label':'VEHICLE CONDITION','value':'ACTIVE', 'detail':str(penalty.get('reason') or ''),'severity':'warn','score_penalty':round(p,2),'score_source':'execution'})
    base = clamp(sum(x['points'] for x in components))
    score = round(clamp(base - rich_penalty), 2)
    # The source formula rounds subcomponents to hundredths; match that.
    total = round(100.0-score, 2)
    checks = [{'key':'now_reference','label':'REFERENCE TRIP BASIS','state':'CONDITIONAL' if reference_drop is not None else 'UNKNOWN', 'severity':'info', 'detail':'Generic learned commute consumption; present origin/destination not route-verified.', 'value':'—' if reference_drop is None else f'{reference_drop:.1f} SOC points'}]
    if soc < 15:
        checks.append({'key':'now_low_soc','label':'LOW BATTERY','state':'WATCH','severity':'warn','detail':'SOC is below 15%; compare against intended driving and access to charging.', 'value':f'{soc:.0f}%'})
    from . import config
    warm_target = number(getattr(config,'READINESS_TARGET_PACK_F',None)) or 50.0
    heater = bool(cur.get('heater_on'))
    if heater:
        action='Battery heater is active right now.'
    elif pack >= warm_target:
        action='No battery warm-up is needed right now.'
    else:
        action=f'Pack is below the {warm_target:.0f}°F preferred warm-up target right now.'
    state='READY' if score>=75 else 'WATCH' if score>=55 else 'ACTION'
    headline = 'WINTER READY NOW' if score>=90 else 'CURRENT WINTER READY' if score>=75 else 'CURRENT WINTER WATCH' if score>=55 else 'CURRENT ACTION RECOMMENDED'
    return {
        'available':True,'score':score,'state':state,'headline':headline,'action':action,
        'current_soc':round(soc,1),'pack_f':round(pack,1),'outside_f':None if ambient is None else round(ambient,1),
        'reference_soc_drop_pp':None if reference_drop is None else round(reference_drop,1),
        'reference_arrival_soc':None if arrival_now is None else round(arrival_now,1),
        'reference_note':'Reference commute only: not a verified drive from the current parking location.',
        'score_breakdown':{'max_score':100.0,'base_score_unrounded':round(base,2),'rich_context_penalty':round(rich_penalty,2),'score_unrounded':score,'total_penalty':total,'components':components,'active_penalties':[x for x in components if x['penalty']>=.025], 'execution_penalties':future.get('execution_penalties') or [], 'human_penalties':human, 'human_checks':checks},
    }


def attach_now_score(board):
    """Separate current-score history, sampled by the existing background timer.

    Exceptions never affect the existing Winter Score API.
    """
    now = float(board.get('generated_at') or time.time())
    board['now_score_history_12h'] = []
    board['now_score_history_status'] = 'COLLECTING'
    try:
        current = calculate_now(board)
        board['now_score'] = current
        if not current.get('available'):
            return board
        from . import db
        with db.connect() as conn:
            row = conn.execute('SELECT ts FROM telemetry ORDER BY ts DESC LIMIT 1').fetchone()
        age = now-float(row['ts']) if row else float('inf')
        fresh = -120 <= age <= 1800
        board['now_score']['data_age_minutes'] = round(max(0, age)/60.0,1) if math.isfinite(age) else None
        if not fresh:
            board['now_score']['state'] = 'LAST KNOWN'
            board['now_score']['headline'] = 'LAST KNOWN VEHICLE CONDITION'
            board['now_score_history_status'] = 'STALE TELEMETRY'
        HISTORY.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(str(HISTORY), timeout=5.0)) as conn, conn:
            conn.execute('PRAGMA busy_timeout=5000')
            conn.execute('CREATE TABLE IF NOT EXISTS now_score_samples (ts REAL PRIMARY KEY, score REAL NOT NULL CHECK(score >= 0 AND score <= 100))')
            conn.execute('BEGIN IMMEDIATE')
            prev=conn.execute('SELECT ts,score FROM now_score_samples ORDER BY ts DESC LIMIT 1').fetchone()
            score=current['score']
            if fresh and (prev is None or now-prev[0]>=60 or (now-prev[0]>=10 and abs(score-prev[1])>=.05)):
                conn.execute('INSERT OR REPLACE INTO now_score_samples(ts,score) VALUES (?,?)',(now,score))
            conn.execute('DELETE FROM now_score_samples WHERE ts < ?', (now-8*DAY,))
            rows=conn.execute('SELECT ts,score FROM now_score_samples WHERE ts>=? AND ts<=? ORDER BY ts',(now-43200,now+1)).fetchall()
        board['now_score_history_12h']=[{'ts':round(float(ts),2),'score':round(float(sc),2)} for ts,sc in rows]
        if fresh:
            board['now_score_history_status']='LIVE' if rows else 'COLLECTING'
    except Exception:
        board['now_score_history_status']='HISTORY UNAVAILABLE'
        board.setdefault('now_score', {'available':False,'status':'LEARNING','reason':'Current-readiness computation unavailable.'})
    return board

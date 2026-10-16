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
    """GHOST RIGHT NOW V2: measured Tesla telemetry only, never future forecasts."""
    try:
        from . import db
        from .readiness_now_v2 import score_measured
        with db.connect() as con:
            row=con.execute("""SELECT battery_level, battery_temp_c, outside_temp_c,
                charging_state, battery_heater_on, battery_heater_no_power,
                not_enough_power_to_heat, module_temp_min_c, module_temp_max_c
                FROM telemetry ORDER BY ts DESC LIMIT 1""").fetchone()
        return score_measured(dict(row) if row is not None else None)
    except Exception:
        return {'available': False, 'status': 'LEARNING', 'state': 'LEARNING',
                'reason': 'Current Tesla telemetry could not be read; no estimated score shown.',
                'score_breakdown': {'human_penalties': [], 'human_checks': []}}


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
            conn.execute('CREATE TABLE IF NOT EXISTS now_score_samples_v2 (ts REAL PRIMARY KEY, score REAL NOT NULL CHECK(score >= 0 AND score <= 100))')
            conn.execute('BEGIN IMMEDIATE')
            prev=conn.execute('SELECT ts,score FROM now_score_samples_v2 ORDER BY ts DESC LIMIT 1').fetchone()
            score=current['score']
            if fresh and (prev is None or now-prev[0]>=60 or (now-prev[0]>=10 and abs(score-prev[1])>=.05)):
                conn.execute('INSERT OR REPLACE INTO now_score_samples_v2(ts,score) VALUES (?,?)',(now,score))
            conn.execute('DELETE FROM now_score_samples_v2 WHERE ts < ?', (now-8*DAY,))
            rows=conn.execute('SELECT ts,score FROM now_score_samples_v2 WHERE ts>=? AND ts<=? ORDER BY ts',(now-43200,now+1)).fetchall()
        board['now_score_history_12h']=[{'ts':round(float(ts),2),'score':round(float(sc),2)} for ts,sc in rows]
        if fresh:
            board['now_score_history_status']='LIVE' if rows else 'COLLECTING'
    except Exception:
        board['now_score_history_status']='HISTORY UNAVAILABLE'
        board.setdefault('now_score', {'available':False,'status':'LEARNING','reason':'Current-readiness computation unavailable.'})
    return board

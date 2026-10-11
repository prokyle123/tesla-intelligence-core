"""Independent history of actual rendered GHOST winter-readiness scores.

No score recomputation or adjustment takes place here. Do not use for model training.
"""
from __future__ import annotations

import math
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import time

HISTORY_DIR = Path(os.environ.get('GHOST_SCORE_HISTORY_DIR', '/var/lib/ghost-tesla-ai/winter-score-history'))
HISTORY_DB = HISTORY_DIR / 'scores.sqlite3'
DAY = 86400.0


def _score(board):
    value = (board.get('score_breakdown') or {}).get('score_unrounded', board.get('score'))
    try:
        val = float(value)
    except (TypeError, ValueError):
        return None
    return round(max(0.0, min(100.0, val)), 3) if math.isfinite(val) else None


def attach_score_history(board: dict) -> dict:
    """Add historical scores to an already-calculated winter board; fail open.

    The API remains available even if the independent history store fails.
    No storage is attempted if telemetry is stale or if the board is waiting.
    """
    board['score_history_24h'] = []
    board['score_history_status'] = 'COLLECTING'
    current = _score(board)
    if current is None or board.get('status') == 'WAITING':
        try:
            from .winter_dual_mode_v1 import attach_now_score
            attach_now_score(board)
        except Exception:
            board['now_score_history_status'] = 'HISTORY UNAVAILABLE'
        return board
    now = float(board.get('generated_at') or time.time())
    try:
        from . import db
        with db.connect() as live:
            last_telemetry = live.execute('SELECT ts FROM telemetry ORDER BY ts DESC LIMIT 1').fetchone()
        telemetry_age = now - float(last_telemetry['ts']) if last_telemetry else float('inf')
        fresh = -120.0 <= telemetry_age <= 1800.0
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(str(HISTORY_DB), timeout=5.0)) as con, con:
            con.execute('PRAGMA busy_timeout=5000')
            con.execute('CREATE TABLE IF NOT EXISTS score_samples (ts REAL PRIMARY KEY, score REAL NOT NULL CHECK(score >= 0 AND score <= 100))')
            con.execute('BEGIN IMMEDIATE')
            prev = con.execute('SELECT ts, score FROM score_samples ORDER BY ts DESC LIMIT 1').fetchone()
            # A regular once-a-minute sample, or a genuine change after 10 seconds.
            # Avoid artificial noise due only to five-second browser refreshes.
            if fresh and (prev is None or (now - prev[0] >= 60.0) or (now - prev[0] >= 10.0 and abs(current - prev[1]) >= 0.05)):
                con.execute('INSERT OR REPLACE INTO score_samples(ts,score) VALUES (?,?)', (now, current))
            con.execute('DELETE FROM score_samples WHERE ts < ?', (now - 8 * DAY,))
            rows = con.execute('SELECT ts,score FROM score_samples WHERE ts >= ? AND ts <= ? ORDER BY ts', (now - DAY, now + 1)).fetchall()
        board['score_history_24h'] = [{'ts': round(float(t), 2), 'score': round(float(s), 2)} for t, s in rows]
        board['score_history_status'] = ('LIVE' if fresh else 'STALE TELEMETRY') if rows else 'COLLECTING'
    except Exception:
        # The graph is optional. Never make winter readiness depend on disk writes.
        board['score_history_status'] = 'HISTORY UNAVAILABLE'
    # GHOST-DUAL-DIAL-V1: separate current-score sampling for API and background timer.
    try:
        from .winter_dual_mode_v1 import attach_now_score
        attach_now_score(board)
    except Exception:
        board['now_score_history_status'] = 'HISTORY UNAVAILABLE'
    return board

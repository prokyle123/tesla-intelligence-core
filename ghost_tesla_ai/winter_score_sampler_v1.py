"""Periodic score snapshot of existing winter score; never wakes Tesla or adjusts weights."""
from __future__ import annotations
import sys,time
from . import db
from .winter_board import build_winter_board
from .winter_score_history import attach_score_history

def sample():
    now=time.time()
    with db.connect() as con:
        row=con.execute('SELECT ts FROM telemetry ORDER BY ts DESC LIMIT 1').fetchone()
    if not row or now-float(row['ts']) > 1800 or float(row['ts']) > now+120:
        return 'SKIPPED: stale or missing telemetry (no new score written)'
    board=attach_score_history(build_winter_board())
    status=board.get('score_history_status')
    if status=='HISTORY UNAVAILABLE': raise RuntimeError(status)
    return f"OK: winter score {board.get('score')} status={status} sample_count={len(board.get('score_history_24h') or [])}"

if __name__=='__main__':
    print(sample())

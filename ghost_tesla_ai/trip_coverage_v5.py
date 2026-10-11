#!/usr/bin/env python3
"""GHOST Trip Coverage v5 — independent, prospective departure-time-only forecasts.

Uses observed, completed vehicle events for time patterns. Requires no fresh GPS,
records NO origin or destination, and leaves live GHOST and the v3/v4 sidecars
untouched. Reuses v3.2's conservative complete-drive settlement criterion.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
import statistics
import tempfile
import time
from urllib.parse import quote
from zoneinfo import ZoneInfo

VERSION='time-only-prospective-v5.0.0'
TZ=ZoneInfo('America/Chicago')
ROOT=Path('/home/ghost/ghost-trip-sequence')
LIVE=Path('/var/lib/ghost-tesla-ai/ghost_ai.sqlite3')
MIN_SUPPORT_WEEKDAY=6
MIN_SUPPORT_WEEKEND=4
MIN_LEAD_MIN=45
MAX_LEAD_HOURS=18
LOOKBACK_DAYS=45
EARLY_WINDOW_MIN=120
LATE_WINDOW_MIN=180
MAX_LAST_TELEMETRY_HOURS=18


def n(v):
    try:
        z=float(v)
        return z if math.isfinite(z) else None
    except (TypeError, ValueError, OverflowError):
        return None


def dt(ts): return datetime.fromtimestamp(float(ts),TZ)
def fmt(ts): return dt(ts).strftime('%Y-%m-%d %a %I:%M %p') if ts else '—'
def median(x):return statistics.median(x) if x else None


def open_live(path):
    c=sqlite3.connect('file:'+quote(str(path),safe='/')+'?mode=ro',uri=True,timeout=20)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA query_only=ON')
    c.execute('PRAGMA busy_timeout=15000')
    return c


def open_sidecar(path):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    c=sqlite3.connect(str(path),timeout=20)
    c.row_factory=sqlite3.Row
    os.chmod(path,0o600)
    c.execute('''CREATE TABLE IF NOT EXISTS time_forecasts (
      id INTEGER PRIMARY KEY,
      captured_at REAL NOT NULL,
      predicted_ts REAL NOT NULL,
      pattern_group TEXT NOT NULL,
      pattern_minute INTEGER NOT NULL,
      support_days INTEGER NOT NULL,
      mad_minutes REAL NOT NULL,
      evidence TEXT NOT NULL DEFAULT 'TIME_ONLY_NO_LOCATION_ASSERTION',
      status TEXT NOT NULL DEFAULT 'PENDING',
      actual_start_ts REAL,
      actual_end_ts REAL,
      departure_error_min REAL,
      scored_at REAL,
      note TEXT
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS ix_v5_status ON time_forecasts(status,predicted_ts)')
    c.commit()
    return c


def source_car(live):
    r=live.execute('SELECT car_id FROM telemetry ORDER BY ts DESC LIMIT 1').fetchone()
    return str(r['car_id']) if r and r['car_id'] else None


def learn_patterns(live,car,now):
    """Only completed real drive events. No configured clock times or GPS."""
    rows=live.execute('''SELECT start_ts,end_ts,distance_km,duration_min
      FROM vehicle_events WHERE car_id=? AND event_type='drive' AND start_ts>=? AND end_ts<=?
      AND distance_km>=5 AND distance_km<=250 AND end_ts>start_ts
      ORDER BY start_ts''',(car,now-LOOKBACK_DAYS*86400,now-20*60)).fetchall()
    samples=defaultdict(list)
    for r in rows:
        start=dt(r['start_ts'])
        m=start.hour*60+start.minute
        k='weekday' if start.weekday()<5 else 'weekend'
        samples[k].append({'day':start.date().isoformat(),'minute':m})
    patterns=[]
    for group,obs in samples.items():
        values=sorted(obs,key=lambda x:x['minute'])
        clusters=[]
        for r in values:
            if not clusters or r['minute']-clusters[-1][-1]['minute']>85:
                clusters.append([r])
            else:clusters[-1].append(r)
        for cluster in clusters:
            near_m=median([x['minute'] for x in cluster])
            each={}
            for x in cluster:
                if x['day'] not in each or abs(x['minute']-near_m)<abs(each[x['day']]-near_m):
                    each[x['day']]=x['minute']
            mins=list(each.values())
            min_days=MIN_SUPPORT_WEEKDAY if group=='weekday' else MIN_SUPPORT_WEEKEND
            if len(mins)<min_days:continue
            center=int(round(median(mins)))
            mad=float(median([abs(x-center) for x in mins]))
            patterns.append({'group':group,'minute':center,'mad':mad,'support':len(mins)})
    return sorted(patterns,key=lambda p:(p['group'],p['minute']))


def candidate(patterns,now):
    """Earliest supported upcoming time-of-day slot; at most one pending target."""
    start=dt(now)
    found=[]
    for delta in range(2):
        day=start.date()+timedelta(days=delta)
        group='weekday' if day.weekday()<5 else 'weekend'
        for p in patterns:
            if p['group']!=group:continue
            when=datetime(day.year,day.month,day.day,p['minute']//60,p['minute']%60,tzinfo=TZ).timestamp()
            lead=(when-now)/60
            if MIN_LEAD_MIN<=lead<=MAX_LEAD_HOURS*60:
                found.append((when,p))
    return min(found,key=lambda x:x[0]) if found else None


def capture_allowed(live,car,now):
    """Time-only capture tolerates sleeping/stale GPS but not observed motion."""
    latest=live.execute('''SELECT ts,shift_state,speed_kmh FROM telemetry
      WHERE car_id=? ORDER BY ts DESC LIMIT 1''',(car,)).fetchone()
    if latest is None:return False,'No vehicle telemetry history'
    age=(now-float(latest['ts']))/3600
    if age<0 or age>MAX_LAST_TELEMETRY_HOURS:
        return False,f'Last telemetry age {age:.1f} h is outside 0–{MAX_LAST_TELEMETRY_HOURS} h'
    gear=str(latest['shift_state'] or '').upper()
    speed=n(latest['speed_kmh']) or 0
    # Do not assume a sleeping vehicle is parked when the LAST known evidence
    # was that it was driving. This covers telemetry outages during a trip.
    if speed>3 or (gear in ('D','DRIVE','R','REVERSE') and age<=6):
        return False,'Last known vehicle state suggests motion or an incomplete park transition'
    # If recent motion is positively observed, do not create any forecast.
    moving=live.execute('''SELECT ts,shift_state,speed_kmh FROM telemetry
      WHERE car_id=? AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 30''',
      (car,now-480,now)).fetchall()
    for r in moving:
        speed=n(r['speed_kmh']) or 0
        gear=str(r['shift_state'] or '').upper()
        if speed>5 or (gear in ('D','DRIVE','R','REVERSE') and speed>2):
            return False,'Recent driving evidence; time-only forecast not captured'
    return True,'GPS not required; departure timing only (location unverified)'


def freeze(sidecar,when,p,now):
    # One prospective forecast per learned time slot and calendar day. If the
    # estimated median moves, preserve the original forecast rather than rewriting.
    day=dt(when).date().isoformat()
    previous=sidecar.execute('''SELECT id FROM time_forecasts WHERE predicted_ts BETWEEN ? AND ?
      ORDER BY captured_at LIMIT 1''',(when-90*60,when+90*60)).fetchone()
    if previous:return False,'Existing frozen forecast preserved'
    sidecar.execute('''INSERT INTO time_forecasts
      (captured_at,predicted_ts,pattern_group,pattern_minute,support_days,mad_minutes,note)
      VALUES (?,?,?,?,?,?,?)''',(now,when,p['group'],p['minute'],p['support'],p['mad'],
        'TIME ONLY. No GPS location, route, or destination prediction.'))
    sidecar.commit()
    return True,'New TIME_ONLY forecast frozen'


def first_event(live,car,snap,now):
    start=max(float(snap['captured_at']),float(snap['predicted_ts'])-EARLY_WINDOW_MIN*60)
    end=min(now,float(snap['predicted_ts'])+LATE_WINDOW_MIN*60)
    return live.execute('''SELECT start_ts,end_ts,distance_km,soc_change,wh_per_mile
      FROM vehicle_events WHERE car_id=? AND event_type='drive' AND start_ts>=? AND start_ts<=?
      AND end_ts>start_ts AND distance_km BETWEEN 5 AND 250
      ORDER BY start_ts LIMIT 1''',(car,start,end)).fetchone()


def evaluate(sidecar,live,car,now,complete_fn,motion_fn):
    for snap in sidecar.execute("SELECT * FROM time_forecasts WHERE status='PENDING' ORDER BY captured_at").fetchall():
        # Retrospective protection: when new telemetry later proves that a forecast
        # was frozen while the car was moving, exclude rather than doctor evidence.
        if motion_fn(live,car,float(snap['captured_at'])):
            sidecar.execute("UPDATE time_forecasts SET status='INVALID_CAPTURE_IN_MOTION',scored_at=?,note=? WHERE id=? AND status='PENDING'",
              (now,'Retrospective movement evidence; excluded',snap['id']))
            continue
        event=first_event(live,car,snap,now)
        if event and complete_fn(live,car,event,now):
            actual=float(event['start_ts']); err=(actual-float(snap['predicted_ts']))/60
            sidecar.execute('''UPDATE time_forecasts SET status='SCORED_TIME_ONLY',actual_start_ts=?,
              actual_end_ts=?,departure_error_min=?,scored_at=?,note=?
              WHERE id=? AND status='PENDING' ''',
              (actual,float(event['end_ts']),round(err,2),now,
               'Entire drive settled; departure time scored; route and destination NOT scored',snap['id']))
        elif not event and now>float(snap['predicted_ts'])+LATE_WINDOW_MIN*60:
            sidecar.execute("UPDATE time_forecasts SET status='UNVERIFIED_NO_TRIP',scored_at=?,note=? WHERE id=? AND status='PENDING'",
                (now,'No complete observed drive. NOT counted as prediction wrong',snap['id']))
    sidecar.commit()


def safe_write(path,value):
    fd,tmp=tempfile.mkstemp(prefix='.ghost-v5-',dir=path.parent)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            f.write(value);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def report(sidecar,patterns,info,now):
    rows=[dict(r) for r in sidecar.execute('SELECT * FROM time_forecasts ORDER BY captured_at DESC').fetchall()]
    scored=[r for r in rows if r['status']=='SCORED_TIME_ONLY']
    pending=[r for r in rows if r['status']=='PENDING']
    invalid=[r for r in rows if r['status']=='INVALID_CAPTURE_IN_MOTION']
    mae=statistics.mean(abs(r['departure_error_min']) for r in scored) if scored else None
    lines=[f'GHOST TIME-ONLY TRIP COVERAGE {VERSION}',f'Updated: {fmt(now)}',
      'SHADOW ONLY. Production departure, v3.2 route scoring, v4 feedback, neural models and vehicle UNCHANGED.',
      '', '=== LEARNED DEPARTURE WINDOWS ===']
    for p in patterns:
        lines.append(f'  {p["group"]} {p["minute"]//60:02d}:{p["minute"]%60:02d} | {p["support"]} separate days | MAD +/-{p["mad"]:.1f}m')
    if not patterns:lines.append('  Collecting qualifying trips; no forecast created.')
    lines.extend(['','=== PROSPECTIVE TIME-ONLY FORECASTS ===',
      f'Captured before departure: {len(rows)}',f'Time-only trips scored: {len(scored)}',
      f'Pending: {len(pending)} | invalid-in-motion: {len(invalid)}',
      f'Departure timing MAE: {mae:.1f}m ({len(scored)} scored)' if mae is not None else 'Departure timing MAE: WAITING',
      f'Capture status: {info}', '', '=== MOST RECENT FORECASTS ==='])
    for r in rows[:10]:
        line=f'  {fmt(r["predicted_ts"])} | {r["pattern_group"]} | {r["status"]} | {r["support_days"]} support days'
        if r['actual_start_ts'] is not None:
            line+=f' | actual {fmt(r["actual_start_ts"])} | error {r["departure_error_min"]:+.1f}m'
        lines.append(line)
    if not rows:lines.append('  None frozen yet.')
    lines+=['','DATA RULE: TIME_ONLY does not assert any site, home/work label, destination, or battery prediction.',
      'Missing GPS or sleeping vehicle is not treated as a missed trip.',
      'v5 statistics are separate from v3/v4; overlapping predictions are NOT double-counted in v4.',
      'PRIVATE: coverage-v5.sqlite3 is local to the Pi. No coordinates, VIN, or credentials in this report.']
    return '\n'.join(lines)+'\n'


def run(root,live_path,now):
    # Fail closed if the existing conservative v3.2 validator isn't installed.
    from trip_outcome_v3 import trip_complete, observed_in_motion, VERSION as V3_VERSION
    if V3_VERSION!='prospective-trip-outcomes-v3.2.0':
        raise RuntimeError('Expected v3.2 scoring safeguards; refusing to run v5')
    if not live_path.is_file():raise RuntimeError('No read-only live DB')
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    live=open_live(live_path)
    sidecar=open_sidecar(root/'coverage-v5.sqlite3')
    try:
        car=source_car(live)
        if not car:raise RuntimeError('No vehicle telemetry')
        patterns=learn_patterns(live,car,now)
        evaluate(sidecar,live,car,now,trip_complete,observed_in_motion)
        target=candidate(patterns,now)
        if not target:
            info='No supported departure within next 18 hours and >=45 minute lead'
        else:
            allowed,reason=capture_allowed(live,car,now)
            if not allowed:info=reason
            else:
                new,reason=freeze(sidecar,target[0],target[1],now)
                info=reason
        output=report(sidecar,patterns,info,now)
        safe_write(root/'latest-trip-coverage-v5.txt',output)
        print(output)
    finally:
        sidecar.close();live.close()


def self_test():
    import sys
    from unittest.mock import Mock
    now=datetime(2026,10,8,17,30,tzinfo=TZ).timestamp()
    # A normal weekday home/work history produces independent morning/afternoon peaks.
    with tempfile.TemporaryDirectory() as td:
        td=Path(td)
        live=sqlite3.connect(td/'live.db')
        live.row_factory=sqlite3.Row
        live.execute('CREATE TABLE telemetry(car_id TEXT,ts REAL,shift_state TEXT,speed_kmh REAL)')
        live.execute('CREATE TABLE vehicle_events(car_id TEXT,event_type TEXT,start_ts REAL,end_ts REAL,distance_km REAL,duration_min REAL,soc_change REAL,wh_per_mile REAL)')
        for daysback in range(43,0,-1):
            day=dt(now)-timedelta(days=daysback)
            if day.weekday()>4:continue
            for hour,minute in ((6,12),(14,41)):
                t=datetime(day.year,day.month,day.day,hour,minute,tzinfo=TZ).timestamp()
                live.execute('INSERT INTO vehicle_events VALUES (?,?,?,?,?,?,?,?)',('car','drive',t,t+3600,63.5,60,-13,230))
        # Vehicle went to sleep; latest telemetry is 3 hours old and GPS absent.
        live.execute('INSERT INTO telemetry VALUES (?,?,?,?)',('car',now-3*3600,'P',0))
        live.commit()
        patterns=learn_patterns(live,'car',now)
        assert len([p for p in patterns if p['group']=='weekday'])==2,patterns
        next_time,p=candidate(patterns,now)
        assert dt(next_time).weekday()==4 and dt(next_time).hour==6 and p['support']>=6
        assert capture_allowed(live,'car',now)[0]
        side=open_sidecar(td/'coverage.sqlite3')
        assert freeze(side,next_time,p,now)[0]
        assert not freeze(side,next_time,p,now+30)[0]
        # Do not score before the full drive is verified.
        later=next_time+10*60
        live.execute('INSERT INTO vehicle_events VALUES (?,?,?,?,?,?,?,?)',('car','drive',later,later+75*60,63.5,75,-12,200))
        live.commit()
        assert (first_event(live,'car',side.execute('SELECT * FROM time_forecasts').fetchone(),later+10*60) is None) is False
        def complete(_live,_car,row,stamp):return stamp>=float(row['end_ts'])+20*60
        def notmoving(*args):return False
        evaluate(side,live,'car',later+10*60,complete,notmoving)
        assert side.execute('SELECT status FROM time_forecasts').fetchone()['status']=='PENDING'
        evaluate(side,live,'car',later+96*60,complete,notmoving)
        row=side.execute('SELECT * FROM time_forecasts').fetchone()
        assert row['status']=='SCORED_TIME_ONLY' and row['departure_error_min']==10
        assert 'TIME_ONLY' in report(side,patterns,'test',now)
        side.close();live.close()
        # Observed motion blocks capture, regardless of fresh GPS evidence.
        moving=sqlite3.connect(td/'motion.db');moving.row_factory=sqlite3.Row
        moving.execute('CREATE TABLE telemetry(car_id TEXT,ts REAL,shift_state TEXT,speed_kmh REAL)')
        moving.execute('INSERT INTO telemetry VALUES (?,?,?,?)',('car',now-30,'D',75))
        moving.commit()
        assert not capture_allowed(moving,'car',now)[0]
        moving.close()
    print('SELF-TEST PASS: learned dual peaks; overnight asleep; no fake GPS; frozen forecasts; complete-drive scoring; moving block')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--db',type=Path,default=LIVE)
    p.add_argument('--self-test',action='store_true')
    args=p.parse_args()
    if args.self_test:self_test()
    else:run(args.root,args.db,time.time())

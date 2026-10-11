#!/usr/bin/env python3
"""GHOST Prediction Accountability v3: prospective, shadow-only trip scoring.

Captures predictions before trips happen and scores them against future observed
vehicle events. Reads production DB and v2 site mapping, writes ONLY a private
sidecar DB and coordinate-free report. No model or production API edits.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import sqlite3
import statistics
import tempfile
import time

VERSION = 'prospective-trip-outcomes-v3.2.0'
ROOT = Path('/home/ghost/ghost-trip-sequence')
GHOST_DB = Path('/var/lib/ghost-tesla-ai/ghost_ai.sqlite3')
# Avoid scoring stale predictions or treating a sleeping car as a verified location.
MAX_SOURCE_AGE_MIN = 55.0
MAX_CURRENT_GPS_AGE_MIN = 35.0
MIN_LEAD_MIN = 30.0
MAX_LEAD_HOURS = 30.0
DRIVE_SETTLE_MIN = 20.0
EARLY_WINDOW_MIN = 120.0
LATE_WINDOW_MIN = 180.0
ZONE_RADIUS_KM = 0.85


def num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError, OverflowError):
        return None


def dist_km(a, b):
    la, lo = [math.radians(x) for x in a]
    lb, lob = [math.radians(x) for x in b]
    h = math.sin((lb-la)/2)**2 + math.cos(la)*math.cos(lb)*math.sin((lob-lo)/2)**2
    return 12742*math.asin(min(1.0, math.sqrt(max(0.0,h))))


def save_atomic(path, s):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.tripscore-', dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(s)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def open_sidecar(path):
    exists = path.exists()
    con = sqlite3.connect(str(path), timeout=20)
    con.row_factory = sqlite3.Row
    if not exists:
        os.chmod(path, 0o600)
    con.execute('''CREATE TABLE IF NOT EXISTS forecasts (
        id INTEGER PRIMARY KEY,
        forecast_key TEXT NOT NULL UNIQUE,
        captured_at REAL NOT NULL,
        predicted_ts REAL NOT NULL,
        origin_site TEXT NOT NULL,
        destination_site TEXT NOT NULL,
        supporting_days INTEGER NOT NULL,
        pattern_mad_min REAL,
        predicted_soc_drop REAL,
        gps_age_min REAL,
        source_age_min REAL,
        lead_min REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING',
        actual_start_ts REAL,
        actual_end_ts REAL,
        actual_destination TEXT,
        actual_soc_drop REAL,
        error_min REAL,
        destination_match INTEGER,
        soc_error REAL,
        evaluated_at REAL,
        evaluation_note TEXT
    )''')
    con.execute('''CREATE TABLE IF NOT EXISTS scoring_corrections (
        id INTEGER PRIMARY KEY, forecast_id INTEGER NOT NULL, corrected_at REAL NOT NULL,
        previous_end_ts REAL, updated_end_ts REAL,
        previous_soc_drop REAL, updated_soc_drop REAL,
        previous_soc_error REAL, updated_soc_error REAL, reason TEXT NOT NULL
    )''')
    con.execute('CREATE INDEX IF NOT EXISTS ix_trip_outcome_due ON forecasts(status,predicted_ts)')
    con.commit()
    return con


def open_live_db(path):
    # Important: SQLite URI read-only; cannot mutate GHOST's historical data.
    from urllib.parse import quote
    con = sqlite3.connect(f'file:{quote(str(path))}?mode=ro', uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA query_only=ON')
    return con


def get_car(con):
    row = con.execute('SELECT car_id FROM telemetry ORDER BY ts DESC LIMIT 1').fetchone()
    return str(row['car_id']) if row and row['car_id'] else None


def site_for_end(live, car, end_ts, site_registry):
    # Destination GPS is private; it never appears in output files/reports.
    lo, hi = end_ts-300, end_ts+2100
    rows = live.execute('''SELECT ts,shift_state,speed_kmh,raw_json FROM telemetry
                           WHERE car_id=? AND ts BETWEEN ? AND ? ORDER BY ts LIMIT 350''',
                        (car,lo,hi)).fetchall()
    try:
        from trip_sequence_shadow import gps_from_raw
    except ImportError:
        return None
    possibilities=[]
    for r in rows:
        gps=gps_from_raw(r['raw_json'])
        if not gps:
            continue
        speed=num(r['speed_kmh'])
        shift=str(r['shift_state'] or '').upper()
        parked=shift in ('P','PARK','PARKED') or (speed is not None and speed<5)
        penalty=(0 if parked else 10000)+(5000 if r['ts']<end_ts else 0)
        possibilities.append((penalty+abs(r['ts']-end_ts), gps))
    if not possibilities:
        return None
    gps=min(possibilities, key=lambda x:x[0])[1]
    matches=[]
    for sid, rec in (site_registry.get('places') or {}).items():
        lat, lon=num(rec.get('centroid_lat')), num(rec.get('centroid_lon'))
        if lat is None or lon is None:
            continue
        matches.append((dist_km(gps,(lat,lon)),sid))
    if not matches:
        return None
    best=min(matches)
    return best[1] if best[0]<=ZONE_RADIUS_KM else None


def parked_at(live, car, at_ts):
    """Require fresh, multiple, *parked* telemetry observations, not just GPS.

    A stopped car still in Drive does not count as safely parked. Requiring
    samples spanning >=60 seconds avoids a momentary shift into Park.
    """
    rows=live.execute('''SELECT ts,shift_state,speed_kmh FROM telemetry
        WHERE car_id=? AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 40''',
        (car,at_ts-600,at_ts)).fetchall()
    if len(rows)<3 or at_ts-float(rows[0]['ts'])>360:
        return False,'recent parked telemetry unavailable'
    newest=rows[:min(len(rows),10)]
    stable=[]
    for r in newest:
        shift=str(r['shift_state'] or '').strip().upper()
        speed=num(r['speed_kmh'])
        if shift not in {'P','PARK','PARKED'} or (speed is not None and speed>3):
            break
        stable.append(r)
    if len(stable)<3 or float(stable[0]['ts'])-float(stable[-1]['ts'])<60:
        return False,'vehicle is moving or stable Park not verified'
    return True,'parked'


def observed_in_motion(live,car,at_ts):
    """Retrospective capture-quality validation, never delete frozen forecasts."""
    rows=live.execute('''SELECT ts,shift_state,speed_kmh FROM telemetry
        WHERE car_id=? AND ts BETWEEN ? AND ? ORDER BY ts''',
        (car,at_ts-120,at_ts+120)).fetchall()
    moves=0
    for r in rows:
        shift=str(r['shift_state'] or '').strip().upper()
        speed=num(r['speed_kmh']) or 0.0
        if speed>8 or (shift in {'D','DRIVE','R','REVERSE'} and speed>3):
            moves+=1
    return moves>=2


def capture(forecasts, context, now, live=None, car=None):
    info={'captured':False,'reason':None}
    if live is None or not car:
        info['reason']='cannot verify vehicle parked; no live DB'; return info
    parked,why=parked_at(live,car,now)
    if not parked:
        info['reason']=why;return info
    source_ts=num(context.get('generated_at'))
    if source_ts is None or not 0<=now-source_ts<=MAX_SOURCE_AGE_MIN*60:
        info['reason']='stale location-context report'; return info
    current=context.get('current_site') or {}
    gps_age=num(current.get('observation_age_minutes'))
    if gps_age is None or gps_age+(now-source_ts)/60>MAX_CURRENT_GPS_AGE_MIN:
        info['reason']='current parked-location evidence not recent'; return info
    p=context.get('direct_shadow_prediction') or {}
    if not p:
        info['reason']='no direct, location-supported next-trip forecast'; return info
    pred=num(p.get('departure_ts'))
    origin=p.get('origin_site');dest=p.get('destination_site')
    support=int(p.get('support_days') or 0)
    if not pred or not origin or not dest or origin==dest or support<3 or current.get('site')!=origin:
        info['reason']='insufficient direct-route evidence';return info
    lead=(pred-now)/60
    if not MIN_LEAD_MIN<=lead<=MAX_LEAD_HOURS*60:
        info['reason']=f'lead time {lead:.0f} min outside prospective scoring range';return info
    day=datetime.fromtimestamp(pred).strftime('%Y-%m-%d')
    key=f'{day}|{origin}'
    before=forecasts.total_changes
    forecasts.execute('''INSERT OR IGNORE INTO forecasts
      (forecast_key,captured_at,predicted_ts,origin_site,destination_site,supporting_days,
       pattern_mad_min,predicted_soc_drop,gps_age_min,source_age_min,lead_min,status)
      VALUES (?,?,?,?,?,?,?,?,?,?,?, 'PENDING')''',
      (key,now,pred,origin,dest,support,num(p.get('time_mad_minutes')),
       num(p.get('median_soc_drop')),round(gps_age+(now-source_ts)/60,1),
       round((now-source_ts)/60,1),round(lead,1)))
    forecasts.commit()
    info['captured']=forecasts.total_changes>before
    info['reason']='new prediction frozen' if info['captured'] else 'prediction already frozen; original preserved'
    return info

def candidate_drive(live, car, snap, now):
    start=max(snap['captured_at'], snap['predicted_ts']-EARLY_WINDOW_MIN*60)
    end=min(now, snap['predicted_ts']+LATE_WINDOW_MIN*60)
    if end<=start:
        return None
    # First qualifying vehicle trip after snapshot, not nearest to predicted time:
    # this prevents selectively matching only trips that make GHOST look accurate.
    return live.execute('''SELECT start_ts,end_ts,distance_km,soc_change,wh_per_mile
        FROM vehicle_events
        WHERE car_id=? AND event_type='drive' AND start_ts>=? AND start_ts<=?
          AND distance_km>=5 AND distance_km<=250
          AND end_ts>start_ts AND (end_ts-start_ts)<=14400
        ORDER BY start_ts ASC LIMIT 1''',(car,start,end)).fetchone()


def score_one(forecasts, snap, drive, live, car, sites, now):
    actual=num(drive['start_ts'])
    if actual is None:
        return None
    dest=site_for_end(live,car,float(drive['end_ts']),sites)
    soc=num(drive['soc_change']); distance=num(drive['distance_km'])
    whmi=num(drive['wh_per_mile'])
    energy_ok=(soc is not None and -45<=soc<0 and distance is not None
               and 5<=distance<=250 and (whmi is None or 80<=whmi<=700))
    drop=-soc if energy_ok else None
    pred_drop=num(snap['predicted_soc_drop'])
    error=round((actual-snap['predicted_ts'])/60,1)
    hit=int(dest==snap['destination_site']) if dest is not None else None
    soc_error=round(drop-pred_drop,2) if drop is not None and pred_drop is not None else None
    forecasts.execute('''UPDATE forecasts SET status='SCORED',actual_start_ts=?,actual_end_ts=?,
        actual_destination=?,actual_soc_drop=?,error_min=?,destination_match=?,soc_error=?,
        evaluated_at=?,evaluation_note=? WHERE id=? AND status='PENDING' ''',
        (actual,float(drive['end_ts']),dest,drop,error,hit,soc_error,now,
         'Destination GPS not validated' if dest is None else 'Actual next qualifying trip',snap['id']))
    return {'error':error,'destination_match':hit,'soc_error':soc_error}


def trip_complete(live,car,drive,now):
    """Require a genuinely settled drive, tolerating brief arrival maneuvers.

    Never finalize an event while it can still be growing. A stationary reverse
    gear sample shortly after arrival is normal and does not invalidate a later,
    sustained period in Park. Motion, Park->Drive changes, and weak/patchy Park
    evidence remain disqualifying. Reads GHOST telemetry; never controls the car.
    """
    end=num(drive['end_ts'])
    if end is None or end>now-DRIVE_SETTLE_MIN*60:
        return False
    after=live.execute('''SELECT ts,shift_state,speed_kmh FROM telemetry
        WHERE car_id=? AND ts BETWEEN ? AND ? ORDER BY ts''',
        (car,end+120,min(now,end+1800))).fetchall()
    if len(after)<7:
        return False
    park_times=[]
    pre_park_maneuvers=0
    for r in after:
        stamp=float(r['ts'])
        shift=str(r['shift_state'] or '').strip().upper()
        speed=num(r['speed_kmh'])
        # A true movement within the settlement interval means do not finalize.
        if speed is not None and abs(speed)>3:
            return False
        if shift in {'P','PARK','PARKED'}:
            park_times.append(stamp)
            continue
        # Park->Reverse/Drive, or parking maneuvers lasting beyond 6 minutes,
        # would make the event boundary ambiguous. Never use them to score.
        if park_times or stamp>end+360 or pre_park_maneuvers>=2:
            return False
        if shift not in {'R','REVERSE','D','DRIVE','N','NEUTRAL'}:
            return False
        # Only tolerate a confidently stationary gear change on arrival.
        if speed is None or abs(speed)>1:
            return False
        pre_park_maneuvers+=1
    if len(park_times)<6 or park_times[-1]-park_times[0]<600:
        return False
    # Do not treat sparse scattered samples as verified continuous parking.
    if any(b-a>480 for a,b in zip(park_times,park_times[1:])):
        return False
    return True

def quarantine_in_motion(forecasts,live,car,now):
    """Retain prediction but exclude it from accuracy if captured mid-drive."""
    for snap in forecasts.execute("SELECT * FROM forecasts WHERE status='PENDING'").fetchall():
        if observed_in_motion(live,car,float(snap['captured_at'])):
            forecasts.execute('''UPDATE forecasts SET status='INVALID_CAPTURE_IN_MOTION',evaluated_at=?,
                evaluation_note='Forecast frozen while vehicle already driving; excluded from metrics'
                WHERE id=? AND status='PENDING' ''',(now,snap['id']))


def reconcile_premature_scores(forecasts,live,car,sites,now):
    """Correct known v3 partial-trip scores, keep an auditable record."""
    all_scored=forecasts.execute("SELECT * FROM forecasts WHERE status='SCORED' AND actual_start_ts IS NOT NULL").fetchall()
    for snap in all_scored:
        drive=live.execute('''SELECT start_ts,end_ts,distance_km,soc_change,wh_per_mile
          FROM vehicle_events WHERE car_id=? AND event_type='drive'
          AND ABS(start_ts-?)<=5 ORDER BY ABS(start_ts-?) LIMIT 1''',
          (car,snap['actual_start_ts'],snap['actual_start_ts'])).fetchone()
        if not drive or not trip_complete(live,car,drive,now):
            continue
        old_end=num(snap['actual_end_ts']) or 0
        new_end=float(drive['end_ts'])
        if new_end-old_end<=180:
            continue
        soc=num(drive['soc_change']);km=num(drive['distance_km']);wh=num(drive['wh_per_mile'])
        drop=(-soc if soc is not None and -45<=soc<0 and km is not None and
              5<=km<=250 and (wh is None or 80<=wh<=700) else None)
        pred_drop=num(snap['predicted_soc_drop'])
        err=round(drop-pred_drop,2) if drop is not None and pred_drop is not None else None
        dest=site_for_end(live,car,new_end,sites)
        hit=int(dest==snap['destination_site']) if dest is not None else None
        forecasts.execute('''INSERT INTO scoring_corrections
          (forecast_id,corrected_at,previous_end_ts,updated_end_ts,previous_soc_drop,
           updated_soc_drop,previous_soc_error,updated_soc_error,reason)
          VALUES (?,?,?,?,?,?,?,?,?)''',
          (snap['id'],now,old_end,new_end,snap['actual_soc_drop'],drop,
           snap['soc_error'],err,'v3 prematurely scored in-progress drive'))
        forecasts.execute('''UPDATE forecasts SET actual_end_ts=?,actual_destination=?,
           actual_soc_drop=?,destination_match=?,soc_error=?,evaluated_at=?,
           evaluation_note='CORRECTED from premature v3 score; full trip verified; original forecast unchanged'
           WHERE id=? AND status='SCORED' ''',
           (new_end,dest,drop,hit,err,now,snap['id']))


def evaluate(forecasts,live,car,sites,now):
    scored=[]
    quarantine_in_motion(forecasts,live,car,now)
    reconcile_premature_scores(forecasts,live,car,sites,now)
    due=forecasts.execute("SELECT * FROM forecasts WHERE status='PENDING' ORDER BY captured_at").fetchall()
    for snap in due:
        trip=candidate_drive(live,car,snap,now)
        if trip and trip_complete(live,car,trip,now):
            result=score_one(forecasts,snap,trip,live,car,sites,now)
            if result:scored.append(result)
        elif trip:
            # A partial or unverified event is never a completed trip.
            pass
        elif now>snap['predicted_ts']+LATE_WINDOW_MIN*60:
            forecasts.execute('''UPDATE forecasts SET status='UNVERIFIED_NO_TRIP',evaluated_at=?,
                evaluation_note='No verified drive inside window; telemetry coverage not proven'
                WHERE id=? AND status='PENDING' ''',(now,snap['id']))
    forecasts.commit()
    return scored

def fmt_time(ts):
    return datetime.fromtimestamp(float(ts)).strftime('%Y-%m-%d %a %I:%M %p')


def make_report(con, info, now):
    allrows=con.execute('SELECT * FROM forecasts ORDER BY captured_at DESC').fetchall()
    done=[x for x in allrows if x['status']=='SCORED']
    pending=[x for x in allrows if x['status']=='PENDING']
    unverified=[x for x in allrows if x['status']=='UNVERIFIED_NO_TRIP']
    invalid=[x for x in allrows if x['status']=='INVALID_CAPTURE_IN_MOTION']
    corrections=con.execute('SELECT COUNT(*) FROM scoring_corrections').fetchone()[0]
    mae=statistics.mean(abs(x['error_min']) for x in done) if done else None
    within30=sum(abs(x['error_min'])<=30 for x in done)
    verified=[x for x in done if x['destination_match'] is not None]
    energy=[x for x in done if x['soc_error'] is not None]
    soc_mae=statistics.mean(abs(x['soc_error']) for x in energy) if energy else None
    out=[f'GHOST PREDICTION ACCOUNTABILITY {VERSION}',f'Updated: {fmt_time(now)}',
         'SHADOW ONLY — forward predictions captured BEFORE actual trips.',
         'Source AI, trained neural models, Tesla controls, winter readiness unchanged.',
         '', '=== PROSPECTIVE MEASUREMENT ===',
         f'Frozen pre-trip forecasts: {len(allrows)}',
         f'Actual departures scored: {len(done)}',
         f'Pending outcomes: {len(pending)}',
         f'Invalidated captures while moving: {len(invalid)} (excluded)',
         f'Audited corrections to premature v3 scores: {corrections}',
         f'No verified trip outcome: {len(unverified)} (NOT counted as wrong predictions)',
         f'Departure timing MAE: {mae:.1f} min ({len(done)} trips)' if mae is not None else 'Departure timing MAE: WAITING for future trips',
         f'Within ±30 minutes: {within30}/{len(done)}' if done else 'Within ±30 minutes: WAITING',
         f'Destination hits: {sum(x["destination_match"] for x in verified)}/{len(verified)} verified destinations' if verified else 'Destination hits: WAITING for GPS-verified outcomes',
         f'Route SOC drop MAE: {soc_mae:.2f} percentage points ({len(energy)} valid drives)' if soc_mae is not None else 'Route SOC drop MAE: WAITING for valid energy observations',
         '',f'Capture status: {info.get("reason", "no capture attempted")}',
         '', '=== LATEST FROZEN FORECASTS ===']
    if not allrows: out.append('  None captured yet. Keep running; predictions must be saved before a trip.')
    for x in allrows[:8]:
        row=(f'  {fmt_time(x["predicted_ts"])} | {x["origin_site"]} -> {x["destination_site"]} '
             f'| lead {x["lead_min"]:.0f}m | {x["status"]}')
        if x['status']=='SCORED':
            row+=f' | actual {fmt_time(x["actual_start_ts"])} | error {x["error_min"]:+.0f}m'
            if x['destination_match'] is not None: row+=f' | destination {"HIT" if x["destination_match"] else "MISS"}'
            if x['soc_error'] is not None: row+=f' | SOC error {x["soc_error"]:+.1f}pp'
            if x['evaluation_note'] and 'CORRECTED' in x['evaluation_note']: row+=' | corrected complete drive'
        out.append(row)
    out+=['','DATA RULES: No GPS coordinates, addresses, VIN or raw telemetry in this report.',
          'Only predictions recorded beforehand are scored. Unobserved trips are not invented.',
          'This is an evaluation layer, not model retraining or calibrated confidence yet.',
          'PRIVATE sidecar: prediction-eval-v3.sqlite3; do not upload private JSON/registry.']
    return '\n'.join(out)+'\n'


def run(root, dbpath, now):
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root,0o700)
    file=root/'latest-location-context.json'
    if not file.is_file():
        raise SystemExit(f'Missing v2 context: {file}')
    context=json.loads(file.read_text())
    sites_path=root/'stable-zones.json'
    sites=json.loads(sites_path.read_text()) if sites_path.is_file() else {}
    if not dbpath.is_file():
        raise SystemExit(f'Missing GHOST telemetry DB: {dbpath}')
    forecasts=open_sidecar(root/'prediction-eval-v3.sqlite3')
    live=open_live_db(dbpath)
    car=get_car(live)
    if not car:
        raise SystemExit('No car ID in GHOST telemetry DB')
    try:
        # Score old forecasts FIRST, using outcome evidence only. Future model
        # changes must never be allowed to rewrite the earlier prediction.
        evaluate(forecasts,live,car,sites,now)
        status=capture(forecasts,context,now,live,car)
        report=make_report(forecasts,status,now)
        save_atomic(root/'latest-prediction-evaluation.txt',report)
        print(report)
    finally:
        live.close()
        forecasts.close()


def self_test():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        f=open_sidecar(root/'eval.sqlite3')
        # 2:41 prediction, actual 2:45:51, reaches home 4:07:53.
        ts=time.mktime((2026,10,8,14,41,0,0,0,-1))
        at=ts-73*60
        dbfile=root/'live.sqlite3'
        c=sqlite3.connect(dbfile)
        c.execute('CREATE TABLE telemetry(car_id TEXT,ts REAL,shift_state TEXT,speed_kmh REAL,raw_json TEXT)')
        c.execute('CREATE TABLE vehicle_events(car_id TEXT,event_type TEXT,start_ts REAL,end_ts REAL,distance_km REAL,soc_change REAL,wh_per_mile REAL)')
        for sec in range(-5*60,1,60):
            c.execute('INSERT INTO telemetry VALUES(?,?,?,?,?)',('fake',at+sec,'P',0,None))
        start=ts+291  # +4m51s
        mid=ts+34*60
        fin=ts+86*60+53
        for i in range(0,85):
            moment=start+i*60
            c.execute('INSERT INTO telemetry VALUES(?,?,?,?,?)',('fake',moment,'D',65,None))
        for sec in range(120,26*60,60):
            c.execute('INSERT INTO telemetry VALUES(?,?,?,?,?)',('fake',fin+sec,'P',0,None))
        c.execute('INSERT INTO vehicle_events VALUES(?,?,?,?,?,?,?)',('fake','drive',start,mid,10,-2,185.8))
        c.commit()
        live=open_live_db(dbfile)
        context={'generated_at':at-30,'current_site':{'site':'SITE_001','observation_age_minutes':1},
          'direct_shadow_prediction':{'departure_ts':ts,'origin_site':'SITE_001',
          'destination_site':'SITE_002','support_days':7,'time_mad_minutes':9,'median_soc_drop':13}}
        assert capture(f,context,at,live,'fake')['captured']
        assert not capture(f,context,at,live,'fake')['captured']
        # Current drive still running: no score, no additional capture.
        assert evaluate(f,live,'fake',{},ts+50*60)==[]
        assert f.execute('SELECT status FROM forecasts').fetchone()['status']=='PENDING'
        assert not capture(f,{**context,'generated_at':start+25*60},start+25*60,live,'fake')['captured']
        live.close()
        c.execute('UPDATE vehicle_events SET end_ts=?,distance_km=?,soc_change=? WHERE car_id=?',(fin,63.6,-12,'fake'))
        c.commit()
        live=open_live_db(dbfile)
        result=evaluate(f,live,'fake',{},fin+30*60)
        assert len(result)==1 and round(result[0]['error'],2)==4.8
        scored=f.execute("SELECT * FROM forecasts WHERE status='SCORED'").fetchone()
        assert scored['actual_soc_drop']==12 and scored['soc_error']==-1
        # Future false forecast captured while vehicle already driving:
        f.execute('INSERT INTO forecasts(forecast_key,captured_at,predicted_ts,origin_site,destination_site,supporting_days,lead_min,status) VALUES(?,?,?,?,?,?,?,?)',
          ('2026-10-09|SITE_001',start+26*60,ts+24*3600,'SITE_001','SITE_002',7,1410,'PENDING'))
        f.commit()
        evaluate(f,live,'fake',{},fin+30*60)
        assert f.execute("SELECT status FROM forecasts WHERE forecast_key='2026-10-09|SITE_001'").fetchone()[0]=='INVALID_CAPTURE_IN_MOTION'
        # Simulate original v3's premature score and check audited correction.
        f.execute("UPDATE forecasts SET actual_end_ts=?,actual_soc_drop=2,soc_error=-11 WHERE forecast_key='2026-10-08|SITE_001'",(mid,))
        f.commit()
        evaluate(f,live,'fake',{},fin+31*60)
        row=f.execute("SELECT * FROM forecasts WHERE forecast_key='2026-10-08|SITE_001'").fetchone()
        assert row['actual_soc_drop']==12 and row['soc_error']==-1
        assert f.execute('SELECT count(*) FROM scoring_corrections').fetchone()[0]==1
        text=make_report(f,{'reason':'tested'},fin+31*60)
        assert 'Invalidated captures while moving: 1' in text and '11.0pp' not in text
        # Real-world regression: one stationary Reverse sample at +3 min,
        # followed by sustained Park. v3.1 refused to reconcile this case.
        live.close()
        c.execute('DELETE FROM telemetry WHERE car_id=? AND ts BETWEEN ? AND ?',
                  ('fake',fin+120,fin+1800))
        c.execute('INSERT INTO telemetry VALUES(?,?,?,?,?)',('fake',fin+180,'R',0,None))
        for sec in range(240,29*60,60):
            c.execute('INSERT INTO telemetry VALUES(?,?,?,?,?)',('fake',fin+sec,'P',0,None))
        c.commit()
        live=open_live_db(dbfile)
        checkdrive=live.execute('SELECT * FROM vehicle_events WHERE car_id=?',('fake',)).fetchone()
        assert trip_complete(live,'fake',checkdrive,fin+31*60), 'arrival Reverse sample should be tolerated'
        # The exact Oct 8 regression: an old partial 2% score must become 12%
        # even when the first post-drive sample reports stationary Reverse.
        f.execute("UPDATE forecasts SET actual_end_ts=?,actual_soc_drop=2,soc_error=-11 WHERE forecast_key='2026-10-08|SITE_001'",(mid,))
        f.commit()
        before_corrections=f.execute('SELECT count(*) FROM scoring_corrections').fetchone()[0]
        evaluate(f,live,'fake',{},fin+31*60)
        corrected=f.execute("SELECT * FROM forecasts WHERE forecast_key='2026-10-08|SITE_001'").fetchone()
        assert corrected['actual_soc_drop']==12 and corrected['soc_error']==-1
        assert f.execute('SELECT count(*) FROM scoring_corrections').fetchone()[0]==before_corrections+1
        live.close()
        # But motion AFTER entering Park must invalidate settlement.
        c.execute('INSERT INTO telemetry VALUES(?,?,?,?,?)',('fake',fin+13*60,'D',20,None))
        c.commit()
        live=open_live_db(dbfile)
        assert not trip_complete(live,'fake',checkdrive,fin+31*60), 'post-Park motion must be rejected'
        live.close();c.close();f.close()
    print('SELF-TEST PASS: full-drive correction, transient stationary Reverse, post-Park motion rejection, frozen forecasts')

def main():
    pa=argparse.ArgumentParser()
    pa.add_argument('--root',type=Path,default=ROOT)
    pa.add_argument('--live-db',type=Path,default=GHOST_DB)
    pa.add_argument('--self-test',action='store_true')
    args=pa.parse_args()
    if args.self_test: self_test(); return
    run(args.root,args.live_db,time.time())

if __name__=='__main__':
    main()

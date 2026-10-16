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
SCORING_PATCH = '2026-10-13-segment-arrival-v1.2'  # keep API version used by v5
MAX_SEGMENT_GAP_SEC = 420.0
from . import config
ROOT = Path(config.get('GHOST_TRIP_SHADOW_DIR', str(config.DATA_DIR / 'trip-sequence')))
GHOST_DB = config.DB_PATH
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
        from .trip_sequence_shadow import gps_from_raw
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

def _event_number(row, key):
    try:
        return num(row[key])
    except (IndexError, KeyError, TypeError):
        return None


def _compatible_segments(live, car, previous, following):
    '''Do not join separate trips across a parked/charging stop or telemetry motion gap.'''
    gap = float(following['start_ts']) - float(previous['end_ts'])
    if gap < -5 or gap > MAX_SEGMENT_GAP_SEC:
        return False
    if _event_number(previous, 'distance_km') is None or _event_number(following, 'distance_km') is None:
        return False
    # Only accept nontrivial, measured pieces, not a zero-distance wake-up.
    if min(float(previous['distance_km']), float(following['distance_km'])) < 1.0:
        return False
    # A known park/charge event is an explicit trip boundary even if short.
    boundary = live.execute('''SELECT 1 FROM vehicle_events WHERE car_id=?
        AND event_type IN ('park','charge') AND start_ts < ? AND end_ts > ? LIMIT 1''',
        (car, float(following['start_ts']), float(previous['end_ts']))).fetchone()
    if boundary:
        return False
    # Don't bridge gaps where SOC inexplicably rose (e.g. charged without a recorded event).
    old_soc = _event_number(previous, 'end_soc')
    new_soc = _event_number(following, 'start_soc')
    if old_soc is not None and new_soc is not None and new_soc > old_soc + 1.0:
        return False
    return True


def _combined_drive(segments):
    '''A joined trip is read-only. Original vehicle_events are never rewritten.'''
    first, last = segments[0], segments[-1]
    distance = sum(float(x['distance_km']) for x in segments)
    start_soc = _event_number(first, 'start_soc')
    end_soc = _event_number(last, 'end_soc')
    if start_soc is not None and end_soc is not None:
        soc_change = end_soc - start_soc
    else:
        vals = [_event_number(x, 'soc_change') for x in segments]
        soc_change = sum(vals) if all(x is not None for x in vals) else None
    energy = [_event_number(x, 'energy_used_kwh') for x in segments]
    if all(x is not None and x >= 0 for x in energy) and distance > 0:
        whmi = 1000 * sum(energy) / (distance / 1.609344)
    else:
        vals = [(_event_number(x, 'wh_per_mile'), _event_number(x, 'distance_km')) for x in segments]
        whmi = sum(a*b for a,b in vals)/distance if all(a is not None and b is not None for a,b in vals) else None
    return {'start_ts': float(first['start_ts']), 'end_ts': float(last['end_ts']),
            'distance_km': distance, 'soc_change': soc_change,
            'wh_per_mile': whmi, 'segment_count': len(segments)}


def _drive_groups(live, car, start, end):
    # Start with every nontrivial segment so a short initial movement is retained.
    # Only groups containing >=5km and <=250km qualify as commutes.
    rows = live.execute('''SELECT * FROM vehicle_events WHERE car_id=? AND event_type='drive'
        AND start_ts BETWEEN ? AND ? AND end_ts>start_ts
        AND distance_km>=1 AND distance_km<=250 AND end_ts-start_ts<=14400
        ORDER BY start_ts''', (car, start - MAX_SEGMENT_GAP_SEC, end)).fetchall()
    groups = []
    for row in rows:
        if groups and _compatible_segments(live, car, groups[-1][-1], row):
            groups[-1].append(row)
        else:
            groups.append([row])
    for group in groups:
        combined = _combined_drive(group)
        if (combined['start_ts'] >= start and combined['start_ts'] <= end
                and 5 <= combined['distance_km'] <= 250
                and 0 < combined['end_ts'] - combined['start_ts'] <= 14400):
            yield combined


def candidate_drive(live, car, snap, now):
    start = max(float(snap['captured_at']), float(snap['predicted_ts']) - EARLY_WINDOW_MIN*60)
    end = min(now, float(snap['predicted_ts']) + LATE_WINDOW_MIN*60)
    if end <= start:
        return None
    # Always take FIRST qualifying trip, not the most prediction-friendly trip.
    return next(_drive_groups(live, car, start, end), None)


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

def _event_confirmed_park(live, car, drive, now):
    """Corroborated Park-event fallback for unreliable/missing gear telemetry.

    Source of truth is an independent long-duration, near-zero-distance Park
    event plus sequential raw telemetry. Explicit meaningful Drive/Reverse,
    moving speed, moving odometer, an intervening trip/charge, sparse samples,
    or a short event all cause fail-closed. No synthetic drive/GPS is created.
    """
    ok, _ = _park_event_verification(live, car, drive, now)
    return ok


def _park_event_verification(live, car, drive, now):
    """Return bool and coordinate-free verification trace for live preflight."""
    end = num(drive['end_ts'])
    if end is None or now < end + DRIVE_SETTLE_MIN * 60:
        return False, 'drive is not settled for 20 minutes'
    try:
        parks = live.execute("""SELECT start_ts,end_ts,distance_km,source_points
            FROM vehicle_events WHERE car_id=? AND event_type='park'
            AND start_ts BETWEEN ? AND ? ORDER BY start_ts LIMIT 5""",
            (car, end-90, end+300)).fetchall()
    except sqlite3.OperationalError:
        return False, 'Park event schema unavailable'
    if not parks:
        return False, 'no adjacent independent Park event'
    columns = {r[1] for r in live.execute('PRAGMA table_info(telemetry)').fetchall()}
    odo_expr = 'odometer_km' if 'odometer_km' in columns else 'NULL AS odometer_km'
    findings = []
    for park in parks:
        begin, finish = float(park['start_ts']), float(park['end_ts'])
        park_distance = _event_number(park, 'distance_km')
        count = _event_number(park, 'source_points')
        minutes = (finish-begin)/60
        if not (finish >= end+1200 and minutes >= 20 and
                park_distance is not None and 0 <= park_distance <= .2 and
                count is not None and count >= 8):
            findings.append('Park event duration/distance/source-point threshold failed')
            continue
        # Check the FULL recorded Park interval, not just the first 20 min.
        # This matters with sleeping cars producing sparse telemetry.
        other = live.execute("""SELECT event_type FROM vehicle_events WHERE car_id=?
            AND event_type IN ('drive','charge') AND start_ts < ? AND end_ts > ? LIMIT 1""",
            (car, finish, end)).fetchone()
        if other:
            findings.append('intervening drive/charge event')
            continue
        # The drive event END timestamp may be its final MOVING telemetry point.
        # Never apply parked-speed rules to that driving endpoint.  Instead
        # corroborate the *independent* Park event with telemetry within its
        # own start/end bounds, and check any interval between the events for
        # a distinct movement (not a brief arrival maneuver).
        if begin > end + 180:
            findings.append('Park event starts >3 minutes after end of drive')
            continue
        gap_rows = live.execute(f"""SELECT ts,shift_state,speed_kmh,{odo_expr} FROM telemetry
            WHERE car_id=? AND ts > ? AND ts < ? ORDER BY ts""",
            (car, end, begin)).fetchall()
        gap_speeds = [num(r['speed_kmh']) for r in gap_rows]
        gap_odos = [num(r['odometer_km']) for r in gap_rows]
        valid_gap_odometer = [x for x in gap_odos if x is not None]
        # A short low-speed final parking maneuver is not an extra commute.
        # Significant or repeated intervening movement still fails closed.
        if (any(s is not None and abs(s)>30 for s in gap_speeds)
                or sum(s is not None and abs(s)>10 for s in gap_speeds)>=2
                or (len(valid_gap_odometer)>=2 and max(valid_gap_odometer)-min(valid_gap_odometer)>.12)):
            findings.append('distinct movement observed between driving and parking')
            continue
        rows = live.execute(f"""SELECT ts,shift_state,speed_kmh,{odo_expr} FROM telemetry
            WHERE car_id=? AND ts BETWEEN ? AND ? ORDER BY ts""",
            (car, begin, min(finish, now))).fetchall()
        if len(rows) < 6 or float(rows[-1]['ts'])-float(rows[0]['ts']) < 600:
            findings.append(f'telemetry in Park event too sparse: {len(rows)} samples')
            continue
        observed_speed = [num(r['speed_kmh']) for r in rows]
        speeds = [x for x in observed_speed if x is not None]
        odos = [num(r['odometer_km']) for r in rows]
        odos = [x for x in odos if x is not None]
        shifts = [str(r['shift_state'] or '').strip().upper() for r in rows]
        drive_gears = {'D','DRIVE','R','REVERSE'}
        if any(abs(speed)>3 for speed in speeds):
            findings.append('movement measured by speed DURING independently recorded Park event')
            continue
        if len(odos)>=2 and max(odos)-min(odos)>.12:
            findings.append('post-arrival odometer movement >120 meters')
            continue
        if any(shift in drive_gears and ((observed_speed[i] is not None and
              abs(observed_speed[i])>1) or float(rows[i]['ts'])>begin+180)
              for i,shift in enumerate(shifts)):
            findings.append('active Drive/Reverse observed after parking')
            continue
        if sum(shift in drive_gears for shift in shifts)>3:
            findings.append('repeated Drive/Reverse gear evidence')
            continue
        if len(speeds)<6 or float(rows[-1]['ts'])-float(rows[0]['ts'])<600:
            findings.append('insufficient speed corroboration')
            continue
        parked = [float(r['ts']) for r,shift in zip(rows,shifts)
                  if shift in {'P','PARK','PARKED'} and float(r['ts'])>=begin]
        explicit_park = len(parked)>=3 and parked[-1]-parked[0]>=300
        # If gear is unknown, demand STRONGER independent evidence, never
        # silently treat a car in Drive as Park.
        if not explicit_park:
            benign = {'','UNKNOWN','NONE','N','NEUTRAL','P','PARK','PARKED'}
            if (any(shift not in benign and shift not in drive_gears for shift in shifts)
                or minutes<25 or count<12 or park_distance>.05
                or len(speeds)<8 or float(rows[-1]['ts'])-float(rows[0]['ts'])<900):
                findings.append('unknown gear with insufficient stronger parked proof')
                continue
        return True, ('PASS: independent Park %.1fmin / %.3fkm / %d event points; '
                      '%d telemetry samples / %d speed samples / %d Park-gear samples; '
                      'odometer range=%s km; gear=%s' %
                      (minutes,park_distance,count,len(rows),len(speeds),len(parked),
                       ('%.3f' % (max(odos)-min(odos))) if len(odos)>=2 else 'missing',
                       'explicit Park' if explicit_park else 'sensor-limited, corroborated'))
    return False, '; '.join(findings[:3])


_trip_complete_strict = trip_complete


def trip_complete(live, car, drive, now):
    return _trip_complete_strict(live, car, drive, now) or _event_confirmed_park(live, car, drive, now)


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
        # Reconstruct the first full commute from its original scored start.
        # This also corrects historical scores that captured only the first leg.
        anchor=float(snap['actual_start_ts'])
        drive=next((trip for trip in _drive_groups(live,car,anchor-2,anchor+2)
                    if abs(trip['start_ts']-anchor)<=2), None)
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
            # Keep the frozen forecast eligible for late-arriving evidence;
            # explain why it is pending instead of silently leaving it stuck.
            forecasts.execute('''UPDATE forecasts SET evaluation_note=?
                WHERE id=? AND status='PENDING' ''',
                ('Observed drive, but settled arrival was not independently verified; excluded from accuracy', snap['id']))
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
    awaiting_arrival=sum(x['status']=='PENDING' and 'settled arrival' in (x['evaluation_note'] or '') for x in allrows)
    invalid=[x for x in allrows if x['status']=='INVALID_CAPTURE_IN_MOTION']
    corrections=con.execute('SELECT COUNT(*) FROM scoring_corrections').fetchone()[0]
    mae=statistics.mean(abs(x['error_min']) for x in done) if done else None
    within30=sum(abs(x['error_min'])<=30 for x in done)
    verified=[x for x in done if x['destination_match'] is not None]
    energy=[x for x in done if x['soc_error'] is not None]
    soc_mae=statistics.mean(abs(x['soc_error']) for x in energy) if energy else None
    out=[f'GHOST PREDICTION ACCOUNTABILITY {VERSION} ({SCORING_PATCH})',f'Updated: {fmt_time(now)}',
         'SHADOW ONLY — forward predictions captured BEFORE actual trips.',
         'Source AI, trained neural models, Tesla controls, winter readiness unchanged.',
         '', '=== PROSPECTIVE MEASUREMENT ===',
         f'Frozen pre-trip forecasts: {len(allrows)}',
         f'Actual departures scored: {len(done)}',
         f'Pending outcomes: {len(pending)} (including {awaiting_arrival} observed drives awaiting arrival proof)',
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

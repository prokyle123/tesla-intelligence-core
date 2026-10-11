#!/usr/bin/env python3
"""GHOST Trip Sequence Intelligence v1: read-only evidence, no production overrides.

Reads vehicle_events and selected nearby telemetry records, learns anonymous
frequent parking zones and empirical next-drive relationships. Writes local
private sidecar reports, never writes to GHOST's live SQLite database.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
import math
import os
from pathlib import Path
import sqlite3
import statistics
import time
from urllib.parse import quote

VERSION = "trip-sequence-shadow-v1.0.0"
MI = 0.621371
ZONE_RADIUS_KM = 0.85


def n(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError, OverflowError):
        return None


def km_between(a, b):
    if a is None or b is None:
        return None
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    z = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    return 12742 * math.asin(min(1.0, math.sqrt(z)))


def gps_from_raw(raw):
    """Only known Tesla state paths; never mistake an arbitrary nested lat/lon for vehicle GPS."""
    try:
        j = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(j, dict):
        return None
    paths = [j]
    if isinstance(j.get('data'), dict):
        paths.append(j['data'])
    if isinstance(j.get('state'), dict):
        paths.append(j['state'])
    if isinstance(j.get('vehicle'), dict):
        paths.append(j['vehicle'])
    for root in paths:
        candidates = [root.get('drive_state'), root.get('location')]
        if root is j:
            candidates.append(root)
        for c in candidates:
            if not isinstance(c, dict):
                continue
            lat = n(c.get('latitude', c.get('lat')))
            lon = n(c.get('longitude', c.get('lon', c.get('lng'))))
            if lat is not None and lon is not None and -90 < lat < 90 and -180 < lon < 180 and abs(lat) > 1 and abs(lon) > 1:
                return (lat, lon)
    return None


def local_day(ts):
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d')


def dow_group(ts):
    return 'weekday' if datetime.fromtimestamp(ts).weekday() < 5 else 'weekend'


def minute(ts):
    t = datetime.fromtimestamp(ts)
    return t.hour * 60 + t.minute


def hhmm(m):
    return f'{int(m) // 60:02d}:{int(m) % 60:02d}'


def robust_time_patterns(events, group_field='group', max_gap=85, min_days=3):
    """Discover time clusters; count at most one representative per day and cluster."""
    groups = defaultdict(list)
    for ev in events:
        key = ev.get(group_field)
        if key is not None:
            groups[key].append(ev)
    patterns = []
    for key, values in groups.items():
        vals = sorted(values, key=lambda e: e['minute'])
        clusters = []
        for item in vals:
            if not clusters or item['minute'] - clusters[-1][-1]['minute'] > max_gap:
                clusters.append([item])
            else:
                clusters[-1].append(item)
        for cluster in clusters:
            # A single day cannot inflate recurrence by taking multiple short drives.
            per_day = {}
            med = statistics.median(v['minute'] for v in cluster)
            for v in cluster:
                day = v['day']
                if day not in per_day or abs(v['minute'] - med) < abs(per_day[day]['minute'] - med):
                    per_day[day] = v
            usable = list(per_day.values())
            if len(usable) < min_days:
                continue
            m = statistics.median(v['minute'] for v in usable)
            mad = statistics.median(abs(v['minute'] - m) for v in usable)
            patterns.append({'group': key, 'time': hhmm(round(m)), 'minute': round(m),
                             'support_days': len(usable), 'mad_minutes': round(mad, 1)})
    return sorted(patterns, key=lambda p: (str(p['group']), p['minute']))


def current_car(con):
    row = con.execute('SELECT car_id FROM telemetry ORDER BY ts DESC LIMIT 1').fetchone()
    return str(row['car_id']) if row and row['car_id'] else None


def at_boundary(con, car_id, stamp, phase):
    """Anchor GPS near trip edge, prefer parked samples, never reuse old GPS."""
    if phase == 'start':
        lo, hi = stamp - 35 * 60, stamp + 5 * 60
    else:
        lo, hi = stamp - 5 * 60, stamp + 35 * 60
    rows = con.execute('''SELECT ts,speed_kmh,shift_state,raw_json FROM telemetry
                          WHERE car_id=? AND ts BETWEEN ? AND ? ORDER BY ts LIMIT 250''',
                       (car_id, lo, hi)).fetchall()
    options = []
    for r in rows:
        gps = gps_from_raw(r['raw_json'])
        if gps is None:
            continue
        speed = n(r['speed_kmh'])
        shift = str(r['shift_state'] or '').upper()
        parked = shift in ('P', 'PARK', 'PARKED') or (speed is not None and speed < 5)
        ts = float(r['ts'])
        # Prefer pre-departure location or post-arrival location; penalize opposite side.
        wrong_side = (phase == 'start' and ts > stamp) or (phase == 'end' and ts < stamp)
        penalty = (0 if parked else 10000) + (5000 if wrong_side else 0)
        options.append((penalty + abs(ts - stamp), gps))
    return min(options, key=lambda x: x[0])[1] if options else None


def discover_zones(drives):
    points = []
    for i, d in enumerate(drives):
        for side in ('start_gps', 'end_gps'):
            if d.get(side):
                points.append((i, side, d[side]))
    parent = list(range(len(points)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            if km_between(points[i][2], points[j][2]) <= ZONE_RADIUS_KM:
                parent[find(j)] = find(i)
    components = defaultdict(list)
    for i, point in enumerate(points):
        components[find(i)].append(point)
    ranked = sorted(components.values(), key=len, reverse=True)
    zones = []
    for cluster in ranked:
        # Single observations don't establish a recurring parking location.
        if len(cluster) < 2:
            continue
        zid = f'ZONE_{len(zones) + 1}'
        locs = [x[2] for x in cluster]
        centroid = (statistics.median(x[0] for x in locs), statistics.median(x[1] for x in locs))
        days = {drives[x[0]]['day'] for x in cluster}
        zones.append({'id': zid, 'visits': len(cluster), 'observed_days': len(days),
                      'centroid_lat': round(centroid[0], 6), 'centroid_lon': round(centroid[1], 6)})
    for d in drives:
        for side, out in (('start_gps', 'from_zone'), ('end_gps', 'to_zone')):
            d[out] = None
            if d.get(side) is not None and zones:
                matches = [(km_between(d[side], (z['centroid_lat'], z['centroid_lon'])), z['id']) for z in zones]
                best = min(matches)
                if best[0] <= ZONE_RADIUS_KM:
                    d[out] = best[1]
    return zones


def energy_valid(d):
    # A recording can span charging or missing observations. Never train on SOC gain during a drive.
    soc = n(d.get('soc_change'))
    dist_mi = d['distance_km'] * MI
    whmi = n(d.get('wh_per_mile'))
    if soc is None or soc >= 0 or soc < -45 or dist_mi < 1 or dist_mi > 150:
        return False
    if whmi is not None and not 80 <= whmi <= 700:
        return False
    return True


def learn(con, days=60, now=None):
    now = time.time() if now is None else float(now)
    car = current_car(con)
    if car is None:
        raise RuntimeError('No car telemetry rows found')
    cutoff = now - days * 86400
    raw = con.execute('''SELECT start_ts,end_ts,duration_min,distance_km,soc_change,wh_per_mile
                         FROM vehicle_events WHERE car_id=? AND event_type='drive' AND start_ts>=?
                         ORDER BY start_ts''', (car, cutoff)).fetchall()
    drives = []
    quality = Counter()
    for row in raw:
        dist = n(row['distance_km'])
        dur = n(row['duration_min'])
        a, b = n(row['start_ts']), n(row['end_ts'])
        if dist is None or dist < 5 or dist > 250 or a is None or b is None or b <= a or (dur is not None and dur > 240):
            quality['rejected_fragments_or_outliers'] += 1
            continue
        d = dict(row)
        d.update(day=local_day(a), group=dow_group(a), minute=minute(a), start_ts=a, end_ts=b,
                 distance_km=dist)
        d['energy_valid'] = energy_valid(d)
        quality['energy_valid' if d['energy_valid'] else 'energy_excluded'] += 1
        d['start_gps'] = at_boundary(con, car, a, 'start')
        d['end_gps'] = at_boundary(con, car, b, 'end')
        # If a real trip's two endpoints are identical despite substantial distance,
        # the cached GPS is likely stale; exclude its locations, not the entire trip.
        sep = km_between(d['start_gps'], d['end_gps'])
        if sep is not None and dist >= 15 and sep < 1.0:
            d['start_gps'], d['end_gps'] = None, None
            quality['stale_gps_pairs_rejected'] += 1
        drives.append(d)
    zones = discover_zones(drives)
    quality['eligible_drives'] = len(drives)
    quality['geo_labeled_drives'] = sum(bool(d['from_zone'] or d['to_zone']) for d in drives)
    quality['geo_complete_drives'] = sum(bool(d['from_zone'] and d['to_zone']) for d in drives)
    time_patterns = robust_time_patterns(drives)

    links = defaultdict(list)
    for d in drives:
        if d['from_zone'] and d['to_zone'] and d['from_zone'] != d['to_zone']:
            links[(d['from_zone'], d['to_zone'], d['group'])].append(d)
    transitions = []
    for (start, end, group), items in links.items():
        ds = len({d['day'] for d in items})
        if ds < 2:
            continue
        t = statistics.median(d['minute'] for d in items)
        en = [d for d in items if d['energy_valid']]
        transitions.append({'from': start, 'to': end, 'group': group,
                            'support_days': ds, 'typical_departure': hhmm(round(t)),
                            'typical_departure_minute': round(t),
                            'time_mad_minutes': round(statistics.median(abs(d['minute'] - t) for d in items), 1),
                            'median_distance_mi': round(statistics.median(d['distance_km'] * MI for d in items), 1),
                            'energy_samples': len(en),
                            'median_soc_drop': round(statistics.median(-d['soc_change'] for d in en), 1) if en else None})
    transitions.sort(key=lambda d: (-d['support_days'], d['from'], d['to']))

    chains = []
    counts = defaultdict(list)
    for one, two in zip(drives, drives[1:]):
        gap_h = (two['start_ts'] - one['end_ts']) / 3600
        if not 0 <= gap_h <= 24:
            continue
        if one['to_zone'] and one['to_zone'] == two['from_zone'] and one['from_zone'] and two['to_zone']:
            counts[(one['from_zone'], one['to_zone'], two['to_zone'], one['group'])].append((one['day'], gap_h))
    for (a, b, c, group), sample in counts.items():
        support = len(set(x[0] for x in sample))
        if support >= 2:
            chains.append({'sequence': f'{a} -> {b} -> {c}', 'group': group,
                           'support_days': support, 'typical_park_hours': round(statistics.median(x[1] for x in sample), 1)})
    chains.sort(key=lambda c: -c['support_days'])

    current = None
    latest = con.execute('''SELECT ts,speed_kmh,shift_state,raw_json FROM telemetry
                            WHERE car_id=? AND ts>=? ORDER BY ts DESC LIMIT 160''', (car, now - 3*3600)).fetchall()
    for r in latest:
        pos = gps_from_raw(r['raw_json'])
        if pos is None:
            continue
        speed = n(r['speed_kmh'])
        shift = str(r['shift_state'] or '').upper()
        if speed is not None and speed >= 5 and shift not in ('P', 'PARK', 'PARKED'):
            continue
        zs = [(km_between(pos, (z['centroid_lat'], z['centroid_lon'])), z['id']) for z in zones]
        near = min(zs) if zs else None
        current = {'zone': near[1] if near and near[0] <= ZONE_RADIUS_KM else 'UNKNOWN_ZONE',
                   'observation_age_minutes': round((now - float(r['ts'])) / 60, 1)}
        break

    location_prediction = None
    if current and current['zone'] != 'UNKNOWN_ZONE':
        candidates = []
        for tr in transitions:
            if tr['from'] != current['zone'] or tr['support_days'] < 3:
                continue
            for day_offset in (0, 1):
                dt = datetime.fromtimestamp(now)
                from datetime import timedelta
                day = (dt + timedelta(days=day_offset)).date()
                if (day.weekday() < 5) != (tr['group'] == 'weekday'):
                    continue
                predicted = time.mktime((day.year, day.month, day.day, 0, 0, 0, 0, 0, -1)) + tr['typical_departure_minute']*60
                if predicted <= now + 5 * 60:
                    continue
                candidates.append((predicted, tr))
        if candidates:
            predicted, tr = min(candidates, key=lambda x: x[0])
            location_prediction = {'departure_ts': predicted,
                                   'departure_local': datetime.fromtimestamp(predicted).isoformat(timespec='minutes'),
                                   'origin_zone': tr['from'], 'destination_zone': tr['to'],
                                   'support_days': tr['support_days'], 'mad_minutes': tr['time_mad_minutes'],
                                   'median_soc_drop': tr['median_soc_drop'],
                                   'status': 'SHADOW_ONLY_NOT_CALIBRATED'}

    return {'model_version': VERSION, 'trained_at': now, 'lookback_days': days,
            'quality': dict(quality), 'anonymous_zones': zones,
            'time_patterns': time_patterns, 'zone_transitions': transitions,
            'trip_chains': chains, 'current_location': current,
            'location_next_trip_prediction': location_prediction,
            'production_predictions_unchanged': True,
            'notes': ['Training evidence comes only from recorded drive events and nearby vehicle GPS.',
                      'Anonymous zone centers are private and stored only on Ghost Pi.',
                      'Confidence is NOT a calibrated prediction success probability.',
                      'When GPS is missing, no location inference is invented.']}


def make_report(m):
    q = m['quality']
    lines = [f'GHOST TRIP SEQUENCE SHADOW — {VERSION}',
             f'Generated: {datetime.fromtimestamp(m["trained_at"]).isoformat(timespec="seconds")}',
             'SHADOW MODE: no changes to live departure learning, readiness, neural models, or vehicle.', '',
             f'Drives used: {q.get("eligible_drives", 0)} | Rejected fragments: {q.get("rejected_fragments_or_outliers", 0)}',
             f'Energy samples accepted: {q.get("energy_valid", 0)} | excluded: {q.get("energy_excluded", 0)}',
             f'GPS-labeled drives: {q.get("geo_labeled_drives", 0)} | complete endpoints: {q.get("geo_complete_drives", 0)}',
             f'Stale GPS pairs excluded: {q.get("stale_gps_pairs_rejected", 0)}', '',
             'TIME-ONLY PATTERNS (no location assumption):']
    for p in m['time_patterns']:
        lines.append(f'  {p["group"]:8s} {p["time"]} | support {p["support_days"]} distinct days | MAD ±{p["mad_minutes"]} min')
    if not m['time_patterns']:
        lines.append('  No supported patterns yet.')
    lines.extend(['', 'ANONYMOUS PARKING ZONES:'])
    for z in m['anonymous_zones'][:12]:
        lines.append(f'  {z["id"]}: {z["visits"]} endpoint observations on {z["observed_days"]} days')
    if not m['anonymous_zones']:
        lines.append('  No verified recurring GPS zones. Check GPS availability in telemetry raw_json.')
    lines.extend(['', 'OBSERVED ZONE-TO-ZONE TRIPS:'])
    for t in m['zone_transitions'][:18]:
        drop = f'{t["median_soc_drop"]}%' if t['median_soc_drop'] is not None else 'not enough clean energy data'
        lines.append(f'  {t["from"]} -> {t["to"]} | {t["group"]} {t["typical_departure"]} | {t["support_days"]} days | {t["median_distance_mi"]} mi | SOC drop {drop}')
    if not m['zone_transitions']:
        lines.append('  Insufficient verified GPS-linked trips; not inventing destinations.')
    lines.extend(['', 'LEARNED TRIP CHAINS:'])
    for c in m['trip_chains'][:12]:
        lines.append(f'  {c["sequence"]} | {c["group"]} | {c["support_days"]} days | park {c["typical_park_hours"]} h')
    if not m['trip_chains']:
        lines.append('  Insufficient verified continuous location sequence evidence.')
    lines.extend(['', 'CURRENT LOCATION CONTEXT:'])
    loc = m['current_location']
    lines.append(f'  {loc["zone"]} (observation {loc["observation_age_minutes"]} min old)' if loc else '  Unavailable from recent parked telemetry.')
    lines.append('SHADOW NEXT TRIP:')
    p = m['location_next_trip_prediction']
    lines.append(f'  {p["departure_local"]} | {p["origin_zone"]} -> {p["destination_zone"]} | {p["support_days"]} support days' if p else '  No location-aware prediction supported yet; production adaptive schedule remains in control.')
    lines.extend(['', 'DATA RULE: This report does not disclose coordinates or home/work addresses.',
                  'PRIVATE JSON: latest.json contains zone-center coordinates; keep it on the Pi.',
                  'This learner does not modify existing trained models.'])
    return '\n'.join(lines) + '\n'


def self_test():
    assert gps_from_raw({'state': {'drive_state': {'latitude': 41.6, 'longitude': -87.3}}}) == (41.6, -87.3)
    assert gps_from_raw({'data': {'drive_state': {'latitude': 0, 'longitude': 0}}}) is None
    assert km_between((41.6, -87.3), (41.6, -87.3)) == 0
    synthetic = []
    for d in range(7):
        synthetic.extend([{'day': f'D{d}', 'group': 'weekday', 'minute': 375 + d % 3},
                          {'day': f'D{d}', 'group': 'weekday', 'minute': 875 + d % 5}])
    patterns = robust_time_patterns(synthetic)
    assert len(patterns) == 2, patterns
    assert all(p['support_days'] == 7 for p in patterns), patterns
    assert energy_valid({'distance_km': 63, 'soc_change': -13, 'wh_per_mile': 240})
    assert not energy_valid({'distance_km': 63, 'soc_change': 12, 'wh_per_mile': 240})
    print('SELF-TEST PASS: GPS paths, time clusters, SOC anomaly filtering')


def main():
    pa = argparse.ArgumentParser()
    pa.add_argument('--self-test', action='store_true')
    pa.add_argument('--db', default='/var/lib/ghost-tesla-ai/ghost_ai.sqlite3')
    pa.add_argument('--out', default='/home/ghost/ghost-trip-sequence')
    pa.add_argument('--days', type=int, default=60)
    args = pa.parse_args()
    if args.self_test:
        self_test()
        return
    source = Path(args.db)
    if not source.is_file():
        raise SystemExit(f'Cannot find GHOST AI DB: {source}')
    dsn = 'file:' + quote(str(source), safe='/') + '?mode=ro'
    con = sqlite3.connect(dsn, uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA query_only=ON')
    con.execute('PRAGMA busy_timeout=15000')
    try:
        m = learn(con, days=max(7, min(args.days, 180)))
    finally:
        con.close()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    os.chmod(out, 0o700)
    for name, contents in [('latest.json', json.dumps(m, indent=2) + '\n'),
                           ('latest.txt', make_report(m))]:
        temporary = out / (name + '.tmp')
        fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(contents)
        os.replace(temporary, out / name)
    print(make_report(m))


if __name__ == '__main__':
    main()

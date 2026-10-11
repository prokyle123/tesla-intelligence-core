#!/usr/bin/env python3
"""GHOST v6: location relationships + deduplicated, prospective accuracy.

Independent shadow reader: consumes v2 / v3.2 / v5 output without modifying
any of their databases or the live departure / neural systems.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta
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

VERSION = 'relationship-coverage-shadow-v6.0.0'
TZ = ZoneInfo('America/Chicago')
ROOT = Path('/home/ghost/ghost-trip-sequence')
NEARBY_MAX_KM = 2.5
MIN_LINK_DAYS = 4
MIN_CHAIN_DAYS = 3
MAX_FRESH_GPS_MIN = 35
DEDUP_START_SECONDS = 2*60


def val(x):
    try:
        n = float(x)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError, OverflowError):
        return None


def local(ts):
    return datetime.fromtimestamp(float(ts), TZ)


def display(ts):
    return local(ts).strftime('%Y-%m-%d %a %I:%M %p') if ts is not None else '—'


def atomic(path, contents):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.v6-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write(contents)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError('Unexpected JSON object format: '+str(path))
    return obj


def read_db(path, table, cols):
    if not path.is_file():
        raise FileNotFoundError(f'Missing existing shadow sidecar: {path}')
    connection = sqlite3.connect('file:'+quote(str(path), safe='/')+'?mode=ro', uri=True, timeout=15)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA query_only=ON')
        existing = {r['name'] for r in connection.execute(f'PRAGMA table_info({table})')}
        if not set(cols).issubset(existing):
            raise RuntimeError(f'Unexpected schema in {path.name} {table}: missing {set(cols)-existing}')
        return [dict(r) for r in connection.execute('SELECT '+','.join(cols)+f' FROM {table} ORDER BY id')]
    finally:
        connection.close()


def relationship_context(ctx, now, stationary_verified=False):
    """Nearness alone is NOT evidence. Require a repeated return chain + links."""
    pairs = ctx.get('nearby_not_merged') or []
    transitions = ctx.get('transitions') or []
    chains = ctx.get('trip_chains') or []
    related = []
    for pair in pairs:
        a, b = pair.get('site_a'), pair.get('site_b')
        km = val(pair.get('distance_km'))
        if not a or not b or a == b or km is None or not 0 < km <= NEARBY_MAX_KM:
            continue
        for chain in chains:
            parts = [x.strip() for x in str(chain.get('sequence') or '').split('->')]
            chain_days = int(chain.get('support_days') or 0)
            if len(parts) != 3 or parts[0] not in (a,b) or parts[2] not in (a,b) or parts[0] == parts[2]:
                continue
            if chain_days < MIN_CHAIN_DAYS:
                continue
            middle = parts[1]
            forward = max((int(t.get('support_days') or 0) for t in transitions
                           if t.get('from_site') == parts[0] and t.get('to_site') == middle), default=0)
            back = max((int(t.get('support_days') or 0) for t in transitions
                        if t.get('from_site') == middle and t.get('to_site') == parts[2]), default=0)
            if min(forward, back) < MIN_LINK_DAYS:
                continue
            related.append({'site_a': a, 'site_b': b, 'distance_km': km,
                            'through_site': middle, 'chain_days': chain_days,
                            'outbound_days': forward, 'return_days': back,
                            'type': 'RELATED_IN_REPEATED_TRAVEL_PATTERN_NOT_SAME_PLACE'})
            break
    current = ctx.get('current_site') or {}
    site = current.get('site')
    age = val(current.get('observation_age_minutes'))
    stamp = val(ctx.get('generated_at'))
    # Data may be read just before scheduled refresh; don't call an old GPS fix current.
    effective_age = None if age is None or stamp is None else max(0, age+(now-stamp)/60)
    fresh = bool(site and effective_age is not None and 0 <= effective_age <= MAX_FRESH_GPS_MIN)
    suggestions = []
    if fresh and stationary_verified:
        for rel in related:
            other = rel['site_b'] if site == rel['site_a'] else rel['site_a'] if site == rel['site_b'] else None
            if other is None:
                continue
            for tr in transitions:
                if tr.get('from_site') != other or int(tr.get('support_days') or 0) < MIN_LINK_DAYS:
                    continue
                text = str(tr.get('typical_departure') or '')
                try:
                    hour,minute=(int(x) for x in text.split(':'))
                    if not (0<=hour<24 and 0<=minute<60):continue
                except (TypeError,ValueError):
                    continue
                group = tr.get('group')
                next_ts = None
                for day_delta in range(3):
                    day = (local(now)+timedelta(days=day_delta)).date()
                    if group not in ('weekday','weekend') or (day.weekday()<5)!=(group=='weekday'):
                        continue
                    tick = datetime(day.year,day.month,day.day,hour,minute,tzinfo=TZ).timestamp()
                    if now+5*60 < tick <= now+36*3600:
                        next_ts = tick
                        break
                if next_ts is None:continue
                suggestions.append({'current_site':site, 'observed_other_site':other,
                                    'historical_destination':tr.get('to_site'),
                                    'time_ts':next_ts, 'historical_support_days':int(tr.get('support_days') or 0),
                                    'basis':'RELATED_SITE_CONTEXT_HYPOTHESIS_ONLY',
                                    'origin_is_not_verified':True})
    suggestions.sort(key=lambda x:(x['time_ts'],-x['historical_support_days']))
    return {'current_site':site, 'last_verified_gps_age_min':round(effective_age,1) if effective_age is not None else None,
            'current_gps_fresh':fresh, 'stationary_verified':bool(stationary_verified), 'related_pairs':related,
            'contextual_hypotheses':suggestions[:5],
            'direct_observed_route':ctx.get('direct_shadow_prediction') if fresh and stationary_verified else None,
            'source_context_age_min':round(max(0,(now-stamp)/60),1) if stamp is not None else None}


def valid_v3(r, now):
    if r.get('status') != 'SCORED':return None
    capture,pred,start,end = [val(r.get(k)) for k in ('captured_at','predicted_ts','actual_start_ts','actual_end_ts')]
    error=val(r.get('error_min'))
    if None in (capture,pred,start,end,error):return None
    if not (capture<pred and capture<start<end<=now and (pred-capture)/60>=30 and abs((start-pred)/60-error)<1.5):return None
    return {'source':'GPS_ROUTE_v3.2','id':r['id'],'capture':capture,'predicted':pred,'start':start,'end':end,
            'error':error,'destination_hit':r.get('destination_match') if r.get('destination_match') in (0,1) else None,
            'soc_error_pp':val(r.get('soc_error'))}


def valid_v5(r,now):
    if r.get('status')!='SCORED_TIME_ONLY':return None
    capture,pred,start,end=[val(r.get(k)) for k in ('captured_at','predicted_ts','actual_start_ts','actual_end_ts')]
    error=val(r.get('departure_error_min'))
    if None in (capture,pred,start,end,error):return None
    if not (capture<pred and capture<start<end<=now and (pred-capture)/60>=45 and abs((start-pred)/60-error)<1.5):return None
    return {'source':'TIME_ONLY_v5','id':r['id'],'capture':capture,'predicted':pred,'start':start,'end':end,
            'error':error,'destination_hit':None,'soc_error_pp':None}


def unified_accuracy(v3, v5, now):
    route = [x for r in v3 if (x:=valid_v3(r,now))]
    timeonly = [x for r in v5 if (x:=valid_v5(r,now))]
    # Every scored outcome represents a real trip; when both systems scored the
    # same departure, count it ONCE. Prefer GPS-verified route to time-only.
    kept = list(route)
    duplicate = 0
    for t in timeonly:
        if any(abs(t['start']-x['start'])<=DEDUP_START_SECONDS for x in kept):
            duplicate+=1
        else:
            kept.append(t)
    # Strictly do not count duplicated v3 rows, should a future migration produce any.
    unique=[]
    for x in sorted(kept,key=lambda i:(i['start'],i['source']!='GPS_ROUTE_v3.2')):
        if any(abs(x['start']-y['start'])<=DEDUP_START_SECONDS for y in unique):
            duplicate+=1
        else:unique.append(x)
    error=[abs(x['error']) for x in unique]
    hits=[x['destination_hit'] for x in unique if x['destination_hit'] is not None]
    soc=[abs(x['soc_error_pp']) for x in unique if x['soc_error_pp'] is not None]
    counts={'morning':0,'afternoon':0,'other':0}
    for x in unique:
        hr=local(x['start']).hour
        key='morning' if 3<=hr<11 else 'afternoon' if 11<=hr<19 else 'other'
        counts[key]+=1
    return {'unique_verified_departures':len(unique),'route_scored':len(route),
            'time_only_scored':len(timeonly),'overlaps_removed':duplicate,
            'departure_mae_min':round(statistics.mean(error),2) if error else None,
            'within_15_min':sum(e<=15 for e in error),'within_30_min':sum(e<=30 for e in error),
            'departure_periods':counts, 'destinations_verified':len(hits),
            'destination_hits':sum(hits),'energy_samples':len(soc),
            'energy_mae_pp':round(statistics.mean(soc),2) if soc else None,
            'recent_scored':[{'actual_local':display(x['start']),'forecast_local':display(x['predicted']),
                              'source':x['source'],'error_min':round(x['error'],1)} for x in sorted(unique,key=lambda x:-x['start'])[:10]]}


def safe_report(data):
    c,m=data['context'],data['accuracy']
    lines=[f'GHOST LOCATION RELATIONSHIP + COVERAGE {VERSION}',f'Updated: {display(data["generated_at"])}',
           'SHADOW ONLY. No production departure changes, no auto-training, no Tesla actions.',
           '', '=== LOCATION RELATIONSHIP EVIDENCE ===']
    if c['related_pairs']:
        for p in c['related_pairs']:
            lines.append(f'  {p["site_a"]} <-> {p["site_b"]}: {p["distance_km"]:.2f} km apart; DIFFERENT sites; '+
                         f'repeated return chain via {p["through_site"]} on {p["chain_days"]} days '+
                         f'(legs {p["outbound_days"]}/{p["return_days"]} days)')
    else:lines.append('  No supported related-site pairs. Proximity alone is insufficient.')
    lines.extend(['', '=== CURRENT LOCATION EVIDENCE ===',
                  f'  Last-known site: {c["current_site"] or "UNKNOWN"}',
                  f'  Verified GPS fix age: {c["last_verified_gps_age_min"]} min' if c['last_verified_gps_age_min'] is not None else '  Verified GPS fix: unavailable',
                  f'  Recent GPS location: {"YES" if c["current_gps_fresh"] else "NO — last-known only, NOT confirmed current"}',
                  f'  Parked state independently verified: {"YES" if c["stationary_verified"] else "NO — route context suppressed"}',
                  '', '=== LOCATION-AWARE SHADOW POSSIBILITIES ==='])
    if c['direct_observed_route']:
        p=c['direct_observed_route']
        lines.append(f'  DIRECT observed: {p.get("origin_site")} -> {p.get("destination_site")} at {p.get("departure_local")}')
    for h in c['contextual_hypotheses']:
        lines.append(f'  RELATED-SITE HYPOTHESIS: if starting from {h["observed_other_site"]}, '+
                     f'observed drive to {h["historical_destination"]} around {display(h["time_ts"])}; '+
                     f'but current GPS site is {h["current_site"]}; NO route claim from current site')
    if not c['direct_observed_route'] and not c['contextual_hypotheses']:
        lines.append('  None supported for current evidence. Time-only prediction may still be available.')
    lines.extend(['', '=== UNIFIED VERIFIED DEPARTURE ACCURACY ===',
                  f'  Unique scored trips: {m["unique_verified_departures"]} (route {m["route_scored"]}, time-only {m["time_only_scored"]})',
                  f'  Duplicated trip outcomes removed: {m["overlaps_removed"]}',
                  f'  Morning / afternoon / other: {m["departure_periods"]["morning"]} / {m["departure_periods"]["afternoon"]} / {m["departure_periods"]["other"]}',
                  f'  Departure MAE: {m["departure_mae_min"]} min' if m['departure_mae_min'] is not None else '  Departure MAE: WAITING',
                  f'  Within +/-15 min: {m["within_15_min"]}/{m["unique_verified_departures"]}',
                  f'  Destinations: {m["destination_hits"]}/{m["destinations_verified"]} verified hits; TIME_ONLY does not vote',
                  f'  Battery SOC MAE: {m["energy_mae_pp"]} pp ({m["energy_samples"]} verified route trips)' if m['energy_samples'] else '  Battery SOC MAE: WAITING (no time-only energy claims)',
                  '', '=== NEXT FROZEN TIME-ONLY FORECAST ==='])
    pending=data.get('pending_timeonly') or []
    for p in pending[:4]:lines.append(f'  {display(p["predicted_ts"])} | {p["pattern_group"]} | PENDING | no site/destination asserted')
    if not pending:lines.append('  None pending')
    lines+=['', 'RULES: Nearby is NOT the same place. Route hypotheses never auto-promote.',
            'GPS must be recent for contextual site suggestions; stale fixes are last-known only.',
            'Only frozen, subsequently scored trips count; same physical departure counted once.',
            'v3.2 route and v5 time-only sidecars are READ ONLY. v4 feedback remains unchanged.',
            'No GPS coordinates, VINs, addresses or raw vehicle records in this report.']
    return '\n'.join(lines)+'\n'


def verified_parked(live_path, now):
    """Fresh stationary samples are required; old GPS alone is not enough."""
    if not Path(live_path).is_file():return False
    con=sqlite3.connect('file:'+quote(str(live_path),safe='/')+'?mode=ro',uri=True,timeout=10)
    con.row_factory=sqlite3.Row
    try:
        con.execute('PRAGMA query_only=ON')
        rows=con.execute("""SELECT ts,shift_state,speed_kmh FROM telemetry
            WHERE car_id=(SELECT car_id FROM telemetry ORDER BY ts DESC LIMIT 1)
              AND ts>=? AND ts<=? ORDER BY ts DESC LIMIT 20""",(now-360,now+5)).fetchall()
        if len(rows)<3 or now-float(rows[0]['ts'])>180:return False
        # Last three snapshots need to show sustained Park for at least 2 min.
        recent=list(rows[:min(5,len(rows))])
        p=[x for x in recent if str(x['shift_state'] or '').upper() in ('P','PARK','PARKED')
           and val(x['speed_kmh']) is not None and abs(val(x['speed_kmh']))<=2]
        return len(p)>=3 and all(x in p for x in recent[:3]) and float(recent[0]['ts'])-float(recent[2]['ts'])>=100
    finally:
        con.close()


def execute(root, now=None, live_path=Path('/var/lib/ghost-tesla-ai/ghost_ai.sqlite3')):
    now=time.time() if now is None else float(now)
    ctx=read_json(root/'latest-location-context.json')
    route=read_db(root/'prediction-eval-v3.sqlite3','forecasts',
                  ['id','captured_at','predicted_ts','status','actual_start_ts','actual_end_ts','error_min','destination_match','soc_error'])
    times=read_db(root/'coverage-v5.sqlite3','time_forecasts',
                  ['id','captured_at','predicted_ts','pattern_group','status','actual_start_ts','actual_end_ts','departure_error_min'])
    output={'version':VERSION,'generated_at':now,
            'shadow_mode':True,'production_unchanged':True,
            'context':relationship_context(ctx,now,stationary_verified=verified_parked(live_path,now)),
            'accuracy':unified_accuracy(route,times,now),
            'pending_timeonly':[{'predicted_ts':r['predicted_ts'],'pattern_group':r['pattern_group']}
                                for r in times if r['status']=='PENDING' and val(r['predicted_ts']) is not None and r['predicted_ts']>=now-4*3600][:4]}
    # No raw GPS in either report; context JSON source remains on the Pi.
    atomic(root/'latest-trip-relationship-v6.json',json.dumps(output,indent=2,sort_keys=True)+'\n')
    atomic(root/'latest-trip-relationship-v6.txt',safe_report(output))
    return output


def self_test():
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        r=Path(td)
        t=datetime(2026,10,8,17,45,tzinfo=TZ).timestamp()
        ctx={'generated_at':t-60,'current_site':{'site':'SITE_002','observation_age_minutes':2},
             'nearby_not_merged':[{'site_a':'SITE_002','site_b':'SITE_003','distance_km':1.92}],
             'transitions':[{'from_site':'SITE_003','to_site':'SITE_001','support_days':8,'group':'weekday','typical_departure':'06:16'},
                            {'from_site':'SITE_001','to_site':'SITE_002','support_days':8,'group':'weekday','typical_departure':'14:41'}],
             'trip_chains':[{'sequence':'SITE_003 -> SITE_001 -> SITE_002','support_days':7}],
             'direct_shadow_prediction':None}
        rctx=relationship_context(ctx,t,stationary_verified=True)
        assert len(rctx['related_pairs'])==1 and rctx['related_pairs'][0]['chain_days']==7
        assert len(rctx['contextual_hypotheses'])==1
        assert rctx['contextual_hypotheses'][0]['origin_is_not_verified']
        assert local(rctx['contextual_hypotheses'][0]['time_ts']).day==9
        # Proximity by itself or stale GPS must never be called an observed route.
        assert not relationship_context({**ctx,'trip_chains':[]},t,stationary_verified=True)['related_pairs']
        assert not relationship_context({**ctx,'current_site':{'site':'SITE_002','observation_age_minutes':80}},t,stationary_verified=True)['contextual_hypotheses']
        pred=datetime(2026,10,8,14,41,tzinfo=TZ).timestamp()
        actual=pred+4.9*60
        v3=[{'id':1,'status':'SCORED','captured_at':pred-73*60,'predicted_ts':pred,
             'actual_start_ts':actual,'actual_end_ts':actual+82*60,'error_min':4.9,'destination_match':1,'soc_error':-1},
            {'id':2,'status':'INVALID_CAPTURE_IN_MOTION','captured_at':pred+3600,'predicted_ts':pred+86400}]
        v5=[{'id':1,'status':'SCORED_TIME_ONLY','captured_at':pred-75*60,'predicted_ts':pred,
             'actual_start_ts':actual,'actual_end_ts':actual+82*60,'departure_error_min':4.9},
            {'id':2,'status':'SCORED_TIME_ONLY','captured_at':pred+7*3600,'predicted_ts':pred+16*3600,
             'actual_start_ts':pred+16*3600+600,'actual_end_ts':pred+16*3600+4200,'departure_error_min':10}]
        metrics=unified_accuracy(v3,v5,pred+30*3600)
        assert metrics['unique_verified_departures']==2 and metrics['overlaps_removed']==1
        assert metrics['departure_periods']=={'morning':1,'afternoon':1,'other':0}
        assert metrics['destinations_verified']==1 and metrics['energy_samples']==1 and metrics['energy_mae_pp']==1
        json_ctx={**ctx,'private_lat':41.6,'private_lon':-87.3}
        a=relationship_context(json_ctx,t,stationary_verified=True)
        txt=safe_report({'generated_at':t,'context':a,'accuracy':metrics,'pending_timeonly':[]})
        assert '41.6' not in txt and '-87.3' not in txt and 'RELATED-SITE HYPOTHESIS' in txt
        # Integration test with SQLite sidecars, no modification to input sidecars.
        def make_db(path,ddl,sql,values):
            c=sqlite3.connect(path);c.execute(ddl);c.execute(sql,values);c.commit();c.close()
        make_db(r/'prediction-eval-v3.sqlite3',
                'CREATE TABLE forecasts(id INTEGER,captured_at REAL,predicted_ts REAL,status TEXT,actual_start_ts REAL,actual_end_ts REAL,error_min REAL,destination_match INTEGER,soc_error REAL)',
                'INSERT INTO forecasts VALUES (?,?,?,?,?,?,?,?,?)',
                (1,pred-73*60,pred,'SCORED',actual,actual+82*60,4.9,1,-1.0))
        make_db(r/'coverage-v5.sqlite3',
                'CREATE TABLE time_forecasts(id INTEGER,captured_at REAL,predicted_ts REAL,pattern_group TEXT,status TEXT,actual_start_ts REAL,actual_end_ts REAL,departure_error_min REAL)',
                'INSERT INTO time_forecasts VALUES (?,?,?,?,?,?,?,?)',
                (1,pred-75*60,pred,'weekday','SCORED_TIME_ONLY',actual,actual+82*60,4.9))
        (r/'latest-location-context.json').write_text(json.dumps(ctx))
        # A parked state is not assumed. Test with a telemetry fixture.
        parked_db=r/'live.sqlite3'
        c=sqlite3.connect(parked_db)
        c.execute('CREATE TABLE telemetry(car_id TEXT,ts REAL,shift_state TEXT,speed_kmh REAL)')
        at=pred+4*3600
        for offset in (0,70,140,210):
            c.execute('INSERT INTO telemetry VALUES (?,?,?,?)',('test',at-offset,'P',0))
        c.commit();c.close()
        assert verified_parked(parked_db,at)
        assert not verified_parked(parked_db,at+600)
        first=execute(r,at,parked_db)
        assert first['accuracy']['unique_verified_departures']==1 and first['accuracy']['overlaps_removed']==1
        assert 'GPS must be recent' in (r/'latest-trip-relationship-v6.txt').read_text()
        assert 'centroid_lat' not in (r/'latest-trip-relationship-v6.json').read_text()
        assert read_db(r/'prediction-eval-v3.sqlite3','forecasts',['id'])[0]['id']==1
    print('SELF-TEST PASS: repeated-chain relationships, stale GPS safeguards, no invented routes, GPS/time-only deduplication, privacy, read-only inputs')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--self-test',action='store_true')
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--db',type=Path,default=Path('/var/lib/ghost-tesla-ai/ghost_ai.sqlite3'))
    args=p.parse_args()
    if args.self_test:self_test()
    else:
        result=execute(args.root,live_path=args.db)
        print(safe_report(result))

if __name__=='__main__':main()

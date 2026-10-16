#!/usr/bin/env python3
"""GHOST verified-trip feedback v4: prospective, read-only shadow calibration.

Reads only prospective v3.2 forecast outcomes from an existing sidecar.
Writes only its own text/JSON diagnostics. No production changes or retraining.
"""
from __future__ import annotations
import argparse
import datetime as dt
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

VERSION = 'trip-feedback-shadow-v4.0.0'
TZ = ZoneInfo('America/Chicago')
from . import config
ROOT = Path(config.get('GHOST_TRIP_SHADOW_DIR', str(config.DATA_DIR / 'trip-sequence')))
MIN_ROUTE_TRIPS = 10
MIN_ROUTE_DAYS = 5
MIN_BACKTEST_POINTS = 5
MIN_BACKTEST_IMPROVEMENT = 0.15
WINDOW_DAYS = 60


def is_num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError, OverflowError):
        return None


def day(ts):
    return dt.datetime.fromtimestamp(float(ts), TZ).date().isoformat()


def fmt_time(ts):
    return dt.datetime.fromtimestamp(float(ts), TZ).strftime('%Y-%m-%d %I:%M %p')


def median(seq):
    return statistics.median(seq) if seq else None


def mae(seq):
    return statistics.mean(abs(x) for x in seq) if seq else None


def safe_write(path, value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd, temp = tempfile.mkstemp(prefix='.ghost-v4-',dir=path.parent)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as out:
            out.write(value)
            out.flush(); os.fsync(out.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def read_forecasts(dbpath):
    if not dbpath.is_file():
        raise RuntimeError('Missing v3.2 forecast database; nothing was modified')
    con = sqlite3.connect('file:'+quote(str(dbpath))+'?mode=ro',uri=True,timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA query_only=ON')
    try:
        cols={r['name'] for r in con.execute('PRAGMA table_info(forecasts)')}
        fields=['id','captured_at','predicted_ts','status','origin_site','destination_site',
                'actual_start_ts','actual_end_ts','error_min','lead_min','destination_match',
                'actual_soc_drop','predicted_soc_drop','soc_error','evaluation_note']
        if not set(fields).issubset(cols):
            raise RuntimeError('Unknown forecast schema; refusing to infer data')
        return [dict(r) for r in con.execute('SELECT '+','.join(fields)+' FROM forecasts ORDER BY captured_at,id')]
    finally:
        con.close()


def good_row(r, now):
    if r.get('status')!='SCORED': return False
    cap=is_num(r.get('captured_at')); pred=is_num(r.get('predicted_ts'))
    start=is_num(r.get('actual_start_ts')); end=is_num(r.get('actual_end_ts'))
    lead=is_num(r.get('lead_min')); err=is_num(r.get('error_min'))
    if None in (cap,pred,start,end,lead,err): return False
    if not (cap < start < end <= now and pred>cap and lead>=30): return False
    if abs(err)>240 or abs((start-pred)/60-err)>1.5: return False
    if (r.get('destination_match') not in (None,0,1)) or not r.get('origin_site') or not r.get('destination_site'): return False
    if r['origin_site']==r['destination_site']:return False
    return True


def energy_error(r):
    actual=is_num(r.get('actual_soc_drop'))
    predicted=is_num(r.get('predicted_soc_drop'))
    err=is_num(r.get('soc_error'))
    if None in (actual,predicted,err): return None
    if not (0 < actual <=45 and 0<predicted<=45 and abs(err)<=45): return None
    if abs(actual-predicted-err)>0.11: return None
    return err


def clip(v, bound):
    return min(bound,max(-bound,v))


def metric_view(rows):
    errs=[r['_departure_error'] for r in rows]
    energy=[r['_energy_error'] for r in rows if r['_energy_error'] is not None]
    hits=[r['destination_match'] for r in rows if r['destination_match'] is not None]
    return {'trips':len(rows),'days':len({day(r['actual_start_ts']) for r in rows}),
            'departure_mae_min':round(mae(errs),2) if errs else None,
            'departure_median_bias_min':round(median(errs),2) if errs else None,
            'within_15_min':sum(abs(x)<=15 for x in errs),
            'destination_verified':len(hits),'destination_hits':sum(hits),
            'energy_samples':len(energy),
            'energy_mae_pp':round(mae(energy),2) if energy else None,
            'energy_median_bias_pp':round(median(energy),2) if energy else None}


def backtest(rows):
    """Walk forward using ONLY outcomes completed before each forecast was captured."""
    baseline=[];corrected=[];soc_baseline=[];soc_corrected=[]
    for r in rows:
        known=[p for p in rows if is_num(p['actual_end_ts']) < r['captured_at'] and
               p['id']!=r['id']]
        if len(known)<5 or len({day(p['actual_start_ts']) for p in known})<3:
            continue
        adjustment=clip(median([p['_departure_error'] for p in known]),20)
        baseline.append(abs(r['_departure_error']))
        corrected.append(abs(r['_departure_error']-adjustment))
        if r['_energy_error'] is not None:
            known_soc=[p['_energy_error'] for p in known if p['_energy_error'] is not None]
            if len(known_soc)>=5:
                soc_delta=clip(median(known_soc),4)
                soc_baseline.append(abs(r['_energy_error']))
                soc_corrected.append(abs(r['_energy_error']-soc_delta))
    a=statistics.mean(baseline) if baseline else None
    b=statistics.mean(corrected) if corrected else None
    relative=(a-b)/a if a is not None and a>0 else None
    return {'testable_forecasts':len(baseline),
            'baseline_departure_mae_min':round(a,2) if a is not None else None,
            'shadow_departure_mae_min':round(b,2) if b is not None else None,
            'relative_departure_improvement':round(relative,4) if relative is not None else None,
            'energy_testable_forecasts':len(soc_baseline),
            'baseline_energy_mae_pp':round(statistics.mean(soc_baseline),2) if soc_baseline else None,
            'shadow_energy_mae_pp':round(statistics.mean(soc_corrected),2) if soc_corrected else None}


def evaluate(allrows,now):
    cutoff=now-WINDOW_DAYS*86400
    accepted=[]
    for r in allrows:
        if not good_row(r,now) or float(r['actual_start_ts'])<cutoff: continue
        rr=dict(r);rr['_departure_error']=float(r['error_min']);rr['_energy_error']=energy_error(r)
        accepted.append(rr)
    groups={}
    for r in accepted:
        key=(str(r['origin_site']),str(r['destination_site']))
        groups.setdefault(key,[]).append(r)
    routes=[]
    for (origin,destination),items in sorted(groups.items(),key=lambda p:(-len(p[1]),p[0])):
        metrics=metric_view(items)
        walk=backtest(items)
        enough=(metrics['trips']>=MIN_ROUTE_TRIPS and metrics['days']>=MIN_ROUTE_DAYS)
        improved=(walk['testable_forecasts']>=MIN_BACKTEST_POINTS and
                  walk['relative_departure_improvement'] is not None and
                  walk['relative_departure_improvement']>=MIN_BACKTEST_IMPROVEMENT)
        status='READY_FOR_HUMAN_REVIEW' if enough and improved else 'COLLECTING'
        dep_correction=round(clip(median([r['_departure_error'] for r in items]),20),1) if enough else None
        e=[r['_energy_error'] for r in items if r['_energy_error'] is not None]
        energy_correction=round(clip(median(e),4),2) if enough and len(e)>=MIN_ROUTE_TRIPS else None
        routes.append({'origin_site':origin,'destination_site':destination,
                       'status':status,'metrics':metrics,'walk_forward':walk,
                       'candidate_departure_adjustment_min':dep_correction,
                       'candidate_energy_adjustment_pp':energy_correction})
    return {'version':VERSION,'generated_at':now,'window_days':WINDOW_DAYS,
            'records_in_sidecar':len(allrows),'valid_scored_forecasts_in_window':len(accepted),
            'overall':metric_view(accepted),'routes':routes,'mode':'SHADOW_ONLY',
            'auto_promotion':False,'production_changes':False}


def render(out):
    v=out['overall']
    lines=[f'GHOST VERIFIED TRIP FEEDBACK {VERSION}',
           f'Updated: {fmt_time(out["generated_at"])}',
           'SHADOW ONLY — reads v3.2 outcomes; does NOT change production predictions, models, or the vehicle.',
           '', '=== EVIDENCE ===',
           f'Forecast records checked: {out["records_in_sidecar"]}',
           f'Verified scored trips in last {WINDOW_DAYS} days: {v["trips"]}',
           f'Departure timing MAE: {v["departure_mae_min"] if v["trips"] else "WAITING"} min',
           f'Within 15 min: {v["within_15_min"]}/{v["trips"]}',
           f'GPS-verified destinations: {v["destination_hits"]}/{v["destination_verified"]}',
           f'Battery SOC MAE: {v["energy_mae_pp"] if v["energy_samples"] else "WAITING"} pp ({v["energy_samples"]} valid trips)',
           '', '=== ROUTE FEEDBACK (never applied automatically) ===']
    if not out['routes']:
        lines.append('No verified route outcomes yet.')
    for r in out['routes']:
        m=r['metrics'];w=r['walk_forward']
        lines.append(f'{r["origin_site"]} -> {r["destination_site"]}: {m["trips"]} trips on {m["days"]} days | {r["status"]}')
        lines.append(f'  timing bias {m["departure_median_bias_min"]:+.1f} min, MAE {m["departure_mae_min"]:.1f} min')
        lines.append(f'  timing candidate (min): {r["candidate_departure_adjustment_min"] if r["candidate_departure_adjustment_min"] is not None else "NOT READY"}; minimum {MIN_ROUTE_TRIPS} trips on {MIN_ROUTE_DAYS} days')
        lines.append(f'  SOC candidate (pp): {r["candidate_energy_adjustment_pp"] if r["candidate_energy_adjustment_pp"] is not None else "NOT READY"}')
        if w['testable_forecasts']:
            lines.append(f'  walk-forward: {w["testable_forecasts"]} future forecasts | baseline MAE {w["baseline_departure_mae_min"]}m vs shadow {w["shadow_departure_mae_min"]}m')
        else:
            lines.append('  walk-forward: waiting for enough earlier outcomes')
    lines += ['', 'RULES: Only historically frozen and subsequently SCORED trips qualify.',
              'Corrections use medians, are capped, and are tested without future-data leakage.',
              'No GPS coordinates, addresses, VIN, credentials, or raw telemetry appear in this report.',
              'Even READY_FOR_HUMAN_REVIEW does not auto-promote or change live predictions.']
    return '\n'.join(lines)+'\n'


def run(root, now):
    allrows=read_forecasts(root/'prediction-eval-v3.sqlite3')
    out=evaluate(allrows,now)
    safe_write(root/'latest-feedback-v4.txt',render(out))
    safe_write(root/'latest-feedback-v4.json',json.dumps(out,indent=2)+'\n')
    print(render(out))


def self_test():
    now=1782300000.0
    def sample(i,cap=None,error=8.0,energy=-2.0,route=('SITE_001','SITE_002'),status='SCORED'):
        p=now-(30-i)*86400
        captured=p-90*60 if cap is None else cap
        start=p+error*60
        return {'id':i,'captured_at':captured,'predicted_ts':p,'status':status,
                'origin_site':route[0],'destination_site':route[1],
                'actual_start_ts':start,'actual_end_ts':start+3600,'error_min':error,
                'lead_min':90,'destination_match':1,'actual_soc_drop':11.0,
                'predicted_soc_drop':13.0,'soc_error':energy,'evaluation_note':''}
    one=sample(1)
    invalid=sample(2,status='INVALID_CAPTURE_IN_MOTION')
    result=evaluate([one,invalid],now)
    assert result['valid_scored_forecasts_in_window']==1
    assert result['routes'][0]['candidate_departure_adjustment_min'] is None
    assert result['routes'][0]['status']=='COLLECTING'
    seq=[sample(i) for i in range(1,18)]
    out=evaluate(seq,now)
    route=out['routes'][0]
    assert route['candidate_departure_adjustment_min']==8.0
    assert route['candidate_energy_adjustment_pp']==-2.0
    assert route['status']=='READY_FOR_HUMAN_REVIEW'
    assert route['walk_forward']['testable_forecasts']>=5
    assert route['walk_forward']['shadow_departure_mae_min']==0.0
    # A row with a contradictory SOC error must never be used for SOC calibration.
    bad=dict(sample(20));bad['soc_error']=42
    assert energy_error(bad) is None
    # A completed trip that wasn't frozen beforehand must be rejected.
    bad2=dict(sample(21));bad2['captured_at']=bad2['actual_start_ts']+60
    assert not good_row(bad2,now)
    assert 'SHADOW ONLY' in render(result)
    print('SELF-TEST PASS: no retraining with one trip; strict outcome filtering; walk-forward evaluation; energy safeguards')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    if args.self_test: self_test()
    else: run(args.root,time.time())

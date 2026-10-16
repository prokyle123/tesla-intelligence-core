#!/usr/bin/env python3
"""GHOST Forecast Quality v1: read-only, transition-aware evaluation of existing predictions.

Does not alter the vehicle, database, event engine, training, champions or forecasts.
"""
import argparse
import bisect
import collections
import datetime as dt
import json
import math
import os
import sqlite3
import statistics
import sys
import time
from pathlib import Path

DEFAULT_DB = '/var/lib/ghost-tesla-ai/ghost_ai.sqlite3'
MODELS = ('park_soc_180m', 'soc_180m', 'soc_60m', 'charge_soc_60m')
SAMPLE_CAP = 65000


def nfloat(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def charging(row):
    state = str(row.get('charging_state') or '').lower()
    p = [nfloat(row.get(k)) for k in ('charge_input_kw', 'charger_power_kw')]
    return state == 'charging' or any(v is not None and v > 0.25 for v in p)


def driving(row):
    state = str(row.get('state') or '').lower()
    shift = str(row.get('shift_state') or '').upper()
    speed = nfloat(row.get('speed_kmh')) or 0.0
    return state == 'driving' or shift in ('D', 'R', 'N') or speed > 3.0


def conditioning(row):
    return bool(row.get('preconditioning')) or (bool(row.get('climate_on')) and bool(row.get('battery_heater_on')))


def tstr(ts):
    return dt.datetime.fromtimestamp(float(ts)).strftime('%Y-%m-%d %I:%M %p %Z')


def summarize(values):
    values = [v for v in values if v is not None and math.isfinite(v)]
    if not values:
        return {'count': 0, 'mae_pp': None, 'bias_pp': None, 'median_ae_pp': None, 'p90_ae_pp': None}
    ae = sorted(abs(v) for v in values)
    index = min(len(ae) - 1, max(0, math.ceil(0.9 * len(ae)) - 1))
    return {
        'count': len(values),
        'mae_pp': round(statistics.fmean(ae), 3),
        'bias_pp': round(statistics.fmean(values), 3),
        'median_ae_pp': round(statistics.median(ae), 3),
        'p90_ae_pp': round(ae[index], 3),
    }


def classify_window(forecast, rows, time_axis):
    """Retrospectively classify observation window; clean outcomes demand good coverage."""
    start = float(forecast['source_ts'])
    intended_end = float(forecast['target_ts'])
    actual_ts = float(forecast['actual_ts'])
    # Restrict evidence to intended horizon; actual reading may have loose resolve tolerance.
    lo = bisect.bisect_left(time_axis, start - 20.0)
    hi = bisect.bisect_right(time_axis, intended_end + 20.0)
    window = rows[lo:hi]
    if not window:
        return {'category': 'insufficient_coverage', 'reason': 'no telemetry', 'max_gap_min': None, 'sentry_mode': 'unknown'}

    drive_count = sum(driving(r) for r in window)
    charge_count = sum(charging(r) for r in window)
    precondition_count = sum(conditioning(r) for r in window)
    odo_vals = [nfloat(r.get('odometer_km')) for r in window]
    odo_vals = [v for v in odo_vals if v is not None]
    distance_km = max(0.0, max(odo_vals) - min(odo_vals)) if len(odo_vals) > 1 else 0.0
    moving = drive_count > 0 or distance_km > 0.35
    charging_seen = charge_count > 0
    precondition_seen = precondition_count > 0

    # Sentry setting is what Tesla reports in each sample, not proof of Watts used.
    bits = [r.get('sentry_mode') for r in window if r.get('sentry_mode') is not None]
    sentry = 'unknown'
    if bits:
        fraction = sum(bool(b) for b in bits) / len(bits)
        sentry = 'on' if fraction >= 0.80 else ('off' if fraction <= 0.20 else 'mixed')

    timeline = [start] + [float(r['ts']) for r in window if start < float(r['ts']) < intended_end] + [intended_end]
    max_gap_min = max((b - a for a, b in zip(timeline, timeline[1:])), default=intended_end-start) / 60.0
    # SQLite's truth resolver can match data an hour away on 3h forecasts.
    # This is not precise enough to claim valid parked or charging truth.
    gap = max_gap_min > 10.0 or abs(actual_ts-intended_end) > 300.0
    reason = ''
    share_drive = drive_count / len(window)
    share_charge = charge_count / len(window)
    if moving and charging_seen:
        category = 'drive_and_charge_observed'
    elif moving:
        category = 'predominantly_driving' if (share_drive >= 0.70 and not gap) else 'drive_observed'
    elif charging_seen:
        category = 'predominantly_charging' if (share_charge >= 0.70 and not gap) else 'charging_observed'
    elif precondition_seen:
        category = 'conditioning_observed'
    elif gap:
        category = 'insufficient_coverage'
    else:
        category = 'uninterrupted_stationary'
    if gap:
        reason = 'coverage gap or loose target match'
    return {'category': category, 'reason': reason, 'max_gap_min': round(max_gap_min, 2),
            'sentry_mode': sentry, 'distance_km_observed': round(distance_km, 2),
            'drive_samples': drive_count, 'charging_samples': charge_count,
            'conditioning_samples': precondition_count, 'coverage_sufficient': not gap}


def read_data(path, now, days):
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    # Python sqlite URI takes file: syntax; Path.as_uri works as file:///...
    con = sqlite3.connect(uri, uri=True, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA query_only=ON')
    con.execute('PRAGMA busy_timeout=20000')
    with con:
        since = now - days*86400
        fields = "ts,car_id,state,shift_state,speed_kmh,odometer_km,charging_state,charge_input_kw,charger_power_kw,preconditioning,climate_on,battery_heater_on,sentry_mode,battery_level"
        samples = con.execute('SELECT '+fields+' FROM telemetry WHERE ts>=? AND ts<=? ORDER BY car_id,ts', (since-4*3600, now)).fetchall()
        forecasts = con.execute('''
          SELECT a.id,a.model_name,a.predicted_at,a.target_ts,a.source_telemetry_id,
                 a.actual_telemetry_id,a.predicted_value,a.actual_value,a.signed_error,a.abs_error,
                 s.car_id,s.ts as source_ts,s.battery_level as starting_soc,
                 s.state as start_state,s.shift_state as start_shift,s.charging_state as start_charging,
                 s.sentry_mode as start_sentry,s.speed_kmh as start_speed,
                 x.ts as actual_ts
          FROM prediction_audit a
          JOIN telemetry s ON s.id=a.source_telemetry_id
          JOIN telemetry x ON x.id=a.actual_telemetry_id AND x.car_id=s.car_id
          WHERE a.status='resolved' AND a.model_name IN (?,?,?,?) AND a.predicted_at>=?
            AND a.predicted_at<=? AND a.actual_value IS NOT NULL
          ORDER BY a.predicted_at DESC LIMIT ?
        ''', (*MODELS, since, now, SAMPLE_CAP)).fetchall()
    con.close()
    bycar = collections.defaultdict(list)
    for r in samples:
        bycar[str(r['car_id'])].append(dict(r))
    tsbycar = {car: [float(r['ts']) for r in rr] for car, rr in bycar.items()}
    return [dict(r) for r in forecasts], bycar, tsbycar, len(samples)


def evaluate(forecasts, bycar, tsbycar, now, days):
    entries = []
    for f in forecasts:
        car = str(f['car_id'])
        if car not in bycar:
            continue
        label = classify_window(f, bycar[car], tsbycar[car])
        signed = nfloat(f['signed_error'])
        if signed is None:
            predicted = nfloat(f['predicted_value'])
            actual = nfloat(f['actual_value'])
            signed = predicted-actual if predicted is not None and actual is not None else None
        if signed is None:
            continue
        if f['model_name'] == 'park_soc_180m':
            f0 = {'state':f['start_state'], 'shift_state':f['start_shift'], 'charging_state':f['start_charging'], 'speed_kmh':f['start_speed']}
            # A non-park start is a contract violation, not an uninterrupted parked sample.
            if driving(f0) or charging(f0):
                label['category']='invalid_start_state'
        entries.append({'model': f['model_name'], 'predicted_at': float(f['predicted_at']),
                        'target_ts': float(f['target_ts']), 'source_ts':float(f['source_ts']),
                        'start_soc': nfloat(f['starting_soc']), 'actual_soc': nfloat(f['actual_value']),
                        'predicted_soc': nfloat(f['predicted_value']), 'signed_error':signed, **label})
    report = {'generated_at':tstr(now), 'lookback_days':days, 'forecasts_scored':len(entries),
              'note':'Historical forecast values are preserved; classifications apply only to evaluation.',
              'models':{}, 'parked_sentry_comparison':{}, 'examples':[]}
    for model in MODELS:
        relevant = [x for x in entries if x['model']==model]
        obj={}
        for duration, cutoff in [('24h',now-86400),('7d',now-7*86400)]:
            these = [x for x in relevant if x['predicted_at'] >= cutoff]
            if model == 'park_soc_180m':
                groups=['all_forecasts', 'uninterrupted_stationary','drive_observed','charging_observed',
                        'drive_and_charge_observed','predominantly_driving','predominantly_charging','conditioning_observed','insufficient_coverage','invalid_start_state']
            else:
                groups=['all_forecasts','uninterrupted_stationary','drive_observed','charging_observed',
                        'drive_and_charge_observed','predominantly_driving','predominantly_charging','conditioning_observed','insufficient_coverage']
            metrics={}
            for group in groups:
                subset=these if group == 'all_forecasts' else [x for x in these if x['category']==group]
                metrics[group]=summarize([x['signed_error'] for x in subset])
            obj[duration]=metrics
        report['models'][model]=obj

    clean = [x for x in entries if x['model']=='park_soc_180m' and x['category']=='uninterrupted_stationary']
    for name in ('on','off','mixed','unknown'):
        relevant = [x for x in clean if x['sentry_mode']==name]
        metrics=summarize([x['signed_error'] for x in relevant])
        drain=[(x['start_soc']-x['actual_soc']) for x in relevant if x['start_soc'] is not None and x['actual_soc'] is not None]
        metrics['mean_observed_3h_soc_drop_pp']=round(statistics.fmean(drain),3) if drain else None
        report['parked_sentry_comparison'][name]=metrics

    invalid=[x for x in entries if x['model']=='park_soc_180m' and x['category'] != 'uninterrupted_stationary']
    worst=sorted(invalid, key=lambda x: abs(x['signed_error']), reverse=True)[:5]
    report['examples']=[{k: ((tstr(x[k])) if k in ('predicted_at','target_ts') else x[k]) for k in
        ('predicted_at','target_ts','category','predicted_soc','actual_soc','signed_error','max_gap_min')} for x in worst]
    return report


def fmtmetric(m):
    if m['count'] == 0:
        return 'n=0'
    return ('n={count:5d}  MAE={mae_pp:6.2f} pp  bias={bias_pp:+6.2f} pp'
            '  p90={p90_ae_pp:5.2f} pp').format(**m)


def make_text(result, n_samples, n_forecasts):
    lines=[
      'GHOST FORECAST QUALITY v1 - TRANSITION-AWARE SHADOW SCORING',
      'Generated: '+result['generated_at'],
      'READ-ONLY SQLite / DOES NOT REPLACE ORIGINAL PREDICTION AUDIT',
      '',
      'Telemetry rows scanned: '+str(n_samples)+' | resolved forecasts scanned: '+str(n_forecasts),
      'Forecasts scored: '+str(result['forecasts_scored']),
      'MAE and bias in SOC percentage points. Bias = predicted minus actual.',
      'A parking prediction interrupted by driving or charging remains valid history but',
      'does not count toward uninterrupted PARKED performance.',
      'Coverage is insufficient if any >10-min gap or actual reading >5 min from target.',
      'Activity-observed groups can also contain data gaps; do not treat as full trip totals.',
      'Predominantly driving/charging means at least 70% activity samples with adequate coverage.',
      'Samples overlap in time; forecast counts are NOT independent trips.',
      '',
    ]
    for model in MODELS:
        lines.append('='*71)
        lines.append(model.upper())
        for duration in ('24h','7d'):
            lines.append(' '+duration+':')
            for category, metrics in result['models'][model][duration].items():
                if category=='invalid_start_state' or metrics['count'] or category in ('all_forecasts','uninterrupted_stationary'):
                    lines.append('  '+category.ljust(28)+' '+fmtmetric(metrics))
        lines.append('')
    lines += ['='*71, 'CLEAN 3-HOUR PARKED FORECASTS SPLIT BY SENTRY MODE (7 DAYS)']
    for key, val in result['parked_sentry_comparison'].items():
        drain=val.get('mean_observed_3h_soc_drop_pp')
        lines.append('  sentry '+key.ljust(7)+' '+fmtmetric(val)+'  observed 3h SOC drop='+('n/a' if drain is None else str(drain)+' pp'))
    lines += ['','EXAMPLES OF HIGH-ERROR INTERRUPTED PARKED FORECASTS']
    for x in result['examples']:
        lines.append('  '+str(x))
    lines += ['', 'FINAL: Original model_runs, prediction_audit, and telemetry were not modified.']
    return '\n'.join(lines)+'\n'


def atomic_write(path, body):
    tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(body,encoding='utf-8')
    os.replace(tmp,path)


def main():
    p=argparse.ArgumentParser(description='Read-only retrospective forecast scoring')
    p.add_argument('--db',default=DEFAULT_DB)
    p.add_argument('--output-dir',default='/home/ghost/ghost-forecast-quality')
    p.add_argument('--days',type=int,default=7)
    p.add_argument('--now',type=float,default=None,help='For tests only')
    a=p.parse_args()
    if a.days<1 or a.days>14:
        p.error('--days must be 1 to 14')
    now=a.now or time.time()
    if not Path(a.db).is_file():
        p.error('Database not found: '+a.db)
    forecasts,bycar,tsbycar,n_samples=read_data(a.db,now,a.days)
    result=evaluate(forecasts,bycar,tsbycar,now,a.days)
    content=make_text(result,n_samples,len(forecasts))
    outdir=Path(a.output_dir)
    outdir.mkdir(parents=True,exist_ok=True)
    atomic_write(outdir/'latest.txt',content)
    atomic_write(outdir/'latest.json',json.dumps(result,indent=2,allow_nan=False)+'\n')
    daily=outdir/'daily'
    daily.mkdir(exist_ok=True)
    date=dt.datetime.fromtimestamp(now).strftime('%Y-%m-%d')
    atomic_write(daily/(date+'.txt'), content)
    atomic_write(daily/(date+'.json'), json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(content)
    print('Saved:',outdir/'latest.txt')
    print('Saved:',outdir/'latest.json')


if __name__=='__main__':
    main()

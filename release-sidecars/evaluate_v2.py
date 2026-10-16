#!/usr/bin/env python3
"""GHOST Forecast Quality v2. Shadow-only, read-only SQLite, no production changes.

Builds context-aware and origin-episode-weighted scores from v1's observation
classifier. Episode units are observed contiguous telemetry states, NOT verified
full trips; data gaps split episodes. All existing model evaluations are retained.
"""
from __future__ import annotations
import argparse, bisect, collections, datetime as dt, importlib.util, json, math, os
from pathlib import Path
import statistics, time, sqlite3

VERSION='2.0.0'
BASE=Path('/home/ghost/ghost-forecast-quality')
MODELS=('park_soc_180m','soc_180m','soc_60m','charge_soc_60m')
GROUPS=('stationary','driving','charging','transition','conditioning','insufficient_coverage')
LABELS={
 'stationary':'Uninterrupted stationary','driving':'Predominantly driving',
 'charging':'Predominantly charging','transition':'Activity / transitions',
 'conditioning':'Preconditioning','insufficient_coverage':'Insufficient coverage'
}

def load_v1(path):
    spec=importlib.util.spec_from_file_location('ghost_forecast_quality_v1',str(path))
    if spec is None or spec.loader is None: raise RuntimeError('Cannot load Forecast Quality v1 from '+str(path))
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    for name in ('read_data','classify_window','nfloat','summarize','driving','charging','conditioning'):
        if not hasattr(mod,name):raise RuntimeError('Forecast Quality v1 is missing '+name)
    return mod

def resolve_kind(r,v1):
    if v1.driving(r): return 'driving'
    if v1.charging(r): return 'charging'
    if v1.conditioning(r): return 'conditioning'
    return 'stationary'

def build_episodes(bycar,v1):
    """Split observations at state transitions or >10m missing telemetry.
    Returns aligned per-row episode identifiers; no position or VIN emitted.
    """
    maps={};counts=collections.Counter(); dist=collections.defaultdict(list); total=0
    for car,rows in bycar.items():
        ids=[];lastkind=None;lastts=None;idnum=0;start=None;startodo=None;endodo=None
        def close():
            nonlocal start,startodo,endodo,lastts
            if start is None:return
            minutes=max(0.0,(lastts-start)/60.0)
            miles=max(0.0,(endodo-startodo)*0.621371) if startodo is not None and endodo is not None else 0.0
            if lastkind=='driving' and (minutes>=2 or miles>=0.5):
                counts['drive_episodes']+=1;dist['drive'].append(miles)
            if lastkind=='stationary' and minutes>=30:counts['park_episodes']+=1
            if lastkind=='charging' and minutes>=3:counts['charge_episodes']+=1
        for r in rows:
            ts=float(r['ts']);kind=resolve_kind(r,v1)
            if kind!=lastkind or (lastts is not None and ts-lastts>600):
                close();idnum+=1;start=ts;startodo=v1.nfloat(r.get('odometer_km'));endodo=startodo;lastkind=kind
            od=v1.nfloat(r.get('odometer_km'))
            if od is not None:endodo=od
            ids.append(idnum);lastts=ts
        close();maps[car]=ids;total+=idnum
    return maps, {'observed_drive_episodes':counts['drive_episodes'],
                  'observed_park_episodes_30min_plus':counts['park_episodes'],
                  'observed_charge_episodes':counts['charge_episodes'],
                  'observed_episode_segments_total':total,
                  'average_observed_drive_miles':round(statistics.fmean(dist['drive']),2) if dist['drive'] else None,
                  'note':'These are observed activity segments; telemetry gaps and stops may split real trips.'}

def context(label):
    if not label.get('coverage_sufficient'):
        return 'insufficient_coverage'
    cat=label['category']
    if cat=='uninterrupted_stationary': return 'stationary'
    if cat=='predominantly_driving':return 'driving'
    if cat=='predominantly_charging':return 'charging'
    if cat=='conditioning_observed':return 'conditioning'
    return 'transition'

def metric(ents):
    if not ents:return {'forecasts':0,'mae_pp':None,'bias_pp':None,'p90_pp':None,
                        'origin_episodes':0,'episode_weighted_mae_pp':None,'episode_weighted_bias_pp':None}
    signed=[e['error'] for e in ents]
    ae=sorted(abs(v) for v in signed)
    episodes=collections.defaultdict(list)
    for e in ents:episodes[(e['car_key'],e['episode'])].append(e['error'])
    # One observation unit per origin episode. Take median absolute error within
    # the episode, then average episode medians (never count minute forecasts as trips).
    episode_aes=[statistics.median(abs(v) for v in vv) for vv in episodes.values()]
    episode_bias=[statistics.median(vv) for vv in episodes.values()]
    return {
      'forecasts':len(signed),'mae_pp':round(statistics.fmean(ae),3),
      'bias_pp':round(statistics.fmean(signed),3),
      'p90_pp':round(ae[max(0,math.ceil(.9*len(ae))-1)],3),
      'origin_episodes':len(episodes),
      'episode_weighted_mae_pp':round(statistics.fmean(episode_aes),3),
      'episode_weighted_bias_pp':round(statistics.fmean(episode_bias),3),
    }

def recorded_event_summary(dbpath,now,days):
    """Distinct event-engine records, NOT the overlapping forecast windows.

    These are extracted vehicle_events (not GPS-verified entire journeys).
    """
    from pathlib import Path
    uri=Path(dbpath).resolve().as_uri()+'?mode=ro'
    con=sqlite3.connect(uri,uri=True,timeout=15)
    con.row_factory=sqlite3.Row
    con.execute('PRAGMA query_only=ON')
    try:
        rows=con.execute('SELECT event_type,start_ts,end_ts,distance_km,duration_min FROM vehicle_events WHERE start_ts>=? AND start_ts<=? ORDER BY start_ts',
            (now-days*86400,now)).fetchall()
    except sqlite3.OperationalError:
        rows=[]
    finally:con.close()
    out={}
    for period,cutoff in [('24h',now-86400),('7d',now-7*86400)]:
        applicable=[r for r in rows if float(r['start_ts'])>=cutoff]
        drives=[r for r in applicable if r['event_type']=='drive' and (float(r['distance_km'] or 0)>=0.2 or float(r['duration_min'] or 0)>=2)]
        parks=[r for r in applicable if r['event_type'] in ('park','sleep','cold_soak') and float(r['duration_min'] or 0)>=30]
        charges=[r for r in applicable if r['event_type']=='charge' and float(r['duration_min'] or 0)>=3]
        out[period]={'recorded_drive_events':len(drives),'recorded_park_events':len(parks),'recorded_charge_events':len(charges),
                'recorded_drive_miles':round(sum(float(r['distance_km'] or 0)*0.621371 for r in drives),1)}
    out['note']='These are distinct rows in Ghost vehicle_events, not verified full routes; brief stops and telemetry gaps can split events.'
    return out

def evaluate(dbpath,mod,now,days=7):
    forecasts,bycar,tsbycar,sample_count=mod.read_data(dbpath,now,days)
    episodes,ep_stats=build_episodes(bycar,mod)
    entries=[]
    for f in forecasts:
        car=str(f['car_id']);rows=bycar.get(car,[])
        if not rows: continue
        a=tsbycar[car]
        j=bisect.bisect_left(a,float(f['source_ts']))
        if j>=len(a) or abs(a[j]-float(f['source_ts']))>120:continue
        label=mod.classify_window(f,rows,a)
        if f['model_name']=='park_soc_180m':
            st={'state':f['start_state'],'shift_state':f['start_shift'],
                'charging_state':f['start_charging'],'speed_kmh':f['start_speed']}
            if mod.driving(st) or mod.charging(st):continue
        err=mod.nfloat(f.get('signed_error'))
        if err is None:
            p=mod.nfloat(f.get('predicted_value'));act=mod.nfloat(f.get('actual_value'))
            if p is None or act is None:continue
            err=p-act
        entries.append({'model':f['model_name'], 'ts':float(f['predicted_at']), 'context':context(label),
                        'car_key':car, 'episode':episodes[car][j], 'error':err,
                        'sentry':label.get('sentry_mode','unknown'),
                        'start_soc':mod.nfloat(f.get('starting_soc')),
                        'actual_soc':mod.nfloat(f.get('actual_value'))})
    report={'version':VERSION,'generated_epoch':int(now),
        'generated_local':dt.datetime.fromtimestamp(now).strftime('%Y-%m-%d %I:%M %p'),
        'lookback_days':days,'telemetry_rows_scanned':sample_count,
        'resolved_forecasts_loaded':len(forecasts),'forecasts_scored':len(entries),
        'source':'read-only SQLite prediction_audit + telemetry via v1 classifier',
        'notes':['Forecasts are overlapping, not independent trips.',
                 'Origin episodes are contiguous observed telemetry states, not GPS-verified routes.',
                 'Windows containing >10 minute gaps or truth >5 minutes off target are excluded from clean contexts.',
                 'Sentry observations are observational and do not prove causation.',
                 'Original forecast records and production predictions are unchanged.'],
        'episode_stats':ep_stats,'recorded_events':recorded_event_summary(dbpath,now,days),'models':{},'daily_trend':{},'sentry':{}}
    for name in MODELS:
        this=[e for e in entries if e['model']==name]
        report['models'][name]={}
        for period,cutoff in [('24h',now-86400),('7d',now-7*86400)]:
            within=[e for e in this if e['ts']>=cutoff]
            report['models'][name][period]={'all':metric(within),**{g:metric([e for e in within if e['context']==g]) for g in GROUPS}}
        trends=[]
        for offset in range(6,-1,-1):
            date=(dt.datetime.fromtimestamp(now)-dt.timedelta(days=offset)).date()
            day=[e for e in this if dt.datetime.fromtimestamp(e['ts']).date()==date]
            clean=[e for e in day if e['context']=='stationary']
            trends.append({'day':date.isoformat(),'all':metric(day),'stationary':metric(clean)})
        report['daily_trend'][name]=trends
    parked=[e for e in entries if e['model']=='park_soc_180m' and e['context']=='stationary'
            and e['ts']>=now-7*86400]
    for key in ('on','off','mixed','unknown'):
        group=[e for e in parked if e['sentry']==key]
        m=metric(group)
        drops=[(e['start_soc']-e['actual_soc']) for e in group if e['start_soc'] is not None and e['actual_soc'] is not None]
        m['observed_mean_3h_soc_drop_pp']=round(statistics.fmean(drops),3) if drops else None
        report['sentry'][key]=m
    return report

def text_report(r):
    o=['GHOST FORECAST QUALITY v2 - SESSION-WEIGHTED EVALUATION',
       'Generated: '+r['generated_local'],
       'Shadow-only; existing predictions, DB, training, and model promotion unchanged.',
       'Source forecast windows: '+str(r['resolved_forecasts_loaded'])+' | Scored: '+str(r['forecasts_scored']),
       'Independent-unit PROXY: contiguous observed origin episodes, not distinct verified journeys.',
       'Coverage gaps >10 min exclude a forecast from clean contexts.','']
    ep=r['episode_stats'];o.append('Observed activity segments: '+str(ep));o.append('Distinct stored vehicle_events: '+str(r['recorded_events']))
    for name in MODELS:
        o += ['','='*69, name.upper()]
        for period in ('24h','7d'):
            o.append(' '+period)
            for label in ('all',)+GROUPS:
                m=r['models'][name][period][label]
                if m['forecasts'] ==0 and label not in ('all','stationary'):continue
                def fmt(v):return '-' if v is None else ('%.2f'%v)
                o.append('  %-22s windows=%5d MAE=%6s pp origin_segments=%4d segment-MAE=%6s pp'%(
                    label,m['forecasts'],fmt(m['mae_pp']),m['origin_episodes'],fmt(m['episode_weighted_mae_pp'])))
    o += ['','SENTRY (clean parked windows; 7-day observational comparisons)']
    for k,m in r['sentry'].items():
        o.append('  %-8s windows=%5d episodes=%4d mean3h_SOC_loss=%s pp'%(k,m['forecasts'],m['origin_episodes'],m['observed_mean_3h_soc_drop_pp']))
    o += ['','NEXT STEP: Check accuracy by distinct completed drives once separate verified drive outcomes are available.',
          'Hourly timer status must be verified from the installation postcheck.',
          'END: No production predictions, database tables, or model artifacts altered.']
    return '\n'.join(o)+'\n'

def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp');tmp.write_text(data,encoding='utf-8');os.replace(tmp,path)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db',default='/var/lib/ghost-tesla-ai/ghost_ai.sqlite3')
    p.add_argument('--v1',default=str(BASE/'evaluate.py'))
    p.add_argument('--out',default=str(BASE))
    p.add_argument('--days',type=int,default=7)
    p.add_argument('--now',type=float,default=None)
    a=p.parse_args()
    if not 1<=a.days<=14:p.error('days must be 1..14')
    if not Path(a.db).is_file():p.error('missing DB: '+a.db)
    v1=load_v1(Path(a.v1));now=a.now if a.now is not None else time.time()
    result=evaluate(a.db,v1,now,a.days)
    out=Path(a.out)
    atomic(out/'v2-latest.json',json.dumps(result,indent=2,allow_nan=False)+'\n')
    content=text_report(result)
    atomic(out/'v2-latest.txt',content)
    day=dt.datetime.fromtimestamp(now).strftime('%Y-%m-%d')
    atomic(out/'daily'/(day+'-v2.json'),json.dumps(result,indent=2,allow_nan=False)+'\n')
    atomic(out/'daily'/(day+'-v2.txt'),content)
    print(content)

if __name__=='__main__':main()

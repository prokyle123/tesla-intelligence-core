#!/usr/bin/env python3
"""Ghost Trip Quality v3.1 - trip-chain-aware shadow scoring and Tessie sensor validation.
Reads existing SQLite in query-only mode and frozen readiness; never asks Tessie for data.
"""
from __future__ import annotations
import argparse, collections, datetime as dt, json, math, os, sqlite3, statistics, sys, time
from pathlib import Path
from urllib.parse import quote

BASE=Path('/home/ghost/ghost-forecast-quality')
DB=Path('/var/lib/ghost-tesla-ai/ghost_ai.sqlite3')
SIDECAR=Path('/home/ghost/ghost-trip-sequence/prediction-eval-v3.sqlite3')
VERSION='3.1.0'
MIPERKM=.621371

def num(x):
    try:
        y=float(x);return y if math.isfinite(y) else None
    except (TypeError,ValueError,OverflowError):return None

def conn(path):
    c=sqlite3.connect('file:'+quote(str(Path(path).resolve()))+'?mode=ro',uri=True,timeout=20)
    c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');return c

def stamp(ts):return dt.datetime.fromtimestamp(float(ts)).strftime('%Y-%m-%d %I:%M %p')
def avg(x):return round(statistics.fmean(x),3) if x else None
def metric(x):
    vals=[num(v) for v in x];vals=[v for v in vals if v is not None]
    return {'n':len(vals),'mae':avg([abs(v) for v in vals]),'bias':avg(vals)}

def make_chains(events,charge_events,now):
    """Group observed drive events split by stops <=15 minutes, NEVER across a charge.
    Unfinished events excluded. A chain is a candidate journey, not proof of same destination.
    """
    eligible=[]
    for e in sorted(events,key=lambda x:float(x['start_ts'])):
        d=num(e.get('distance_km')); t=num(e.get('duration_min'))
        if d is None or d<.5 or t is None or t<2 or not (float(e['start_ts'])<float(e['end_ts'])<now-120):continue
        if num(e.get('start_soc')) is None or num(e.get('end_soc')) is None:continue
        eligible.append(e)
    chains=[]
    for e in eligible:
        attach=False
        if chains:
            prior=chains[-1][-1]
            gap=float(e['start_ts'])-float(prior['end_ts'])
            blocked=any(float(q['start_ts'])<float(e['start_ts']) and float(q['end_ts'])>float(prior['end_ts']) and
                        float(q['end_ts'])>=float(prior['end_ts']) and float(q['start_ts'])<=float(e['start_ts']) for q in charge_events)
            attach=0<=gap<=900 and not blocked and str(e.get('car_id'))==str(prior.get('car_id'))
        if attach:chains[-1].append(e)
        else:chains.append([e])
    return chains

def chain_record(chain):
    a=chain[0];z=chain[-1]
    distance=sum((num(q.get('distance_km')) or 0)*MIPERKM for q in chain)
    en=[num(q.get('energy_used_kwh')) for q in chain]
    energy=sum(en) if all(v is not None and v>=0 for v in en) else None
    return {'event_ids':[int(q['id']) for q in chain], 'start_ts':float(a['start_ts']), 'end_ts':float(z['end_ts']),
            'start_time':stamp(a['start_ts']),'end_time':stamp(z['end_ts']), 'legs':len(chain),
            'stopped_minutes':round(sum(max(0,(float(b['start_ts'])-float(x['end_ts']))/60) for x,b in zip(chain,chain[1:])),1),
            'distance_mi':round(distance,2),'energy_kwh':round(energy,3) if energy is not None else None,
            'start_soc':num(a.get('start_soc')),'end_soc':num(z.get('end_soc')),
            'soc_drop_pp':round(float(a['start_soc'])-float(z['end_soc']),2),
            'pack_temp_f':round(avg([float(x['avg_pack_c']) for x in chain if x.get('avg_pack_c') is not None])*1.8+32,1) if any(x.get('avg_pack_c') is not None for x in chain) else None,
            'outside_temp_f':round(avg([float(x['avg_outside_c']) for x in chain if x.get('avg_outside_c') is not None])*1.8+32,1) if any(x.get('avg_outside_c') is not None for x in chain) else None,
            'recorded_drive_segments':len(chain)}

def category(j):
    t=dt.datetime.fromtimestamp(j['start_ts']);m=j['distance_mi']
    if t.weekday()<5 and 4<=t.hour<10 and 20<=m<=80:return 'weekday_morning_candidate'
    if t.weekday()<5 and 11<=t.hour<19 and 20<=m<=150:return 'weekday_afternoon_candidate'
    return 'other_or_multistop'

def coverage_check(con,journey):
    """Reject a journey from scoring when missing telemetry could hide activity."""
    timestamps=[float(x['ts']) for x in con.execute('SELECT ts FROM telemetry WHERE ts BETWEEN ? AND ? ORDER BY ts',(journey['start_ts']-60,journey['end_ts']+60))]
    if not timestamps:return {'ok':False,'max_gap_min':None,'samples':0}
    gaps=[(b-a)/60 for a,b in zip(timestamps,timestamps[1:])]
    greatest=max(gaps,default=0)
    # per-leg pauses already handled separately; ensure there aren't hidden 10+min windows
    return {'ok':greatest<=10,'max_gap_min':round(greatest,2),'samples':len(timestamps)}

def gps_verified(sidecar,now,days):
    out=[]
    if not sidecar.is_file():return {'status':'absent','outcomes':[]}
    try:
        with conn(sidecar) as c:
            cols={r['name'] for r in c.execute('PRAGMA table_info(forecasts)')}
            fields={'status','captured_at','predicted_ts','actual_start_ts','actual_end_ts','origin_site','destination_site','destination_match','actual_soc_drop','predicted_soc_drop'}
            if not fields.issubset(cols):return {'status':'schema_incompatible','outcomes':[]}
            rs=c.execute('SELECT '+','.join(sorted(fields))+' FROM forecasts WHERE status=? AND actual_start_ts>=? AND actual_end_ts<=? ORDER BY captured_at DESC',('SCORED',now-days*86400,now)).fetchall()
        seen=set()
        for row in rs:
            r=dict(row);start=num(r['actual_start_ts']);end=num(r['actual_end_ts']);cap=num(r['captured_at']);pred=num(r['predicted_ts'])
            if None in (start,end,cap,pred) or not cap+20*60<=start<end<=now:continue
            if r['destination_match']!=1 or not r['origin_site'] or not r['destination_site'] or r['origin_site']==r['destination_site']:continue
            if abs((pred-start)/60)>240:continue
            key=(round(start/180),round(end/180),r['origin_site'],r['destination_site'])
            if key in seen:continue
            seen.add(key)
            drop=num(r['actual_soc_drop']);forecast=num(r['predicted_soc_drop'])
            out.append({'start_ts':start,'end_ts':end,'site_route':str(r['origin_site'])+' -> '+str(r['destination_site']),
                        'departure_error_min':round((pred-start)/60,2),
                        'soc_drop_error_pp':round(forecast-drop,2) if drop is not None and forecast is not None and 0<=drop<=70 and 0<=forecast<=70 else None})
        return {'status':'available','outcomes':out}
    except (OSError,sqlite3.Error):return {'status':'read_error','outcomes':[]}

def match_verified(j,verified):
    # STRICT: require both ends to align with frozen GPS-verified outcome.
    found=[r for r in verified if abs(r['start_ts']-j['start_ts'])<=12*60 and abs(r['end_ts']-j['end_ts'])<=12*60]
    if len(found)==1:return found[0]['site_route']
    return None

def assess_forecast(j,snaps,coverage):
    """Only score when full journey length, target departure and temporal evidence agree.
    No future leakage: persisted readiness snapshots only, never rerun current model on history.
    """
    candidates=collections.defaultdict(list); counters=collections.Counter()
    for s in snaps:
        created=num(s['created_at']);target=num(s['departure_ts'])
        if None in (created,target):continue
        lead=(j['start_ts']-created)/60
        if lead<20 or lead>18*60:continue
        delta=(target-j['start_ts'])/60
        if abs(delta)>45:continue
        bucket='advance' if lead>=240 else 'predrive'
        candidates[bucket].append(s)
    scored=[];rejected=[]
    for bucket,rows in sorted(candidates.items()):
        s=max(rows,key=lambda k:float(k['created_at']))
        plan=None;tp={}
        try:tp=json.loads(s.get('payload_json') or '{}')
        except (ValueError,TypeError):pass
        routine=tp.get('routine') or {}
        plan=num(routine.get('distance_mi'))
        diff=None if plan is None else abs(j['distance_mi']-plan)
        threshold=max(5.0,j['distance_mi']*.15)
        valid_distance=diff is not None and diff<=threshold
        pred_arr=num(s.get('predicted_arrival_soc'));pred_dep=num(s.get('predicted_departure_soc'))
        trip=(tp.get('trip_prediction') or {})
        predicted_energy=num((trip.get('trip_energy_kwh') or {}).get('value')) if isinstance(trip.get('trip_energy_kwh'),dict) else None
        reason=None
        if not coverage['ok']:reason='insufficient_telemetry_coverage'
        elif not valid_distance:reason='forecast_route_distance_mismatch'
        elif pred_arr is None:reason='missing_frozen_arrival_forecast'
        if reason: counters[reason]+=1
        info={'bucket':bucket,'captured':stamp(s['created_at']),'lead_min':round((j['start_ts']-s['created_at'])/60,1),
              'target_departure':stamp(s['departure_ts']), 'departure_error_min':round((s['departure_ts']-j['start_ts'])/60,2),
              'planned_distance_mi':plan,'actual_journey_distance_mi':j['distance_mi'], 'distance_difference_mi':round(diff,2) if diff is not None else None,
              'predicted_arrival_soc':pred_arr,'actual_arrival_soc':j['end_soc'], 'predicted_departure_soc':pred_dep,
              'status':'scored' if not reason else 'withheld','reason':reason,
              'arrival_error_pp':round(pred_arr-j['end_soc'],2) if not reason else None,
              'energy_error_kwh':round(predicted_energy-j['energy_kwh'],3) if not reason and predicted_energy is not None and j['energy_kwh'] is not None else None}
        if reason:rejected.append(info)
        else:scored.append(info)
    return scored,rejected,dict(counters),len(candidates)

SENSORS={
 'vehicle_state.sentry_mode':('Sentry Mode','boolean'),
 'vehicle_state.tpms_pressure_fl':('Tire pressure FL','pressure'),
 'vehicle_state.tpms_pressure_fr':('Tire pressure FR','pressure'),
 'vehicle_state.tpms_pressure_rl':('Tire pressure RL','pressure'),
 'vehicle_state.tpms_pressure_rr':('Tire pressure RR','pressure'),
 'vehicle_state.locked':('Door lock status','boolean'),
 'vehicle_state.software_update.status':('Software update status','status'),
 'climate_state.fan_status':('Climate fan status','number'),
 'charge_state.charge_port_door_open':('Charge port door','boolean'),
 'charge_state.charge_limit_soc_std':('Standard charge limit','number'),
 'vehicle_state.sentry_mode_available':('Sentry Mode available','boolean'),
}

def deep_get(raw,key):
    x=raw
    for part in key.split('.'):
        if not isinstance(x,dict) or part not in x:return None,False
        x=x[part]
    return x,True

def sensor_inventory(con,now):
    rs=con.execute('SELECT raw_json,ts,sentry_mode FROM telemetry WHERE ts>=? ORDER BY ts DESC LIMIT 10000',(now-7*86400,)).fetchall()
    things={path:{'field':path,'label':label,'type':ty,'present':0,'nonnull':0,'nonzero':0,'distinct':set(),'last_changed_at':None,'last_seen_at':None,'previous':None} for path,(label,ty) in SENSORS.items()}
    raw_sentry=collections.Counter(); norm_sentry=collections.Counter()
    for r in reversed(rs):
        norm_sentry['unknown' if r['sentry_mode'] is None else 'on' if int(r['sentry_mode']) else 'off']+=1
        try:raw=json.loads(r['raw_json'] or '{}').get('state') or {}
        except (ValueError,TypeError):continue
        if not isinstance(raw,dict):continue
        for path,q in things.items():
            v,present=deep_get(raw,path)
            if present:q['present']+=1
            if v is None:continue
            q['nonnull']+=1
            meaningful= v is not False and v!='' and (not isinstance(v,(int,float)) or float(v)!=0)
            if meaningful:q['nonzero']+=1
            if isinstance(v,(str,bool,int,float)):
                fingerprint=str(v).lower()[:90]
                if len(q['distinct'])<100:q['distinct'].add(fingerprint)
                if q['previous'] is not None and q['previous']!=fingerprint:q['last_changed_at']=stamp(r['ts'])
                q['previous']=fingerprint
            q['last_seen_at']=stamp(r['ts'])
        v,_=deep_get(raw,'vehicle_state.sentry_mode')
        if v is None:raw_sentry['unknown']+=1
        elif isinstance(v,bool):raw_sentry['on' if v else 'off']+=1
    results=[]
    for p,q in things.items():
        n=q['nonnull'];d=len(q['distinct']);ty=q['type']
        if n==0:grade='no_values'
        elif ty=='pressure' and q['nonzero']==0:grade='zero_only_check_sensor'
        elif d==1:grade='constant_observed'
        else:grade='varying_observed'
        results.append({'field':p,'label':q['label'],'type':ty,'present_rows':q['present'], 'nonnull_rows':n,'nonzero_rows':q['nonzero'],
                        'distinct_values_capped':d,'assessment':grade, 'latest_observed_at':q['last_seen_at'],'last_changed_at':q['last_changed_at']})
    return {'raw_samples_examined':len(rs),'sentry_stored_sample_count':dict(norm_sentry),'sentry_raw_sample_count':dict(raw_sentry),
            'sensors':results,'notes':['Presence, non-null, non-zero and variability are different checks; zero and false can be legitimate readings.',
            'No raw values, addresses, coordinates, VIN, tokens or credentials are exported.',
            'These fields are in the existing /state raw payload. Fleet Telemetry or additional Tessie endpoints were not polled.',
            'Sentry status is already normalized; additional sensor columns must be planned and tested before adding any.']}

def report(db,sidecar,now,days):
    with conn(db) as c:
        row=c.execute('SELECT car_id FROM telemetry ORDER BY ts DESC LIMIT 1').fetchone()
        if row is None:raise ValueError('No telemetry')
        car=row['car_id']
        events=[dict(r) for r in c.execute("SELECT id,car_id,start_ts,end_ts,distance_km,duration_min,start_soc,end_soc,energy_used_kwh,avg_pack_c,avg_outside_c FROM vehicle_events WHERE car_id=? AND event_type='drive' AND start_ts>=? ORDER BY start_ts",(car,now-days*86400))]
        charges=[dict(r) for r in c.execute("SELECT start_ts,end_ts FROM vehicle_events WHERE car_id=? AND event_type='charge' AND end_ts>=? ORDER BY start_ts",(car,now-days*86400))]
        snaps=[dict(r) for r in c.execute("SELECT created_at,departure_ts,predicted_departure_soc,predicted_arrival_soc,payload_json FROM readiness_snapshots WHERE car_id=? AND created_at>=? AND created_at<=? AND departure_ts IS NOT NULL ORDER BY created_at",(car,now-(days+1)*86400,now))]
        chains=make_chains(events,charges,now)
        verified=gps_verified(sidecar,now,days)
        items=[]
        for chain in chains:
            j=chain_record(chain);j['candidate_route']=category(j)
            j['route_evidence']='time_and_distance_candidate_only'
            route=match_verified(j,verified['outcomes'])
            if route:j['verified_route']=route;j['route_evidence']='gps_outcome_confirmed'
            cvr=coverage_check(c,j);j['coverage']=cvr
            s,r,counts,eligible=assess_forecast(j,snaps,cvr)
            j['forecasts_scored']=s;j['forecasts_withheld']=r;j['eligible_snapshot_buckets']=eligible
            # This field should not be used for route-based training; only verified sites qualify.
            items.append(j)
        sensors=sensor_inventory(c,now)
    groups={}
    for cat in ('weekday_morning_candidate','weekday_afternoon_candidate','other_or_multistop'):
        js=[j for j in items if j['candidate_route']==cat]
        matches=[v for j in js for v in j['forecasts_scored'] if v['bucket']=='advance']
        # Explicitly one advance match per journey, even when many snapshots existed.
        groups[cat]={'journeys':len(js),'multi_leg':sum(j['legs']>1 for j in js), 'advance_matches':len(matches),
                     'arrival_soc':metric([x['arrival_error_pp'] for x in matches]),
                     'departure_timing':metric([x['departure_error_min'] for x in matches]),
                     'energy':metric([x['energy_error_kwh'] for x in matches]),
                     'withheld_advance':sum(any(x['bucket']=='advance' for x in j['forecasts_withheld']) for j in js)}
    verified_groups={}
    for j in items:
        name=j.get('verified_route')
        if not name:continue
        verified_groups.setdefault(name,[]).append(j)
    verified_stats={name:{'journeys':len(js),
        'advance_matches':sum(any(f['bucket']=='advance' for f in j['forecasts_scored']) for j in js),
        'arrival_soc':metric([f['arrival_error_pp'] for j in js for f in j['forecasts_scored'] if f['bucket']=='advance'])}
        for name,js in verified_groups.items()}
    return {'version':VERSION,'generated_epoch':now,'generated_local':stamp(now),'lookback_days':days,'mode':'READ_ONLY_SHADOW',
            'event_segments_seen':len(events),'candidate_journeys':len(items),'multi_leg_journeys':sum(j['legs']>1 for j in items),
            'completed_journeys':list(reversed(items))[:150],'by_candidate':groups,'gps_matched_journeys':verified_stats,
            'gps_verified_sidecar':{'status':verified['status'],'verified_outcomes':len(verified['outcomes']), 'note':'Confirmed site label attached only when BOTH frozen GPS trip endpoints match this journey.'},
            'sensors':sensors,
            'notes':['A journey groups drives separated by <=15-minute stops; no merging across charging.',
                     'Forecast scored only when captured before departure, departure target within 45 minutes, measured coverage sufficient and planned distance matches complete journey.',
                     'Only frozen persisted readiness predictions used: NO retrospective model inference or model promotion.',
                     'Time-of-day morning/afternoon labels are NOT verified work/home routes.',
                     'Scores count at most one advance forecast per completed candidate journey; GPS status shown independently.',
                     'Stops and telemetry gaps may make a journey incomplete or uncertain; such results are not assumed to be verified destinations.']}

def save(path,text):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name('.'+path.name+'.tmp-'+str(os.getpid()))
    tmp.write_text(text,encoding='utf-8');os.chmod(tmp,0o600);os.replace(tmp,path)

def human(data):
    ln=[f'GHOST TRIP QUALITY v{VERSION} - MULTI-LEG FORECAST GUARD + SENSOR VALUE AUDIT',
        'Generated: '+data['generated_local'],'Mode: SHADOW READ-ONLY. Live AI, data collection and car control unchanged.',
        f"Drive event segments: {data['event_segments_seen']} | Candidate journeys: {data['candidate_journeys']} | Multi-leg journeys: {data['multi_leg_journeys']}",
        f"GPS outcome sidecar: {data['gps_verified_sidecar']['status']}; outcomes: {data['gps_verified_sidecar']['verified_outcomes']}",
        '', 'ACCURACY: STRICT ADVANCE FORECASTS, ONE PER CANDIDATE JOURNEY']
    for cat,g in data['by_candidate'].items():
        ln+= [f" {cat} | journeys {g['journeys']} | multi-leg {g['multi_leg']} | valid advance matches {g['advance_matches']} | withheld {g['withheld_advance']}",
              '   Arrival SOC: '+str(g['arrival_soc'])+' | departure: '+str(g['departure_timing'])+' | energy kWh: '+str(g['energy'])]
    ln+=['','GPS-MATCHED COMPLETED JOURNEYS (SITE IDS ONLY):']
    if not data['gps_matched_journeys']:ln.append('  No direct GPS-to-whole-journey matches established in current window.')
    for route,group in data['gps_matched_journeys'].items():ln.append('  '+route+' '+str(group))
    ln+=['','RECENT JOURNEYS:']
    for j in data['completed_journeys'][:24]:
        ln.append(f" {j['start_time']} | {j['distance_mi']:.1f} mi | legs {j['legs']} | SOC {j['start_soc']}->{j['end_soc']} | {j['candidate_route']} | GPS {j.get('verified_route','UNVERIFIED')} | coverage {j['coverage']['ok']}")
        for f in j['forecasts_scored']:
            ln.append(f"    SCORED {f['bucket']} lead {f['lead_min']:.0f}min | target error {f['departure_error_min']:+.1f}m | SOC error {f['arrival_error_pp']:+.1f}pp | modeled distance {f['planned_distance_mi']}mi")
        for f in j['forecasts_withheld']:
            ln.append(f"    WITHHELD {f['bucket']} lead {f['lead_min']:.0f}min | {f['reason']} | modeled {f['planned_distance_mi']} vs journey {j['distance_mi']}mi")
    x=data['sensors'];ln+=['','TESSIE SENSOR VALUE QUALITY (raw /state, no new API requests):',f"  Samples: {x['raw_samples_examined']} | sentry normalized: {x['sentry_stored_sample_count']}"]
    for s in x['sensors']:
        ln.append(f" {s['label']} ({s['field']}) | present={s['present_rows']} nonnull={s['nonnull_rows']} nonzero={s['nonzero_rows']} distinct={s['distinct_values_capped']} | {s['assessment']}")
    ln+=['','NOTES:']+[' - '+x for x in data['notes']]+['','No API token, VIN, GPS coordinates, address, or raw sensor values included.']
    return '\n'.join(ln)+'\n'

def run(db=DB,sidecar=SIDECAR,out=BASE,days=7,now=None):
    now=time.time() if now is None else now
    d=report(db,sidecar,now,days)
    save(out/'v31-latest.json',json.dumps(d,indent=2,allow_nan=False)+'\n')
    save(out/'v31-latest.txt',human(d))
    day=dt.datetime.fromtimestamp(now).strftime('%Y-%m-%d')
    save(out/'daily'/(day+'-v31.json'),json.dumps(d,indent=2,allow_nan=False)+'\n')
    print(human(d));return d

def selftest():
    base=1_700_000_000.0
    def row(i,start,end,miles,s0,s1):
        return {'id':i,'car_id':'test','start_ts':start,'end_ts':end,'distance_km':miles/MIPERKM,'duration_min':(end-start)/60,'start_soc':s0,'end_soc':s1,'energy_used_kwh':miles*.205,'avg_pack_c':22,'avg_outside_c':12}
    first=row(1,base,base+400,1.7,90,89)
    second=row(2,base+520,base+3900,38,89,78)
    third=row(3,base+7*3600,base+9*3600,68,77,54)
    fourth=row(4,base+9*3600+480,base+9*3600+2600,33,54,43)
    chains=make_chains([first,second,third,fourth],[],base+20*3600)
    assert [len(c) for c in chains]==[2,2],chains
    j=chain_record(chains[1]);assert j['distance_mi']>100
    assert len(make_chains([third,fourth],[{'start_ts':third['end_ts']+10,'end_ts':fourth['start_ts']-10}],base+20*3600))==2
    snaps=[{'created_at':base+4*3600,'departure_ts':third['start_ts']+500,
       'predicted_arrival_soc':50,'predicted_departure_soc':65,
       'payload_json':json.dumps({'routine':{'distance_mi':39.5},'trip_prediction':{'trip_energy_kwh':{'value':8}}})}]
    scored,rejected,_,_=assess_forecast(j,snaps,{'ok':True})
    assert not scored,'Afternoon 101mi journey must never inherit forecast for 39.5mi leg'
    assert len(rejected)==1 and rejected[0]['reason']=='forecast_route_distance_mismatch',rejected
    good=chain_record(chains[0]); assert good['legs']==2 and good['distance_mi']>39
    morning=[{'created_at':base-300*60,'departure_ts':first['start_ts']+2*60,'predicted_arrival_soc':78.4,'predicted_departure_soc':91.0,'payload_json':json.dumps({'routine':{'distance_mi':39.7},'trip_prediction':{'trip_energy_kwh':{'value':8.0}}})}]
    good_forecasts,good_rejected,_,_=assess_forecast(good,morning,{'ok':True})
    assert len(good_forecasts)==1 and not good_rejected and good_forecasts[0]['arrival_error_pp']==0.4
    fail_coverage,hold,_,_=assess_forecast(good,morning,{'ok':False})
    assert not fail_coverage and hold[0]['reason']=='insufficient_telemetry_coverage'
    assert metric([2,-1,None])['mae']==1.5
    print('SELFTEST PASS: multi-leg, charge barrier, mismatch rejection, no false scoring')

def main():
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,default=DB);p.add_argument('--sidecar',type=Path,default=SIDECAR);p.add_argument('--out',type=Path,default=BASE);p.add_argument('--days',type=int,default=7);p.add_argument('--self-test',action='store_true');a=p.parse_args()
    if a.self_test:selftest();return
    if not 1<=a.days<=30:p.error('days 1..30')
    run(a.db,a.sidecar,a.out,a.days)
if __name__=='__main__':main()

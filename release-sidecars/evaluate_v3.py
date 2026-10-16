#!/usr/bin/env python3
"""GHOST Trip Quality v3: shadow / event-level commute scoring + Tessie payload audit.
Never sends Tessie requests, edits the SQLite database or touches ML artifacts.
"""
from __future__ import annotations
import argparse, collections, datetime as dt, json, math, os, sqlite3, statistics, time
from pathlib import Path
from urllib.parse import quote

ROOT=Path('/home/ghost/ghost-forecast-quality')
DB=Path('/var/lib/ghost-tesla-ai/ghost_ai.sqlite3')
MI_PER_KM=0.621371
VERSION='3.0.0'


def f(x):
    try:
        y=float(x)
        return y if math.isfinite(y) else None
    except (ValueError,TypeError,OverflowError):return None


def date_str(ts,fmt='%Y-%m-%d %I:%M %p'):
    return dt.datetime.fromtimestamp(ts).strftime(fmt)


def connect(path):
    c=sqlite3.connect('file:'+quote(str(Path(path).resolve()))+'?mode=ro',uri=True,timeout=20)
    c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');return c


def avg_abs(xs):
    return round(statistics.fmean(abs(x) for x in xs),3) if xs else None


def stats(items,field):
    errs=[f(r.get(field)) for r in items]
    errs=[x for x in errs if x is not None]
    return {'trips':len(errs),'mae':avg_abs(errs),'bias':round(statistics.fmean(errs),3) if errs else None}


def classify_time(ts,distance):
    local=dt.datetime.fromtimestamp(ts)
    if local.weekday()<5 and 4<=local.hour<10 and 12<=distance<=75:
        return 'weekday_morning_long_drive'
    if local.weekday()<5 and 11<=local.hour<19 and 12<=distance<=75:
        return 'weekday_afternoon_long_drive'
    return 'other_drive'


def matched_frozen_predictions(event, snapshots):
    """Pre-drive forecasts only, departure matching, one snapshot per lead-time bin."""
    matches={}
    start=f(event['start_ts'])
    if start is None:return []
    for s in snapshots:
        created=f(s['created_at']); target=f(s['departure_ts'])
        if created is None or target is None:continue
        lead=(start-created)/60
        if not (20<=lead<=18*60):continue
        departure_error=(target-start)/60
        if abs(departure_error)>45:continue
        bucket='previous_evening_or_advance' if lead>=240 else 'same_day_pre_drive'
        if bucket not in matches or created>float(matches[bucket]['created_at']):matches[bucket]=s
    out=[]
    for bucket,s in matches.items():
        p=f(s['predicted_departure_soc']);a=f(s['predicted_arrival_soc'])
        tp={}
        try:tp=json.loads(s['payload_json'] or '{}')
        except (ValueError,TypeError):pass
        trip=tp.get('trip_prediction') or {}
        modeled_miles=f((tp.get('routine') or {}).get('distance_mi'))
        actual_miles=float(event['distance_mi'])
        comparable=modeled_miles is not None and abs(modeled_miles-actual_miles)<=max(5,actual_miles*.15)
        energy_forecast=f((trip.get('trip_energy_kwh') or {}).get('value')) if isinstance(trip.get('trip_energy_kwh'),dict) else None
        actual_energy=f(event['energy_used_kwh'])
        row={'bucket':bucket,'captured':date_str(s['created_at']),'lead_min':round((event['start_ts']-s['created_at'])/60,1),
             'predicted_departure':date_str(s['departure_ts']),'departure_error_min':round((s['departure_ts']-event['start_ts'])/60,2),
             'pred_start_soc':p,'pred_arrival_soc':a,'actual_start_soc':event['start_soc'],'actual_end_soc':event['end_soc'],
             'departure_soc_error_pp':round(p-event['start_soc'],3) if p is not None and event['start_soc'] is not None else None,
             'arrival_soc_error_pp':round(a-event['end_soc'],3) if a is not None and event['end_soc'] is not None else None,
             'modeled_distance_mi':modeled_miles,'distance_comparable':comparable,
             'forecast_energy_kwh':energy_forecast,'actual_energy_kwh':actual_energy,
             'energy_error_kwh':round(energy_forecast-actual_energy,3) if comparable and energy_forecast is not None and actual_energy is not None else None,
             'energy_score_note':'scored only if modeled route distance within 15% or 5 mi' if comparable else 'not comparable: forecast routine distance differs from completed drive'}
        out.append(row)
    return sorted(out,key=lambda x:x['bucket'])


def confirmed_routes(sidecar,now,days=14):
    """Optional v3.2 frozen forecasts: GPS destination must be scored and confirmed.
    Deduplicate multiple predictions for same completed drive; use latest capture before departure.
    """
    if not sidecar.is_file():return {'status':'unavailable','note':'Verified route sidecar not installed','trips':[]}
    try:
        with connect(sidecar) as con:
            cols={r['name'] for r in con.execute('PRAGMA table_info(forecasts)')}
            required={'id','status','captured_at','predicted_ts','actual_start_ts','actual_end_ts','origin_site','destination_site','destination_match','predicted_soc_drop','actual_soc_drop','error_min'}
            if not required.issubset(cols):return {'status':'incompatible','note':'Unknown sidecar schema','trips':[]}
            rs=con.execute('SELECT '+','.join(sorted(required))+' FROM forecasts WHERE status=? AND actual_start_ts>=? AND actual_end_ts<=? ORDER BY captured_at DESC',('SCORED',now-days*86400,now)).fetchall()
        uniq={}
        for r in rs:
            p=dict(r);start=f(p['actual_start_ts']);end=f(p['actual_end_ts']);cap=f(p['captured_at']);pred=f(p['predicted_ts'])
            if None in (start,end,cap,pred) or not (cap+20*60<=start<end<=now):continue
            if p['destination_match']!=1 or not p['origin_site'] or not p['destination_site'] or p['origin_site']==p['destination_site']:continue
            if abs((pred-start)/60)>240:continue
            key=(round(start/120),round(end/120),p['origin_site'],p['destination_site'])
            if key not in uniq:uniq[key]={'start_ts':start,'end_ts':end,'origin_site':p['origin_site'],'destination_site':p['destination_site'],
                                      'pred_start':pred,'departure_error_min':round((pred-start)/60,2),
                                      'actual_soc_drop':f(p['actual_soc_drop']),'predicted_soc_drop':f(p['predicted_soc_drop'])}
        out=sorted(uniq.values(),key=lambda x:x['start_ts'],reverse=True)
        for r in out:
            x,y=r['actual_soc_drop'],r['predicted_soc_drop']
            r['soc_drop_error_pp']=round(y-x,3) if x is not None and y is not None and 0<=x<=70 and 0<=y<=70 else None
            r['start_time']=date_str(r['start_ts'])
            del r['start_ts'];del r['end_ts'];del r['pred_start']
        return {'status':'available','note':'One latest valid frozen forecast per GPS-verified completed route; SITE identifiers only','trips':out}
    except (sqlite3.DatabaseError,OSError) as exc:
        return {'status':'unavailable','note':'Sidecar read issue: '+type(exc).__name__,'trips':[]}


def telem_fields(root,prefix=''):
    if not isinstance(root,dict):return []
    leaves=[]
    for k,v in root.items():
        path=prefix+'.'+k if prefix else k
        if isinstance(v,dict):leaves.extend(telem_fields(v,path))
        else:leaves.append(path)
    return leaves

# Deliberately restrictive set: only facts confirmed by the installed parser source.
# Paths can exist yet report NULL because model/firmware/Tessie does not expose a value.
MAPPINGS={
 'vehicle_state.sentry_mode':'sentry_mode','vehicle_state.is_user_present':'user_present',
 'vehicle_state.odometer':'odometer_km','drive_state.speed':'speed_kmh',
 'drive_state.shift_state':'shift_state','drive_state.power':'power_kw',
 'charge_state.battery_level':'battery_level','charge_state.usable_battery_level':'usable_battery_level',
 'charge_state.charge_limit_soc':'charge_limit_soc','charge_state.charging_state':'charging_state',
 'charge_state.charger_voltage':'charger_voltage','charge_state.charger_actual_current':'charger_actual_current',
 'charge_state.charger_power':'charger_power_kw','charge_state.charge_energy_added':'charge_energy_added_kwh',
 'charge_state.charge_current_request':'charge_current_request','charge_state.minutes_to_full_charge':'minutes_to_full_charge',
 'charge_state.battery_heater_on':'battery_heater_on',
 'climate_state.outside_temp':'outside_temp_c','climate_state.inside_temp':'inside_temp_c',
 'climate_state.is_climate_on':'climate_on','climate_state.is_preconditioning':'preconditioning',
 'climate_state.defrost_mode':'defrost_mode','climate_state.driver_temp_setting':'driver_temp_setting_c'
}
REVIEW_FIELDS={
 'vehicle_state.locked':'Vehicle locked status',
 'vehicle_state.tpms_pressure_fl':'Front-left tire pressure',
 'vehicle_state.tpms_pressure_fr':'Front-right tire pressure',
 'vehicle_state.tpms_pressure_rl':'Rear-left tire pressure',
 'vehicle_state.tpms_pressure_rr':'Rear-right tire pressure',
 'vehicle_state.software_update.status':'Software update state',
 'climate_state.fan_status':'Cabin fan',
 'charge_state.charge_port_door_open':'Charge port door',
 'charge_state.charge_limit_soc_std':'Standard charge limit',
 'vehicle_state.sentry_mode_available':'Sentry availability'
}

def inventory(con,now):
    # No raw values, credentials, coordinates or VIN ever leave this report.
    cols={r['name'] for r in con.execute('PRAGMA table_info(telemetry)')}
    rows=con.execute('SELECT raw_json,sentry_mode,state,ts FROM telemetry WHERE ts>=? AND ts<=? ORDER BY ts DESC LIMIT 10000',(now-7*86400,now)).fetchall()
    present=collections.Counter();nonnull=collections.Counter();sent=collections.Counter();roots=collections.Counter();sentry_raw=collections.Counter();last_value=None
    for r in rows:
        val=r['sentry_mode'];sent['unknown' if val is None else 'on' if val==1 else 'off']+=1
        if last_value is None and val is not None:last_value='on' if val==1 else 'off'
        try:q=json.loads(r['raw_json'] or '{}')
        except (ValueError,TypeError):continue
        st=q.get('state') or {}
        if not isinstance(st,dict):continue
        roots.update(st.keys())
        paths=telem_fields(st)
        for p in paths:present[p]+=1
        # Accurate nested non-null field counting without exposing field content.
        def search(path):
            item=st
            for part in path.split('.'):
                if not isinstance(item,dict):return None
                item=item.get(part)
            return item
        for p in paths:
            if search(p) is not None:nonnull[p]+=1
        raw_s=search('vehicle_state.sentry_mode')
        if isinstance(raw_s,bool):sentry_raw['on' if raw_s else 'off']+=1
        elif raw_s is None:sentry_raw['unknown']+=1
    known=[{'path':p,'stored_column':col,'present_samples':present[p],'nonnull_samples':nonnull[p]} for p,col in MAPPINGS.items() if present[p] or nonnull[p]]
    candidate=[{'path':p,'description':desc,'observed_nonnull_samples':nonnull[p],'present_samples':present[p],'normalized_column':'none' if p not in MAPPINGS else MAPPINGS[p]} for p,desc in REVIEW_FIELDS.items()]
    # This list deliberately excludes keys indicating credentials, location, keys, identity or personally sensitive data.
    disallowed=('lat','lon','vin','token','key','location','calendar','name','homelink','driver','gps','address','pin','media','password','id')
    extra=[{'path':p,'nonnull_samples':n} for p,n in nonnull.most_common() if p not in MAPPINGS and p not in REVIEW_FIELDS and not any(w in p.lower() for w in disallowed) and p.count('.')<=2]
    return {'samples_analyzed':len(rows),'known_mapped_signals':len(MAPPINGS),'known_columns_present':sorted(c for c in set(MAPPINGS.values()) if c in cols),
      'mapped_path_coverage':known,'tessie_payload_keys_seen':len(present),
      'potential_additions':candidate,'other_unmapped_field_paths':extra[:80],
      'sentry':{'column_available':'sentry_mode' in cols,'stored_7d':dict(sent),'raw_7d':dict(sentry_raw),'latest_recorded':last_value},
      'notes':['Inventory covers raw Tessie state payloads ALREADY stored by Ghost, not all possible Tessie endpoints or Fleet Telemetry signals.',
               'No external Tessie API call was made and no authentication token, VIN or location data are reported.',
               'Presence/non-null does not prove a sensor is accurate, fresh or supported by the car.',
               'Full returned state and battery payloads are already stored in telemetry.raw_json; normalized columns are only a subset.']}


def report(db,sidecar,now,days):
    with connect(db) as con:
        car=con.execute('SELECT car_id FROM telemetry ORDER BY ts DESC LIMIT 1').fetchone()
        if not car:raise RuntimeError('No telemetry records')
        car_id=car['car_id']
        events=[dict(x) for x in con.execute("SELECT id,start_ts,end_ts,distance_km,duration_min,start_soc,end_soc,energy_used_kwh,avg_pack_c,avg_outside_c,wh_per_mile FROM vehicle_events WHERE car_id=? AND event_type='drive' AND start_ts>=? AND end_ts<=? ORDER BY start_ts DESC",(car_id,now-days*86400,now))]
        snaps=[dict(x) for x in con.execute('SELECT created_at,departure_ts,predicted_departure_soc,predicted_arrival_soc,payload_json FROM readiness_snapshots WHERE car_id=? AND created_at>=? AND created_at<=? AND departure_ts IS NOT NULL ORDER BY created_at DESC',(car_id,now-(days+1)*86400,now))]
        inv=inventory(con,now)
    verified=confirmed_routes(sidecar,now,days)
    rows=[]
    for ev in events:
        miles=(f(ev['distance_km']) or 0)*MI_PER_KM
        mins=f(ev['duration_min']) or 0
        if not (miles>=1.0 and mins>=3 and f(ev['start_soc']) is not None and f(ev['end_soc']) is not None):continue
        ev['distance_mi']=round(miles,2)
        matches=matched_frozen_predictions(ev,snaps) if miles>=10.0 else []
        item={'event_id':int(ev['id']),'start_time':date_str(ev['start_ts']),'end_time':date_str(ev['end_ts']),
              'start_ts':ev['start_ts'],'distance_mi':round(miles,2),'duration_min':round(mins,1),
              'start_soc':ev['start_soc'],'end_soc':ev['end_soc'],
              'soc_drop_pp':round(ev['start_soc']-ev['end_soc'],2),'energy_used_kwh':f(ev['energy_used_kwh']),
              'wh_per_mile':f(ev['wh_per_mile']),
              'battery_temp_f':round(float(ev['avg_pack_c'])*1.8+32,1) if ev['avg_pack_c'] is not None else None,
              'outside_temp_f':round(float(ev['avg_outside_c'])*1.8+32,1) if ev['avg_outside_c'] is not None else None,
              'route_category':classify_time(ev['start_ts'],miles),
              'route_evidence':'time_and_length_only_not_GPS_verified',
              'readiness_forecasts':matches}
        rows.append(item)
    grp={}
    for cat in ('weekday_morning_long_drive','weekday_afternoon_long_drive','other_drive'):
        drives=[e for e in rows if e['route_category']==cat]
        matched=[(e,s) for e in drives for s in e['readiness_forecasts'] if s['bucket']=='previous_evening_or_advance']
        grp[cat]={'distinct_drive_events':len(drives),'miles':round(sum(e['distance_mi'] for e in drives),1),
                  'forecast_matched_drive_events':len(matched),
                  'arrival_soc_error_pp':stats([s for e,s in matched],'arrival_soc_error_pp'),
                  'departure_time_error_min':stats([s for e,s in matched],'departure_error_min'),
                  'energy_error_kwh':stats([s for e,s in matched],'energy_error_kwh')}
    verified_agg={}
    for r in verified['trips']:
        k=r['origin_site']+' -> '+r['destination_site'];verified_agg.setdefault(k,[]).append(r)
    verified_groups={k:{'gps_verified_trips':len(vals),'departure_time_error_min':stats(vals,'departure_error_min'),
                        'soc_drop_error_pp':stats(vals,'soc_drop_error_pp')} for k,vals in verified_agg.items()}
    return {'version':VERSION,'generated_epoch':round(now),'generated_local':date_str(now),'days':days,'mode':'SHADOW_READ_ONLY',
      'source':'stored vehicle_events and frozen readiness_snapshots; GPS-verified v3.2 sidecar where available',
      'model_generation_changed':False,'predictions_edited':False,
      'trips':rows[:150],'summary':grp,'total_completed_drive_events':len(rows),
      'verified_routes':{'status':verified['status'],'note':verified['note'],'groups':verified_groups,'trips':verified['trips'][:80]},
      'tessie_coverage':inv,
      'interpretation':['Every recorded drive event is counted once. Stops can still split one journey into multiple events.',
                        'Morning and afternoon long-drive labels are time-of-day candidates, NOT GPS-confirmed home/work route names.',
                        'Readiness forecasts must exist at least 20 minutes before the event and target a departure within 45 minutes; unmatched trips remain unmatched.',
                        'Earlier (>4h) and same-day forecasts are scored separately; arrival error compared to completed event, not a synthetic prediction.',
                        'Comparing predicted energy requires similar forecast and actual route distance; otherwise error is withheld.',
                        'Verified sidecar routes require status SCORED and GPS-confirmed destination; predictions deduplicated by finished trip.',
                        'Report contains no coordinates, VIN, tokens or raw API values.']}


def safe_write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name('.'+path.name+'.tmp-'+str(os.getpid()))
    tmp.write_text(data,encoding='utf-8');os.chmod(tmp,0o600);os.replace(tmp,path)


def text_report(r):
    o=['GHOST TRIP QUALITY v3 - DISTINCT COMPLETED DRIVES + TESSIE COVERAGE',
       'Generated: '+r['generated_local'],
       'SHADOW / READ-ONLY - no prediction, telemetry, model or charging changes',
       'Drive events (not guaranteed whole GPS routes): '+str(r['total_completed_drive_events']),
       'GPS verified sidecar status: '+r['verified_routes']['status'],'']
    for k,g in r['summary'].items():
        o.append(k.replace('_',' ').upper()+' | distinct drives '+str(g['distinct_drive_events'])+' | advance-forecast matches '+str(g['forecast_matched_drive_events']))
        o.append('  arrival SOC: '+str(g['arrival_soc_error_pp'])+' | departure min: '+str(g['departure_time_error_min'])+' | energy kWh: '+str(g['energy_error_kwh']))
    o.extend(['','GPS VERIFIED ROUTES (if sidecar confirms):'])
    for k,g in r['verified_routes']['groups'].items():o.append('  '+k+' '+str(g))
    if not r['verified_routes']['groups']:o.append('  No GPS-verified outcomes scored yet.')
    o.extend(['','RECENT DRIVE EVENTS:'])
    for e in r['trips'][:18]:
        o.append('%s | %s | %.1f mi | SOC %s->%s | %.2f kWh | forecasts %s'%(e['start_time'],e['route_category'],e['distance_mi'],e['start_soc'],e['end_soc'],e['energy_used_kwh'] or 0,len(e['readiness_forecasts'])))
        for p in e['readiness_forecasts']:
            o.append('   %s lead %.0f min | departure error %s min | arrival SOC error %s pp | energy error %s'%(p['bucket'],p['lead_min'],p['departure_error_min'],p['arrival_soc_error_pp'],p['energy_error_kwh']))
    c=r['tessie_coverage'];o.extend(['','TESSIE SENSOR / RAW PAYLOAD COVERAGE:',
      '  Raw state rows sampled: '+str(c['samples_analyzed']),
      '  Distinct raw state field paths observed: '+str(c['tessie_payload_keys_seen']),
      '  Sentry stored field: '+str(c['sentry']['column_available'])+ ' | latest: '+str(c['sentry']['latest_recorded']),
      '  Sentry mode history (7d; number of telemetry rows): '+str(c['sentry']['stored_7d']),
      '  Mapped field samples (selected):'])
    for e in c['mapped_path_coverage']:
        if e['path'].startswith(('vehicle_state.sentry','charge_state.','climate_state.is_climate')):o.append('    '+e['path']+' -> '+e['stored_column']+' : '+str(e['nonnull_samples']))
    o.append('  Optional field candidates (none are mapped yet in the confirmed source):')
    for x in c['potential_additions']:
        if x['observed_nonnull_samples']>0:o.append('    '+x['path']+' : '+str(x['observed_nonnull_samples'])+' available rows')
    o+=['','NOTES:','  Tessie /state is parsed to a curated set of typed fields; the raw /state and battery JSON are preserved.',
        '  This audit does not claim every Tessie or Tesla Fleet Telemetry signal was requested.',
        '  No API write, token exposure, location dump, training or DB writes.']
    return '\n'.join(o)+'\n'


def run(db,sidecar,out,days,now=None):
    now=time.time() if now is None else now
    data=report(db,sidecar,now,days)
    safe_write(out/'v3-latest.json',json.dumps(data,indent=2,allow_nan=False)+'\n')
    safe_write(out/'v3-latest.txt',text_report(data))
    day=dt.datetime.fromtimestamp(now).strftime('%Y-%m-%d')
    safe_write(out/'daily'/(day+'-v3.json'),json.dumps(data,indent=2,allow_nan=False)+'\n')
    print(text_report(data));return data


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db',type=Path,default=DB);p.add_argument('--out',type=Path,default=ROOT)
    p.add_argument('--sidecar',type=Path,default=Path('/home/ghost/ghost-trip-sequence/prediction-eval-v3.sqlite3'))
    p.add_argument('--days',type=int,default=7);a=p.parse_args()
    if not 1<=a.days<=30:p.error('days must be 1..30')
    if not a.db.is_file():p.error('Database missing')
    run(a.db,a.sidecar,a.out,a.days)
if __name__=='__main__':main()

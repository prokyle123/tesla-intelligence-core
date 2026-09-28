from __future__ import annotations
import json, math, statistics, time
from . import config, db
from .features import classify_regime

def _f(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except Exception:return None

def _mean(vals):
    vals=[x for x in (_f(v) for v in vals) if x is not None]
    return sum(vals)/len(vals) if vals else None

def _median(vals):
    vals=[x for x in (_f(v) for v in vals) if x is not None]
    return statistics.median(vals) if vals else None

def _event_type(regime):
    return {'driving':'drive','l1_charging':'charge','charging':'charge','preconditioning':'precondition','cold_soak':'cold_soak','sleeping':'sleep','parked':'park'}.get(regime,regime)

def _segment_metric(seg,event_type):
    a,b=seg[0],seg[-1]
    start_ts=float(a['ts']); end_ts=float(b['ts']); dur=max(0.0,(end_ts-start_ts)/60.0)
    so=_f(a['odometer_km']); eo=_f(b['odometer_km']); dist=None if so is None or eo is None else max(0.0,eo-so)
    ss=_f(a['battery_level']); es=_f(b['battery_level']); soc=None if ss is None or es is None else es-ss
    sp=_f(a['battery_temp_c']); ep=_f(b['battery_temp_c']); pchg=None if sp is None or ep is None else ep-sp
    le0=_f(a['lifetime_energy_used_kwh']); le1=_f(b['lifetime_energy_used_kwh']); used=None
    if le0 is not None and le1 is not None and le1>=le0: used=le1-le0
    er0=_f(a['energy_remaining_kwh']); er1=_f(b['energy_remaining_kwh']); erd=None if er0 is None or er1 is None else er1-er0
    if used is None and event_type=='drive' and erd is not None and erd<0: used=-erd
    miles=None if dist is None else dist*0.621371
    whmi=None if not used or not miles or miles<0.1 else used*1000.0/miles
    c0=_f(a['charge_energy_added_kwh']); c1=_f(b['charge_energy_added_kwh']); charge_added=None
    if c0 is not None and c1 is not None: charge_added=max(0.0,c1-c0)
    avg_out=_mean([r['outside_temp_c'] for r in seg]); avg_pack=_mean([r['battery_temp_c'] for r in seg])
    vals_out=[_f(r['outside_temp_c']) for r in seg]; vals_out=[x for x in vals_out if x is not None]
    meta={
      'regime':event_type,
      'start_state':a['state'],'end_state':b['state'],
      'start_shift':a['shift_state'],'end_shift':b['shift_state'],
      'plugged_fraction':round(sum(bool(r['plugged_in']) for r in seg)/max(1,len(seg)),3),
      'heater_fraction':round(sum(bool(r['battery_heater_on']) for r in seg if r['battery_heater_on'] is not None)/max(1,sum(r['battery_heater_on'] is not None for r in seg)),3) if seg else 0,
      'climate_fraction':round(sum(bool(r['climate_on']) for r in seg if r['climate_on'] is not None)/max(1,sum(r['climate_on'] is not None for r in seg)),3) if seg else 0,
    }
    return {
      'car_id':str(a['car_id']),'event_type':event_type,'start_ts':start_ts,'end_ts':end_ts,'duration_min':dur,'source_points':len(seg),
      'start_soc':ss,'end_soc':es,'soc_change':soc,'start_pack_c':sp,'end_pack_c':ep,'pack_change_c':pchg,'avg_pack_c':avg_pack,
      'avg_outside_c':avg_out,'min_outside_c':min(vals_out) if vals_out else None,'max_outside_c':max(vals_out) if vals_out else None,
      'start_odometer_km':so,'end_odometer_km':eo,'distance_km':dist,'energy_used_kwh':used,'energy_remaining_delta_kwh':erd,
      'avg_pack_power_kw':_mean([r['pack_power_kw'] for r in seg]),'avg_charge_power_kw':_mean([r['charge_input_kw'] if r['charge_input_kw'] is not None else r['charger_power_kw'] for r in seg]),
      'charge_energy_added_kwh':charge_added,'wh_per_mile':whmi,'metadata_json':json.dumps(meta,separators=(',',':'))
    }

def _keep(e):
    t=e['event_type']; d=e['duration_min'] or 0; dist=e['distance_km'] or 0
    if t=='drive': return dist>=0.2 or d>=2
    if t in {'charge','precondition'}: return d>=3
    if t in {'cold_soak','sleep','park'}: return d>=30
    return d>=5

def rebuild_events(days:int|None=None):
    db.init_db(); days=int(days or config.EVENT_LOOKBACK_DAYS); car=db.latest_car_id()
    if not car:return {'status':'waiting','events':0,'reason':'no telemetry'}
    cutoff=time.time()-days*86400
    with db.connect() as con:
        rows=con.execute('SELECT * FROM telemetry WHERE car_id=? AND ts>=? ORDER BY ts',(car,cutoff)).fetchall()
    if len(rows)<2:return {'status':'waiting','events':0,'reason':'not enough telemetry'}
    segments=[]; current=[]; current_label=None; max_gap=config.EVENT_MAX_GAP_MINUTES*60
    for i,row in enumerate(rows):
        prev=rows[i-1] if i else None; nxt=rows[i+1] if i+1<len(rows) else None
        label=_event_type(classify_regime(row,prev,nxt))
        if current:
            gap=float(row['ts'])-float(current[-1]['ts'])
            if label!=current_label or gap>max_gap:
                if len(current)>=2: segments.append((current_label,current))
                current=[]
        if not current: current_label=label
        current.append(row)
    if len(current)>=2:segments.append((current_label,current))
    events=[]
    for label,seg in segments:
        e=_segment_metric(seg,label)
        if _keep(e):events.append(e)
    fields=['car_id','event_type','start_ts','end_ts','duration_min','source_points','start_soc','end_soc','soc_change','start_pack_c','end_pack_c','pack_change_c','avg_pack_c','avg_outside_c','min_outside_c','max_outside_c','start_odometer_km','end_odometer_km','distance_km','energy_used_kwh','energy_remaining_delta_kwh','avg_pack_power_kw','avg_charge_power_kw','charge_energy_added_kwh','wh_per_mile','metadata_json']
    with db.connect() as con:
        con.execute('DELETE FROM vehicle_events WHERE car_id=? AND start_ts>=?',(car,cutoff))
        for e in events:
            con.execute(f"INSERT OR REPLACE INTO vehicle_events({','.join(fields)}) VALUES({','.join('?' for _ in fields)})",[e.get(f) for f in fields])
    summary=event_summary(days)
    out={'status':'complete','events':len(events),'telemetry_rows':len(rows),'days':days,'finished_at':time.time(),'summary':summary}
    db.set_state('event_engine',out)
    return out

def event_summary(days:int=60):
    cutoff=time.time()-int(days)*86400
    with db.connect() as con:
        rows=con.execute('SELECT * FROM vehicle_events WHERE start_ts>=? ORDER BY start_ts DESC',(cutoff,)).fetchall()
    counts={};
    for r in rows:counts[r['event_type']]=counts.get(r['event_type'],0)+1
    drives=[r for r in rows if r['event_type']=='drive']; charges=[r for r in rows if r['event_type']=='charge']; cold=[r for r in rows if r['event_type']=='cold_soak']; pre=[r for r in rows if r['event_type']=='precondition']
    return {
      'counts':counts,'total':len(rows),
      'drive_distance_mi':round(sum((r['distance_km'] or 0)*0.621371 for r in drives),1),
      'median_drive_wh_mi':None if not drives else _median([r['wh_per_mile'] for r in drives]),
      'median_drive_soc_drop':None if not drives else _median([-(r['soc_change']) for r in drives if r['soc_change'] is not None and r['soc_change']<0]),
      'median_l1_soc_per_hr':_median([(r['soc_change'] or 0)/(r['duration_min']/60) for r in charges if r['duration_min'] and r['duration_min']>=10 and r['soc_change'] is not None and r['soc_change']>0 and (r['avg_charge_power_kw'] or 0)<=2.5]),
      'median_precondition_heat_f_hr':_median([(r['pack_change_c']*1.8)/(r['duration_min']/60) for r in pre if r['duration_min'] and r['duration_min']>=5 and r['pack_change_c'] is not None and r['pack_change_c']>0]),
      'cold_soak_events':len(cold),'precondition_events':len(pre),'charge_events':len(charges),'drive_events':len(drives),
    }

def routine_profile(days:int=45):
    cutoff=time.time()-days*86400
    with db.connect() as con:
        drives=con.execute("SELECT * FROM vehicle_events WHERE event_type='drive' AND start_ts>=? AND distance_km>=5 ORDER BY start_ts",(cutoff,)).fetchall()

    configured_minute=None
    if config.EXPECTED_DEPARTURE and ':' in config.EXPECTED_DEPARTURE:
        try:
            h,m=(int(x) for x in config.EXPECTED_DEPARTURE.split(':',1))
            if 0<=h<24 and 0<=m<60: configured_minute=h*60+m
        except Exception:
            configured_minute=None

    learned_minute=None
    learned_confidence=0
    learned_status={}
    if config.DEPARTURE_LEARNING_ENABLED:
        try:
            from .departure_learning import schedule_status
            learned_status=schedule_status(refresh=True)
            if learned_status.get('routine_minute') is not None:
                learned_minute=int(learned_status['routine_minute'])
            learned_confidence=int(learned_status.get('confidence') or 0)
        except Exception:
            learned_status={}

    # The learned first-drive morning cluster replaces the old hard-coded override
    # as evidence accumulates. The 06:00 value remains only as the cold-start seed.
    if learned_minute is not None and int(learned_status.get('routine_samples') or 0) >= 3:
        commute_minute=learned_minute
        selection_mode='learned-window'
    elif configured_minute is not None:
        commute_minute=configured_minute
        selection_mode='anchor-window'
    else:
        commute_minute=None
        selection_mode='first-drive'

    byday={}
    if commute_minute is not None:
        window=int(config.EXPECTED_DEPARTURE_WINDOW_MINUTES)
        for r in drives:
            lt=time.localtime(float(r['start_ts']))
            if lt.tm_wday>=5:
                continue
            minute=lt.tm_hour*60+lt.tm_min
            delta=abs(minute-commute_minute)
            delta=min(delta,1440-delta)
            key=time.strftime('%Y-%m-%d',lt)
            if delta<=window:
                prev=byday.get(key)
                if prev is None or delta<prev[0]:
                    byday[key]=(delta,r)
        sample=[v[1] for _,v in sorted(byday.items())]
    else:
        for r in drives:
            key=time.strftime('%Y-%m-%d',time.localtime(float(r['start_ts'])))
            byday.setdefault(key,r)
        first=list(byday.values())
        work=[r for r in first if time.localtime(float(r['start_ts'])).tm_wday<5]
        sample=work if len(work)>=5 else first

    if not sample:
        return {'status':'learning','samples':0,'selection_mode':selection_mode,
                'configured_departure_text':config.EXPECTED_DEPARTURE or None,
                'schedule_confidence':learned_confidence,
                'learned_departure_text':learned_status.get('routine_text')}
    mins=[time.localtime(float(r['start_ts'])).tm_hour*60+time.localtime(float(r['start_ts'])).tm_min for r in sample]
    dep=int(round(statistics.median(mins))); mad=statistics.median([min(abs(x-dep),1440-abs(x-dep)) for x in mins]) if mins else None
    dists=[r['distance_km']*0.621371 for r in sample if r['distance_km'] is not None]
    drops=[-r['soc_change'] for r in sample if r['soc_change'] is not None and r['soc_change']<0]
    whmi=[r['wh_per_mile'] for r in sample if r['wh_per_mile'] is not None and 50<r['wh_per_mile']<1000]
    return {'status':'learned','samples':len(sample),'selection_mode':selection_mode,
            'configured_departure_text':config.EXPECTED_DEPARTURE or None,
            'learned_departure_text':learned_status.get('routine_text'),
            'schedule_confidence':learned_confidence,
            'departure_minute':dep,'departure_text':f'{dep//60:02d}:{dep%60:02d}',
            'departure_mad_min':round(float(mad or 0),1),'distance_mi':None if not dists else round(statistics.median(dists),1),
            'soc_drop':None if not drops else round(statistics.median(drops),2),'wh_per_mile':None if not whmi else round(statistics.median(whmi),1)}

def learned_dynamics(days:int=60):
    cutoff=time.time()-days*86400
    with db.connect() as con:
        rows=con.execute('SELECT * FROM vehicle_events WHERE start_ts>=? ORDER BY start_ts',(cutoff,)).fetchall()
    cold=[r for r in rows if r['event_type']=='cold_soak']; pre=[r for r in rows if r['event_type']=='precondition']; charges=[r for r in rows if r['event_type']=='charge']; park=[r for r in rows if r['event_type'] in {'park','sleep','cold_soak'}]
    ks=[]; cool=[]
    for r in cold:
        h=(r['duration_min'] or 0)/60
        s=_f(r['start_pack_c']); e=_f(r['end_pack_c']); a=_f(r['avg_outside_c'])
        if h>0.5 and s is not None and e is not None and a is not None and s-a>1 and e-a>0.3:
            ratio=(e-a)/(s-a)
            if 0<ratio<1.2:
                k=-math.log(ratio)/h
                if 0<k<2:ks.append(k)
        if h>0.5 and r['pack_change_c'] is not None:cool.append(r['pack_change_c']*1.8/h)
    charge_rates=[r['soc_change']/((r['duration_min'] or 1)/60) for r in charges if r['soc_change'] is not None and r['soc_change']>0 and (r['duration_min'] or 0)>=10 and (r['avg_charge_power_kw'] or 0)<=2.5]
    pre_heat=[r['pack_change_c']*1.8/((r['duration_min'] or 1)/60) for r in pre if r['pack_change_c'] is not None and r['pack_change_c']>0 and (r['duration_min'] or 0)>=5]
    standby=[-r['soc_change']/((r['duration_min'] or 1)/60) for r in park if r['soc_change'] is not None and r['soc_change']<0 and (r['duration_min'] or 0)>=60]
    pre_soc=[-r['soc_change']/((r['duration_min'] or 1)/60) for r in pre if r['soc_change'] is not None and r['soc_change']<0 and (r['duration_min'] or 0)>=5]
    return {'cold_soak_k_per_hr':_median(ks),'cold_pack_delta_f_hr':_median(cool),'cold_samples':len(ks),
            'l1_soc_pct_hr':_median(charge_rates),'l1_samples':len(charge_rates),
            'precondition_heat_f_hr':_median(pre_heat),'precondition_samples':len(pre_heat),
            'precondition_soc_pct_hr':_median(pre_soc),'standby_soc_pct_hr':_median(standby),'standby_samples':len(standby)}

def recent_events(limit:int=80):
    with db.connect() as con:
        rows=con.execute('SELECT * FROM vehicle_events ORDER BY start_ts DESC LIMIT ?',(max(1,min(int(limit),250)),)).fetchall()
    out=[]
    for r in rows:
        d=dict(r); d['vin_tail']=str(d.pop('car_id',''))[-6:]
        if d.get('metadata_json'):
            try:d['metadata']=json.loads(d.pop('metadata_json'))
            except Exception:d.pop('metadata_json',None)
        out.append(d)
    return out

from __future__ import annotations

import json, math, statistics, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from . import config, db
from .predict import current_predictions
from .readiness import current_readiness
from .event_engine import learned_dynamics, recent_events


def _f(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except Exception: return None


def _c2f(c): return None if c is None else c*9/5+32

def _f2c(f): return None if f is None else (f-32)*5/9

def _clamp(x,a,b): return max(a,min(b,x))


def _raw(root):
    try:
        j=json.loads(root or '{}')
        return j if isinstance(j,dict) else {}
    except Exception:return {}


def _gps(raw_json):
    j=_raw(raw_json)
    roots=[j, j.get('state',{}) if isinstance(j,dict) else {}]
    for root in roots:
        if not isinstance(root,dict):continue
        d=root.get('drive_state',{})
        if not isinstance(d,dict):continue
        lat=_f(d.get('latitude') or d.get('native_latitude')); lon=_f(d.get('longitude') or d.get('native_longitude'))
        if lat is not None and lon is not None:return lat,lon
    return None,None


def _cabin_target_f(raw_json):
    j=_raw(raw_json)
    roots=[j,j.get('state',{}) if isinstance(j,dict) else {}]
    for root in roots:
        if not isinstance(root,dict):continue
        c=root.get('climate_state',{})
        if not isinstance(c,dict):continue
        for k in ('driver_temp_setting','passenger_temp_setting'):
            if c.get(k) is not None:
                v=_f(c[k])
                if v is not None:return round(_c2f(v),1)
    return None


def _weather(lat,lon,now):
    """Optional cloud weather source. No coordinates are returned to the browser."""
    enabled=config.get_bool('WEATHER_ENABLED',True)
    cache_mins=max(5,config.get_int('WEATHER_CACHE_MINUTES',30))
    cached=db.get_state('winter_weather',{}) or {}
    if cached and now-float(cached.get('fetched_at',0)) < cache_mins*60:
        return cached
    if not enabled or lat is None or lon is None:
        out=cached if cached.get('hours') else {'status':'disabled','source':'ambient fallback','fetched_at':now,'hours':[]}
        if not cached.get('hours'): db.set_state('winter_weather',out)
        return out
    try:
        q=urllib.parse.urlencode({
            'latitude':round(lat,4),'longitude':round(lon,4),
            'hourly':'temperature_2m','temperature_unit':'fahrenheit',
            'forecast_days':2,'timeformat':'unixtime','timezone':'auto'
        })
        url='https://api.open-meteo.com/v1/forecast?'+q
        req=urllib.request.Request(url,headers={'User-Agent':'GHOST-Tesla-AI/0.3.4'})
        with urllib.request.urlopen(req,timeout=8) as r:
            payload=json.loads(r.read().decode('utf-8'))
        times=payload.get('hourly',{}).get('time',[]) or []
        temps=payload.get('hourly',{}).get('temperature_2m',[]) or []
        hours=[]
        for ts,t in zip(times,temps):
            try:
                ts=float(ts); t=float(t)
            except Exception:continue
            if ts >= now-3600 and ts <= now+48*3600:hours.append({'ts':ts,'temp_f':round(t,1)})
        out={'status':'ready','source':'Open-Meteo hourly','fetched_at':now,'hours':hours}
        db.set_state('winter_weather',out)
        return out
    except Exception as e:
        if cached.get('hours'):
            cached=dict(cached); cached['status']='cached'; cached['error']=f'{type(e).__name__}: {e}'; cached['fetched_at']=now; db.set_state('winter_weather',cached); return cached
        out={'status':'error','source':'ambient fallback','fetched_at':now,'error':f'{type(e).__name__}: {e}','hours':[]}
        db.set_state('winter_weather',out); return out


def _nearest_weather(hours,target,current_f):
    if not hours:return current_f
    row=min(hours,key=lambda r:abs(float(r['ts'])-target))
    return _f(row.get('temp_f')) if _f(row.get('temp_f')) is not None else current_f


def _retention_k(days=60):
    cutoff=time.time()-days*86400; ks=[]
    with db.connect() as con:
        rows=con.execute('''SELECT duration_min,start_pack_c,end_pack_c,avg_outside_c,event_type
                            FROM vehicle_events WHERE start_ts>=? AND event_type IN ('park','sleep','cold_soak')''',(cutoff,)).fetchall()
    for r in rows:
        h=(_f(r['duration_min']) or 0)/60; s=_f(r['start_pack_c']); e=_f(r['end_pack_c']); a=_f(r['avg_outside_c'])
        if h<0.5 or s is None or e is None or a is None or s-a<=0.8 or e-a<=0.15:continue
        ratio=(e-a)/(s-a)
        if 0.03<ratio<1.15:
            k=-math.log(ratio)/h
            if 0.002<k<1.5:ks.append(k)
    return (statistics.median(ks) if ks else None),len(ks)


def _physics_series(pack_f,outside_now_f,weather_hours,now,k,hours=12):
    if pack_f is None:return []
    if k is None or k<=0:return []
    t=pack_f; out=[]
    for h in range(1,hours+1):
        ts=now+h*3600; amb=_nearest_weather(weather_hours,ts,outside_now_f)
        if amb is None:amb=outside_now_f if outside_now_f is not None else t
        t_c=_f2c(t); a_c=_f2c(amb)
        t_c=a_c+(t_c-a_c)*math.exp(-k)
        t=_c2f(t_c)
        out.append({'hours':h,'ts':ts,'outside_f':round(amb,1),'pack_f':round(t,1),'source':'learned thermal retention'})
    return out


def _model_prediction(name):
    for p in current_predictions():
        if p.get('model')==name and not p.get('error'):
            val=_f(p.get('value')); mae=_f(p.get('mae'))
            return {'value_f':None if val is None else round(_c2f(val),1),'mae_f':None if mae is None else round(mae*1.8,2),'generation':p.get('generation')}
    return None


def _forecast_card(hours,now,current_outside,weather,physics,model=None):
    target=now+hours*3600; outside=_nearest_weather(weather.get('hours',[]),target,current_outside)
    phys=next((x for x in physics if x['hours']==hours),None)
    pack=None; source='learning'; mae=None
    if model and model.get('value_f') is not None:
        pack=model['value_f']; source=f"Pack Thermal AI Gen {model.get('generation','?')}"; mae=model.get('mae_f')
    elif phys:
        pack=phys['pack_f']; source=phys['source']
    margin=None if pack is None or outside is None else round(pack-outside,1)
    uncertainty=None
    if mae is not None:uncertainty=max(2.0,round(mae*1.5,1))
    elif pack is not None:uncertainty=4.0
    rng=None if pack is None or uncertainty is None else [round(pack-uncertainty,1),round(pack+uncertainty,1)]
    return {'hours':hours,'target_ts':target,'pack_f':pack,'outside_f':None if outside is None else round(outside,1),'margin_f':margin,'range_f':rng,'source':source}


def _thermal_history(car_id,now):
    with db.connect() as con:
        rows=con.execute('''SELECT ts,battery_temp_c,inside_temp_c,outside_temp_c FROM telemetry
                            WHERE car_id=? AND ts>=? ORDER BY ts''',(car_id,now-24*3600)).fetchall()
    if not rows:return []
    step=max(1,math.ceil(len(rows)/240)); sample=list(rows[::step])
    if sample[-1]['ts']!=rows[-1]['ts']:sample.append(rows[-1])
    return [{'ts':float(r['ts']),'pack_f':_c2f(_f(r['battery_temp_c'])),'cabin_f':_c2f(_f(r['inside_temp_c'])),'outside_f':_c2f(_f(r['outside_temp_c']))} for r in sample]



def _live_warmup(car_id, latest, now):
    """Small, transparent live warm-up summary from recent raw telemetry."""
    latest_ts=_f(latest['ts']) or now
    current_pack_c=_f(latest['battery_temp_c'])
    active=bool(latest['battery_heater_on']) or bool(latest['preconditioning'])

    with db.connect() as con:
        rows=con.execute(
            """SELECT ts,battery_temp_c,battery_heater_on,preconditioning,charge_input_kw,pack_power_kw
               FROM telemetry
               WHERE car_id=? AND ts>=? AND ts<=?
               ORDER BY ts""",
            (car_id,latest_ts-2*3600,latest_ts)
        ).fetchall()
        old20=con.execute(
            """SELECT ts,battery_temp_c FROM telemetry
               WHERE car_id=? AND ts<=? AND battery_temp_c IS NOT NULL
               ORDER BY ts DESC LIMIT 1""",
            (car_id,latest_ts-20*60)
        ).fetchone()

    move20=None
    rate=None
    sample_minutes=None
    if old20 and current_pack_c is not None and old20['battery_temp_c'] is not None:
        old_ts=_f(old20['ts'])
        old_pack_c=_f(old20['battery_temp_c'])
        if old_ts is not None and old_pack_c is not None:
            mins=max(0.0,(latest_ts-old_ts)/60.0)
            if 5 <= mins <= 45:
                move20=(current_pack_c-old_pack_c)*1.8
                sample_minutes=mins
                rate=move20/(mins/60.0)

    started_at=None
    elapsed_sec=None
    start_pack_f=None
    if active and rows:
        active_rows=[]
        prev_ts=latest_ts
        for r in reversed(rows):
            ts=_f(r['ts'])
            if ts is None:
                continue
            row_active=bool(r['battery_heater_on']) or bool(r['preconditioning'])
            if not row_active or prev_ts-ts > 10*60:
                break
            active_rows.append(r)
            prev_ts=ts
        if active_rows:
            first=active_rows[-1]
            started_at=_f(first['ts'])
            elapsed_sec=None if started_at is None else max(0.0,latest_ts-started_at)
            start_pack_f=_c2f(_f(first['battery_temp_c']))

    return {
        'active':active,
        'started_at':started_at,
        'elapsed_sec':elapsed_sec,
        'start_pack_f':start_pack_f,
        'pack_f':_c2f(current_pack_c),
        'move_20m_f':None if move20 is None else round(move20,1),
        'heat_rate_f_per_hr':None if rate is None else round(rate,1),
        'rate_window_min':None if sample_minutes is None else round(sample_minutes,1),
        'wall_kw':_f(latest['charge_input_kw']),
        'pack_kw':_f(latest['pack_power_kw']),
    }

def _timeline(now):
    events=recent_events(40); out=[]
    for e in events:
        if float(e.get('end_ts') or 0) < now-36*3600:continue
        typ=e.get('event_type'); pc=_f(e.get('pack_change_c')); sc=_f(e.get('soc_change')); dur=_f(e.get('duration_min'))
        if typ=='charge':
            text=f"Level 1 charging session: {sc:+.1f}% SOC" if sc is not None else 'Level 1 charging session recorded.'
            kind='charge'
        elif typ=='drive':
            mi=_f(e.get('distance_km')); mi=None if mi is None else mi*.621371
            text=f"Drive completed: {mi:.1f} mi" if mi is not None else 'Drive completed.'; kind='drive'
        elif pc is not None and abs(pc*1.8)>=2:
            text=f"Pack temperature moved {pc*1.8:+.1f}°F over {dur:.0f} min" if dur is not None else f"Pack temperature moved {pc*1.8:+.1f}°F"
            kind='thermal'
        else:continue
        out.append({'ts':float(e.get('end_ts') or e.get('start_ts')),'type':kind,'text':text})
        if len(out)>=10:break
    return out


def build_winter_board(now=None):
    now=float(now or time.time()); db.init_db()
    with db.connect() as con:
        latest=con.execute('SELECT * FROM telemetry ORDER BY ts DESC LIMIT 1').fetchone()
    if not latest:return {'status':'WAITING','score':0,'generated_at':now,'forecast':[],'message':'Waiting for Tesla telemetry.'}

    ready=current_readiness(now); dyn=learned_dynamics(); raw=latest['raw_json']; lat,lon=_gps(raw)
    weather=_weather(lat,lon,now)
    cur_pack=_c2f(_f(latest['battery_temp_c'])); cur_out=_c2f(_f(latest['outside_temp_c'])); cur_cabin=_c2f(_f(latest['inside_temp_c']))
    k,nk=_retention_k(); physics=_physics_series(cur_pack,cur_out,weather.get('hours',[]),now,k,12)
    m1=_model_prediction('pack_temp_60m'); m3=_model_prediction('pack_temp_180m')
    f1=_forecast_card(1,now,cur_out,weather,physics,m1)
    f3=_forecast_card(3,now,cur_out,weather,physics,m3)
    f6=_forecast_card(6,now,cur_out,weather,physics,None)
    all_future=[]
    for h in range(1,13):
        model=m1 if h==1 else m3 if h==3 else None
        all_future.append(_forecast_card(h,now,cur_out,weather,physics,model))
    valid=[x for x in all_future if x.get('pack_f') is not None]
    cold=min(valid,key=lambda x:x['pack_f']) if valid else {'target_ts':None,'pack_f':None,'outside_f':None,'margin_f':None,'range_f':None,'source':'learning'}

    min_pack=min([x['pack_f'] for x in valid],default=cur_pack if cur_pack is not None else 32)
    thermal_score=100 if min_pack>=50 else _clamp((min_pack-20)/(50-20)*100,0,100)
    arrival=_f(ready.get('predicted_arrival_soc'))
    soc_score=50 if arrival is None else _clamp((arrival-10)/(30-10)*100,0,100)
    dep_soc=_f(ready.get('predicted_departure_soc')); target=_f(ready.get('charge_target_soc')) or 80
    charge_score=70 if dep_soc is None else _clamp((dep_soc-(target-15))/15*100,0,100)
    evidence=_f(ready.get('confidence')) or 0

    # Transparent readiness accounting. Each component contributes a fixed
    # portion of the 100-point operational score, and the dashboard can show
    # the exact deductions instead of presenting an unexplained number.
    score_parts=[
        {
            'key':'thermal','label':'Thermal margin','weight':45.0,'raw_score':thermal_score,
            'reason':(
                f"Coolest projected pack {min_pack:.1f}°F is at or above the 50°F full-score threshold."
                if min_pack>=50 else
                f"Coolest projected pack {min_pack:.1f}°F is below the 50°F full-score threshold."
            )
        },
        {
            'key':'arrival_soc','label':'Arrival SOC margin','weight':35.0,'raw_score':soc_score,
            'reason':(
                'Projected arrival SOC is not available yet, so this component is held at 50%.'
                if arrival is None else
                (f"Projected arrival SOC {arrival:.0f}% is at or above the 30% full-score threshold."
                 if arrival>=30 else
                 f"Projected arrival SOC {arrival:.0f}% is below the 30% full-score threshold.")
            )
        },
        {
            'key':'departure_charge','label':'Departure charge','weight':10.0,'raw_score':charge_score,
            'reason':(
                'Departure SOC is not available yet, so this component is held at 70%.'
                if dep_soc is None else
                (f"Projected departure SOC {dep_soc:.0f}% meets the {target:.0f}% charge target."
                 if dep_soc>=target else
                 f"Projected departure SOC {dep_soc:.0f}% is below the {target:.0f}% charge target.")
            )
        },
        {
            'key':'evidence','label':'Evidence confidence','weight':10.0,'raw_score':_clamp(evidence,0,100),
            'reason':(
                f"Overall readiness evidence confidence is {evidence:.0f}%. This combines commute, thermal and charging evidence; it is separate from departure-schedule confidence."
            )
        },
    ]
    for part in score_parts:
        part['points']=round(part['weight']*part['raw_score']/100.0,2)
        part['penalty']=round(part['weight']-part['points'],2)
    score_unrounded=_clamp(sum(x['points'] for x in score_parts),0,100)
    score=int(round(score_unrounded))
    score_breakdown={
        'max_score':100.0,
        'score_unrounded':round(score_unrounded,2),
        'total_penalty':round(100.0-score_unrounded,2),
        'components':score_parts,
        'active_penalties':[x for x in score_parts if x['penalty']>=0.05],
    }
    if score>=90:headline='WINTER READY NOW'; state='READY'
    elif score>=75:headline='WINTER READY'; state='READY'
    elif score>=55:headline='WINTER WATCH'; state='WATCH'
    else:headline='ACTION RECOMMENDED'; state='ACTION'

    target_pack=float(config.READINESS_TARGET_PACK_F)
    dep_pack=_f(ready.get('predicted_departure_pack_f'))
    heater=bool(latest['battery_heater_on']) if latest['battery_heater_on'] is not None else False
    if heater:action='Battery heater is active.'
    elif ready.get('suggested_precondition_start_ts'):action=f"Warm-up recommended near {time.strftime('%-I:%M %p',time.localtime(ready['suggested_precondition_start_ts']))}."
    elif dep_pack is not None and dep_pack>=target_pack:action='No battery warm-up is needed.'
    elif min_pack>=target_pack:action='No battery warm-up is expected to be needed.'
    else:action='Pack may be below the preferred warm target; continue monitoring.'

    # 30-minute movement / trend
    with db.connect() as con:
        old=con.execute('SELECT battery_temp_c,inside_temp_c FROM telemetry WHERE car_id=? AND ts<=? ORDER BY ts DESC LIMIT 1',(latest['car_id'],now-1800)).fetchone()
    pack_move=None if not old or cur_pack is None or old['battery_temp_c'] is None else round(cur_pack-_c2f(float(old['battery_temp_c'])),1)
    mn=_c2f(_f(latest['module_temp_min_c'])); mx=_c2f(_f(latest['module_temp_max_c'])); spread=None if mn is None or mx is None else round(mx-mn,1)
    wall_kw=_f(latest['charge_input_kw']); pack_kw=_f(latest['pack_power_kw'])
    nonpack=None if wall_kw is None or pack_kw is None else max(0.0,wall_kw-max(0.0,pack_kw))
    pack_share=None if wall_kw is None or wall_kw<=.05 or pack_kw is None else _clamp(max(0,pack_kw)/wall_kw*100,0,100)
    target_cabin=_cabin_target_f(raw)
    forecast_low=min([x['temp_f'] for x in weather.get('hours',[]) if x['ts']<=now+18*3600],default=cur_out if cur_out is not None else 99)
    season='WINTER CONDITIONS' if forecast_low<32 else 'COLD-WEATHER WATCH' if forecast_low<45 else 'MILD-WEATHER THERMAL WATCH'

    confidence='HIGH' if weather.get('status')=='ready' and m1 and m3 and nk>=5 else 'MEDIUM' if (m1 or nk>=3) else 'LOW'

    # v0.8.27.4 HUMAN-READINESS-V08274
    # Human-facing explanation layer. Only score_penalty values remove points;
    # the larger check grid is context so cold air, trend, data age, etc. can be
    # visible without pretending every condition changes the Winter Score.
    diagnostics=[]
    def _diag(key,label,state,severity,detail,value=None,score_penalty=0.0,score_source=None):
        diagnostics.append({
            'key':key,'label':label,'state':state,'severity':severity,'detail':detail,
            'value':value,'score_penalty':round(max(0.0,float(score_penalty or 0.0)),2),
            'score_source':score_source,
        })

    parts_by_key={x.get('key'):x for x in score_parts}
    therm_pen=float((parts_by_key.get('thermal') or {}).get('penalty') or 0.0)
    arrival_pen=float((parts_by_key.get('arrival_soc') or {}).get('penalty') or 0.0)
    charge_pen=float((parts_by_key.get('departure_charge') or {}).get('penalty') or 0.0)
    evidence_pen=float((parts_by_key.get('evidence') or {}).get('penalty') or 0.0)

    if therm_pen >= .05:
        if min_pack < 32: lab='PACK FREEZING RISK'; sev='bad'
        elif min_pack < 40: lab='PACK TOO COLD'; sev='bad'
        else: lab='PACK BELOW READY TEMP'; sev='warn'
        _diag('score_pack_temp',lab,'PENALTY',sev,
              f'Coldest projected pack is {min_pack:.1f}°F. Full thermal credit starts at 50°F.',
              f'{min_pack:.1f}°F',therm_pen,'thermal')
    if arrival_pen >= .05:
        if arrival is None:
            _diag('score_arrival','ARRIVAL RESERVE UNKNOWN','PENALTY','warn',
                  'GHOST does not have a reliable arrival-SOC estimate yet.','LEARNING',arrival_pen,'arrival_soc')
        else:
            lab='ARRIVAL RESERVE LOW' if arrival < 20 else 'ARRIVAL RESERVE THIN'
            _diag('score_arrival',lab,'PENALTY','bad' if arrival < 20 else 'warn',
                  f'Projected arrival is {arrival:.0f}% SOC. Full reserve credit starts at 30%.',
                  f'{arrival:.0f}%',arrival_pen,'arrival_soc')
    if charge_pen >= .05:
        if dep_soc is None:
            _diag('score_departure_charge','DEPARTURE CHARGE UNKNOWN','PENALTY','warn',
                  'Departure SOC is still learning, so GHOST cannot give full charge credit.','LEARNING',charge_pen,'departure_charge')
        else:
            lab='DEPARTURE SOC LOW' if dep_soc < target-10 else 'DEPARTURE SOC BELOW TARGET'
            _diag('score_departure_charge',lab,'PENALTY','bad' if dep_soc < target-10 else 'warn',
                  f'Projected departure is {dep_soc:.0f}% versus the {target:.0f}% target.',
                  f'{dep_soc:.0f}% / {target:.0f}%',charge_pen,'departure_charge')

    routine=ready.get('routine') or {}
    rdyn=ready.get('dynamics') or {}
    schedule=ready.get('departure_learning') or {}
    commute_samples=int(routine.get('samples') or 0)
    cold_samples=int(rdyn.get('cold_samples') or 0)
    l1_samples=int(rdyn.get('l1_samples') or 0)
    schedule_conf=_f(schedule.get('confidence')) if schedule else None
    evidence_sources=[]
    if commute_samples:
        evidence_sources.append(('commute','COMMUTE MEMORY THIN',min(100.0,commute_samples/15.0*100.0),commute_samples,15,'first-drive events'))
    if cold_samples:
        evidence_sources.append(('cold','COLD-SOAK MEMORY THIN',min(100.0,cold_samples/15.0*100.0),cold_samples,15,'cold-soak events'))
    if l1_samples:
        evidence_sources.append(('charge','L1 CHARGE MEMORY THIN',min(100.0,l1_samples/10.0*100.0),l1_samples,10,'charging events'))
    base_conf=(sum(x[2] for x in evidence_sources)/len(evidence_sources)) if evidence_sources else 10.0
    if schedule_conf is not None:
        uncapped_conf=round(base_conf*.65 + schedule_conf*.35); base_weight=6.5; schedule_weight=3.5
    else:
        uncapped_conf=round(base_conf); base_weight=10.0; schedule_weight=0.0
    raw_hits=[]
    if evidence_sources:
        per_weight=base_weight/len(evidence_sources)
        for key,label,pct,have,need,noun in evidence_sources:
            hit=per_weight*(1.0-pct/100.0)
            if hit>.0001:
                raw_hits.append((key,label,hit,f'GHOST has {have} {noun}; full evidence credit is reached at {need}.',f'{have} / {need}'))
    elif base_weight>0:
        raw_hits.append(('history','READINESS HISTORY TOO THIN',base_weight*.90,'GHOST has not built enough commute, cold-soak or charging memory yet.','LEARNING'))
    if schedule_weight>0 and schedule_conf is not None:
        hit=schedule_weight*(1.0-_clamp(schedule_conf,0,100)/100.0)
        if hit>.0001:
            raw_hits.append(('schedule','DEPARTURE PATTERN STILL LEARNING',hit,
                             f'The learned departure schedule is {schedule_conf:.0f}% confident; more observed departures will tighten it.',f'{schedule_conf:.0f}%'))
    cold_threshold_f=_c2f(float(config.COLD_SOAK_THRESHOLD_C))
    if cur_out is not None and cur_out <= cold_threshold_f and cold_samples < 3 and uncapped_conf > 35:
        raw_hits.append(('cold_cap','COLD-WEATHER EVIDENCE CAP',(uncapped_conf-35)/10.0,
                         f'Outside air is {cur_out:.1f}°F but GHOST only has {cold_samples} cold-soak events, so confidence is capped for safety.',f'{cold_samples} cold events'))
    raw_total=sum(x[2] for x in raw_hits)
    scale=(evidence_pen/raw_total) if evidence_pen>.0001 and raw_total>.0001 else 0.0
    if evidence_pen>=.05:
        if raw_hits:
            for key,label,hit,detail,value in raw_hits:
                pts=hit*scale
                if pts>=.025:_diag('score_evidence_'+key,label,'PENALTY','warn',detail,value,pts,'evidence')
        else:
            _diag('score_evidence','READINESS EVIDENCE STILL LEARNING','PENALTY','warn',
                  f'Overall GHOST readiness evidence is {evidence:.0f}%; more observed operation will close the gap.',f'{evidence:.0f}%',evidence_pen,'evidence')

    # Broad live readiness checks. These do not deduct points unless a matching
    # active score card above explicitly shows a point value.
    if min_pack < 32:_diag('pack_forecast','PACK FORECAST','FREEZING','bad',f'Coldest projected pack is {min_pack:.1f}°F.',f'{min_pack:.1f}°F')
    elif min_pack < 50:_diag('pack_forecast','PACK FORECAST','COLD','warn','Coldest projected pack is below the 50°F ready threshold.',f'{min_pack:.1f}°F')
    else:_diag('pack_forecast','PACK FORECAST','READY','good','Projected pack temperature stays in the full-credit range.',f'{min_pack:.1f}°F')

    if forecast_low < 20:_diag('outside_air','OUTSIDE AIR','VERY COLD','bad','Deep-winter outside air increases cold-soak exposure.',f'{forecast_low:.1f}°F')
    elif forecast_low < 32:_diag('outside_air','OUTSIDE AIR','BELOW FREEZING','warn','Forecast air drops below freezing; pack retention matters more.',f'{forecast_low:.1f}°F')
    elif forecast_low < 45:_diag('outside_air','OUTSIDE AIR','COLD WATCH','info','Cool air is being included in the thermal plan.',f'{forecast_low:.1f}°F')
    else:_diag('outside_air','OUTSIDE AIR','MILD','good','No strong cold-air stress in the current forecast.',f'{forecast_low:.1f}°F')

    dep_pack_val=_f(ready.get('predicted_departure_pack_f'))
    if dep_pack_val is None:_diag('departure_pack','PACK AT DEPARTURE','LEARNING','info','Departure pack temperature is not stable enough to call yet.','—')
    elif dep_pack_val < 32:_diag('departure_pack','PACK AT DEPARTURE','TOO COLD','bad','Predicted pack temperature at departure is below freezing.',f'{dep_pack_val:.1f}°F')
    elif dep_pack_val < target_pack:_diag('departure_pack','PACK AT DEPARTURE','WARM-UP RANGE','warn',f'Predicted pack is below the {target_pack:.0f}°F preferred target.',f'{dep_pack_val:.1f}°F')
    else:_diag('departure_pack','PACK AT DEPARTURE','READY','good','Predicted departure pack meets the preferred warm target.',f'{dep_pack_val:.1f}°F')

    if arrival is None:_diag('arrival_reserve','ARRIVAL RESERVE','LEARNING','info','Trip-energy learning has not produced a stable arrival SOC yet.','—')
    elif arrival < 20:_diag('arrival_reserve','ARRIVAL RESERVE','LOW','bad','Projected arrival reserve is low.',f'{arrival:.0f}%')
    elif arrival < 30:_diag('arrival_reserve','ARRIVAL RESERVE','THIN','warn','Projected arrival is below the full-credit reserve.',f'{arrival:.0f}%')
    else:_diag('arrival_reserve','ARRIVAL RESERVE','HEALTHY','good','Projected arrival retains a healthy SOC reserve.',f'{arrival:.0f}%')

    if dep_soc is None:_diag('departure_soc','DEPARTURE CHARGE','LEARNING','info','GHOST is still learning departure SOC.','—')
    elif dep_soc+0.5 < target:_diag('departure_soc','DEPARTURE CHARGE','BELOW TARGET','warn',f'Predicted departure charge is below the {target:.0f}% target.',f'{dep_soc:.0f}%')
    else:_diag('departure_soc','DEPARTURE CHARGE','ON TARGET','good','Predicted departure charge meets the configured target.',f'{dep_soc:.0f}%')

    next_prob=_f(ready.get('departure_probability'))
    if schedule_conf is None:_diag('schedule','DEPARTURE PATTERN','LEARNING','info','GHOST is separating routine departures from random trips.','—')
    elif schedule_conf < 60:_diag('schedule','DEPARTURE PATTERN','LEARNING','warn','Observed departure timing is still variable.',f'{schedule_conf:.0f}% learned')
    else:_diag('schedule','DEPARTURE PATTERN','LEARNED','good','Routine timing is strongly learned; random trips remain allowed.',f'{schedule_conf:.0f}% learned')
    if next_prob is not None:
        p=next_prob*100.0; st='LIKELY' if p>=65 else 'POSSIBLE' if p>=40 else 'LOW CONFIDENCE'
        _diag('next_trip','NEXT TRIP WINDOW',st,'good' if p>=65 else 'info','This is the next-window probability, not overall schedule quality.',f'{p:.0f}%')

    _diag('commute_memory','COMMUTE MEMORY','READY' if commute_samples>=15 else 'BUILDING','good' if commute_samples>=15 else 'info','First-drive history teaches normal trip SOC use and timing.',f'{commute_samples} events')
    _diag('cold_memory','COLD-SOAK MEMORY','READY' if cold_samples>=15 else 'BUILDING','good' if cold_samples>=15 else 'info','Parked cold-weather history teaches how quickly the pack follows outside air.',f'{cold_samples} events')
    _diag('charge_memory','L1 CHARGE MEMORY','READY' if l1_samples>=10 else 'BUILDING','good' if l1_samples>=10 else 'info','Charging history teaches overnight SOC gain and charge timing.',f'{l1_samples} events')

    if weather.get('status')=='ready':_diag('weather','FORECAST LINK','LIVE','good','Hourly outside-air forecast is available.',str(weather.get('source') or 'weather'))
    elif weather.get('hours'):_diag('weather','FORECAST LINK','CACHED','warn','GHOST is using a cached forecast until refresh.','CACHED')
    else:_diag('weather','FORECAST LINK','FALLBACK','warn','No hourly forecast; current outside air is the fallback.','AMBIENT')

    if m1 and m3:_diag('thermal_ai','PACK THERMAL AI','ONLINE','good','Both 1-hour and 3-hour learned pack forecasts are available.','1h + 3h')
    elif m1 or m3:_diag('thermal_ai','PACK THERMAL AI','PARTIAL','info','One neural horizon is available; other horizons use retention physics.','PARTIAL')
    else:_diag('thermal_ai','PACK THERMAL AI','LEARNING','warn','Pack outlook is relying on learned retention physics.','PHYSICS')

    if nk>=5:_diag('retention','THERMAL RETENTION MEMORY','READY','good','Enough parked thermal events exist for the retention model.',f'{nk} events')
    elif nk>=3:_diag('retention','THERMAL RETENTION MEMORY','BUILDING','info','More parked-temperature events will tighten the model.',f'{nk} events')
    else:_diag('retention','THERMAL RETENTION MEMORY','THIN','warn','Very little parked thermal history is available.',f'{nk} events')

    heat_rate=_f(rdyn.get('precondition_heat_f_hr'))
    if heat_rate is not None and heat_rate>0.5:_diag('warmup_memory','WARM-UP LEARNING','READY','good','Observed pack-heating rate can time preconditioning.',f'{heat_rate:.1f}°F/hr')
    elif dep_pack_val is not None and dep_pack_val < target_pack:_diag('warmup_memory','WARM-UP LEARNING','NEEDS DATA','warn','Pack may need heat, but GHOST has not learned a reliable heat rate yet.','LEARNING')
    else:_diag('warmup_memory','WARM-UP LEARNING','STANDBY','info','A learned heat rate is not currently required.','—')

    age_min=max(0.0,(now-(_f(latest['ts']) or now))/60.0)
    if age_min>30:_diag('telemetry','TESLA TELEMETRY','STALE','bad','The newest vehicle sample is too old for strong live context.',f'{age_min:.0f} min old')
    elif age_min>10:_diag('telemetry','TESLA TELEMETRY','AGING','warn','A fresh Tesla sample would improve the live picture.',f'{age_min:.0f} min old')
    else:_diag('telemetry','TESLA TELEMETRY','FRESH','good','Live vehicle context is current.',f'{age_min:.0f} min old')

    if pack_move is None:_diag('pack_trend','PACK TREND','LEARNING','info','Not enough recent history for a 30-minute pack trend.','—')
    elif pack_move <= -5:_diag('pack_trend','PACK TREND','COOLING FAST','bad','Pack temperature has dropped quickly.',f'{pack_move:+.1f}°F / 30m')
    elif pack_move <= -2:_diag('pack_trend','PACK TREND','COOLING','warn','Pack is cooling noticeably.',f'{pack_move:+.1f}°F / 30m')
    elif pack_move >= 2:_diag('pack_trend','PACK TREND','WARMING','good','Pack temperature is rising.',f'{pack_move:+.1f}°F / 30m')
    else:_diag('pack_trend','PACK TREND','STABLE','good','Pack temperature is holding steady.',f'{pack_move:+.1f}°F / 30m')

    if spread is None:_diag('module_balance','MODULE TEMPS','LEARNING','info','Module temperature spread is unavailable.','—')
    elif spread>12:_diag('module_balance','MODULE TEMPS','WIDE SPREAD','bad','Battery modules have a large temperature spread.',f'{spread:.1f}°F spread')
    elif spread>6:_diag('module_balance','MODULE TEMPS','WATCH','warn','Module temperature spread is wider than normal.',f'{spread:.1f}°F spread')
    else:_diag('module_balance','MODULE TEMPS','EVEN','good','Battery module temperatures are closely grouped.',f'{spread:.1f}°F spread')

    dep_ts=_f(ready.get('departure_ts')); charge_target_ts=_f(ready.get('charge_target_ts'))
    if charge_target_ts is not None and dep_ts is not None and charge_target_ts > dep_ts:_diag('charge_deadline','CHARGE DEADLINE','LATE','bad','At the learned rate, target SOC would be reached after departure.',time.strftime('%-I:%M %p',time.localtime(charge_target_ts)))
    elif charge_target_ts is not None and dep_ts is not None:_diag('charge_deadline','CHARGE DEADLINE','ON TIME','good','Target SOC should be reached before departure.',time.strftime('%-I:%M %p',time.localtime(charge_target_ts)))
    elif dep_soc is not None and dep_soc>=target:_diag('charge_deadline','CHARGE DEADLINE','SATISFIED','good','Projected departure SOC already meets the target.','READY')
    else:_diag('charge_deadline','CHARGE DEADLINE','MONITOR','info','No reliable charge-completion deadline is available yet.','—')

    if bool(latest['plugged_in']):
        st='CHARGING' if str(latest['charging_state'] or '').lower()=='charging' else 'PLUGGED IN'
        _diag('power_state','CHARGE CONNECTION',st,'good','The car is connected for overnight energy management.',f'{wall_kw:.2f} kW' if wall_kw is not None else st)
    elif dep_soc is not None and dep_soc < target:_diag('power_state','CHARGE CONNECTION','UNPLUGGED','warn','Departure SOC is below target and the vehicle is not plugged in.','UNPLUGGED')
    else:_diag('power_state','CHARGE CONNECTION','UNPLUGGED','info','Vehicle is not plugged in; departure charge still looks acceptable.','UNPLUGGED')

    active_human=[x for x in diagnostics if float(x.get('score_penalty') or 0)>=.025]
    score_breakdown['human_penalties']=active_human
    score_breakdown['human_checks']=diagnostics
    score_breakdown['human_penalty_total']=round(sum(float(x['score_penalty']) for x in active_human),2)
    score_breakdown['human_note']='Only cards marked PENALTY remove Winter Score points. WATCH / LEARNING / COLD cards are context unless a point value is shown.'

    live_warmup=_live_warmup(latest['car_id'],latest,now)
    return {
        'generated_at':now,'headline':headline,'state':state,'score':score,'score_breakdown':score_breakdown,'confidence_label':confidence,'action':action,
        'current':{'soc':_f(latest['battery_level']),'pack_f':cur_pack,'outside_f':cur_out,'cabin_f':cur_cabin,'cabin_target_f':target_cabin,
                   'heater_on':heater,'preconditioning':bool(latest['preconditioning']),'climate_on':bool(latest['climate_on']),
                   'charging_state':latest['charging_state'],'plugged_in':bool(latest['plugged_in']),'module_min_f':mn,'module_max_f':mx,'module_spread_f':spread,
                   'pack_move_30m_f':pack_move,'pack_voltage_v':_f(latest['pack_voltage_v']),'pack_current_a':_f(latest['pack_current_a']),
                   'wall_kw':wall_kw,'pack_kw':pack_kw,'nonpack_kw':nonpack,'pack_share_pct':pack_share},
        'forecast':[f1,f3,f6], 'coldest':cold,
        'weather':{'status':weather.get('status'),'source':weather.get('source'),'fetched_at':weather.get('fetched_at'),'forecast_low_f':round(forecast_low,1) if forecast_low is not None else None},
        'thermal':{'retention_k_per_hr':None if k is None else round(k,4),'retention_samples':nk,'target_pack_f':target_pack,'season':season,
                   'current_margin_f':None if cur_pack is None or cur_out is None else round(cur_pack-cur_out,1),'coldest_margin_f':cold.get('margin_f')},
        'departure':{'status':ready.get('status'),'confidence':ready.get('confidence'),'departure_ts':ready.get('departure_ts'),'current_soc':ready.get('current_soc'),
                     'departure_soc':ready.get('predicted_departure_soc'),'arrival_soc':ready.get('predicted_arrival_soc'),'departure_pack_f':ready.get('predicted_departure_pack_f'),
                     'precondition_start_ts':ready.get('suggested_precondition_start_ts'),'precondition_minutes':ready.get('suggested_precondition_minutes'),
                     'charge_target_soc':ready.get('charge_target_soc'),'charge_target_ts':ready.get('charge_target_ts'),'charging_now':ready.get('charging_now'),
                     'probability':ready.get('departure_probability'),'departure_class':ready.get('departure_class'),'departure_source':ready.get('departure_source'),
                     'departure_learning':ready.get('departure_learning',{}),
                     'routine':ready.get('routine',{}),'trip_prediction':ready.get('trip_prediction',{}),'reasons':ready.get('reasons',[])},
        'history':_thermal_history(latest['car_id'],now),'timeline':_timeline(now),'live_warmup':live_warmup,
        'notes':['Readiness score is a transparent operational score, not model accuracy.','Weather is fetched only for forecast temperatures; model training and inference remain local on GHOST.']
    }

from __future__ import annotations
import json, math, statistics, time
from . import config, db
from .event_engine import routine_profile, learned_dynamics, event_summary

def _f(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except Exception:return None

def _f2c(f): return (f-32)*5/9

def _c2f(c): return None if c is None else c*9/5+32

def _parse_target_soc(raw_json):
    try:
        j=json.loads(raw_json or '{}')
        # Tessie cached state nests this under state.charge_state; historical states may vary.
        for root in (j,j.get('state',{}) if isinstance(j,dict) else {}):
            cs=root.get('charge_state',{}) if isinstance(root,dict) else {}
            if isinstance(cs,dict) and cs.get('charge_limit_soc') is not None:return float(cs['charge_limit_soc'])
    except Exception:pass
    return None

def _next_departure(profile,now):
    schedule={}
    if config.DEPARTURE_LEARNING_ENABLED:
        try:
            from .departure_learning import schedule_status
            schedule=schedule_status(now, refresh=True)
            nxt=schedule.get('next') or {}
            if nxt.get('departure_ts') is not None:
                return float(nxt['departure_ts']), str(nxt.get('source') or 'learned_schedule'), schedule
        except Exception:
            schedule={}

    # Safe fallback: use the commute profile, then the configured 06:00 seed if
    # the schedule learner is not ready. This preserves winter readiness during
    # cold start without turning the seed back into a permanent override.
    minute=profile.get('departure_minute')
    source='routine_fallback'
    if minute is None and config.EXPECTED_DEPARTURE and ':' in config.EXPECTED_DEPARTURE:
        try:
            h,m=(int(x) for x in config.EXPECTED_DEPARTURE.split(':',1)); minute=h*60+m; source='anchor_prior'
        except Exception:
            minute=None
    if minute is None:return None,source,schedule
    lt=time.localtime(now); midnight=time.mktime((lt.tm_year,lt.tm_mon,lt.tm_mday,0,0,0,lt.tm_wday,lt.tm_yday,lt.tm_isdst)); dep=midnight+minute*60
    if dep<=now+5*60:dep+=86400
    return dep,source,schedule

def _confidence(profile,dyn):
    parts=[]
    if profile.get('samples'):parts.append(min(100,profile['samples']/15*100))
    if dyn.get('cold_samples'):parts.append(min(100,dyn['cold_samples']/15*100))
    if dyn.get('l1_samples'):parts.append(min(100,dyn['l1_samples']/10*100))
    if not parts:return 10
    return int(round(sum(parts)/len(parts)))

def current_readiness(now:float|None=None):
    db.init_db(); now=float(now or time.time())
    with db.connect() as con:
        latest=con.execute('SELECT * FROM telemetry ORDER BY ts DESC LIMIT 1').fetchone()
    if not latest:return {'status':'WAITING','confidence':0,'reason':'No telemetry available.'}
    profile=routine_profile(); dyn=learned_dynamics(); summary=event_summary(); dep,dep_source,departure_learning=_next_departure(profile,now)
    cur_soc=_f(latest['battery_level']); pack_c=_f(latest['battery_temp_c']); out_c=_f(latest['outside_temp_c'])
    hours=None if dep is None else max(0.0,(dep-now)/3600)
    pred_pack_c=pack_c
    thermal_basis='current pack'
    k=_f(dyn.get('cold_soak_k_per_hr'))
    if hours is not None and pack_c is not None and out_c is not None and k is not None and k>0:
        pred_pack_c=out_c+(pack_c-out_c)*math.exp(-k*hours); thermal_basis=f'learned cold-soak k={k:.3f}/h'
    pred_soc=cur_soc; soc_basis='current SOC'
    charging=str(latest['charging_state'] or '').lower()=='charging' or (_f(latest['charge_input_kw']) or 0)>0.15
    charge_rate=_f(dyn.get('l1_soc_pct_hr')); standby=_f(dyn.get('standby_soc_pct_hr'))
    target_soc=_parse_target_soc(latest['raw_json']) or 80.0
    if hours is not None and cur_soc is not None:
        if charging and charge_rate is not None and charge_rate>0:
            pred_soc=min(target_soc,cur_soc+charge_rate*hours); soc_basis=f'learned L1 rate {charge_rate:.2f}%/h'
        elif standby is not None and standby>=0:
            pred_soc=max(0,cur_soc-standby*hours); soc_basis=f'learned standby drain {standby:.3f}%/h'
    commute_drop=_f(profile.get('soc_drop')); arrival=None if pred_soc is None or commute_drop is None else max(0,pred_soc-commute_drop)
    target_pack_f=float(config.READINESS_TARGET_PACK_F); pred_pack_f=_c2f(pred_pack_c); cur_pack_f=_c2f(pack_c); pre_start=None; pre_min=None
    trip_prediction={}
    try:
        from .event_models import current_trip_prediction
        trip_prediction=current_trip_prediction(profile.get('distance_mi'),pred_soc,pred_pack_f,_c2f(out_c),dep)
        if trip_prediction.get('predicted_arrival_soc') is not None:
            arrival=float(trip_prediction['predicted_arrival_soc'])
            commute_drop=max(0,float(pred_soc)-arrival) if pred_soc is not None else commute_drop
    except Exception:
        trip_prediction={}
    heat_rate=_f(dyn.get('precondition_heat_f_hr'))
    if dep is not None and pred_pack_f is not None and pred_pack_f<target_pack_f and heat_rate is not None and heat_rate>0.5:
        pre_min=min(90,max(0,(target_pack_f-pred_pack_f)/heat_rate*60)); pre_start=dep-pre_min*60
    confidence=_confidence(profile,dyn)
    if departure_learning:
        confidence=int(round((confidence*0.65)+((departure_learning.get('confidence') or 0)*0.35)))
    if out_c is not None and out_c<=config.COLD_SOAK_THRESHOLD_C and int(dyn.get('cold_samples') or 0)<3:
        confidence=min(confidence,35)
    status='LEARNING'
    reasons=[]
    if dep is None:reasons.append('No stable departure routine learned yet.')
    if profile.get('samples',0)<3:reasons.append('More first-drive events are needed for commute learning.')
    if arrival is not None:
        if arrival<config.READINESS_MIN_ARRIVAL_SOC:status='LOW MARGIN';reasons.append(f'Learned commute profile projects arrival near {arrival:.0f}% SOC.')
        elif confidence>=55:status='READY'
        else:status='WATCH'
    elif pred_soc is not None and confidence>=40:status='WATCH'
    if pred_pack_f is not None and pred_pack_f<32:reasons.append('Pack is projected below freezing at departure under the current-ambient assumption.')
    if pred_pack_f is not None and pred_pack_f<target_pack_f and heat_rate is None:
        reasons.append('Pack is below the warm-pack policy target, but GHOST has not learned enough preconditioning heat-rate evidence yet.')
        if status=='READY':status='WATCH'
    if pre_start is not None:reasons.append('A preconditioning start time is derived from your observed pack-heating rate.')
    if not reasons:reasons.append('Current learned charge, thermal and commute margins look normal.')
    charge_target_time=None
    if charging and charge_rate and cur_soc is not None and charge_rate>0 and target_soc>cur_soc:
        charge_target_time=now+(target_soc-cur_soc)/charge_rate*3600
    out={
      'status':status,'confidence':confidence,'generated_at':now,
      'departure_ts':dep,'departure_source':dep_source,'configured_departure':config.EXPECTED_DEPARTURE or None,'hours_to_departure':None if hours is None else round(hours,2),
      'departure_learning':departure_learning,'departure_probability':((departure_learning.get('next') or {}).get('probability') if departure_learning else None),
      'departure_class':((departure_learning.get('next') or {}).get('class') if departure_learning else None),
      'current_soc':cur_soc,'predicted_departure_soc':None if pred_soc is None else round(pred_soc,1),'predicted_arrival_soc':None if arrival is None else round(arrival,1),
      'current_pack_f':None if cur_pack_f is None else round(cur_pack_f,1),'predicted_departure_pack_f':None if pred_pack_f is None else round(pred_pack_f,1),
      'outside_f':None if out_c is None else round(_c2f(out_c),1),'target_pack_f':target_pack_f,
      'suggested_precondition_start_ts':pre_start,'suggested_precondition_minutes':None if pre_min is None else round(pre_min),
      'charge_target_soc':target_soc,'charge_target_ts':charge_target_time,'charging_now':charging,
      'thermal_basis':thermal_basis,'soc_basis':soc_basis,'reasons':reasons,
      'routine':profile,'dynamics':dyn,'events':summary,'trip_prediction':trip_prediction,
      'assumptions':['Future ambient temperature currently assumes the latest observed outside temperature.','Departure timing is learned from observed drive starts; the configured 06:00 work time is only a fading cold-start prior.','Readiness does not control the vehicle; it is prediction/advice only.']
    }
    return out

def snapshot_readiness():
    r=current_readiness();
    with db.connect() as con:
        latest=con.execute('SELECT car_id FROM telemetry ORDER BY ts DESC LIMIT 1').fetchone(); car=None if not latest else latest['car_id']
        con.execute('''INSERT INTO readiness_snapshots(created_at,car_id,departure_ts,status,confidence,current_soc,predicted_departure_soc,predicted_arrival_soc,current_pack_f,predicted_departure_pack_f,suggested_precondition_start_ts,payload_json)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(time.time(),car,r.get('departure_ts'),r.get('status'),r.get('confidence'),r.get('current_soc'),r.get('predicted_departure_soc'),r.get('predicted_arrival_soc'),r.get('current_pack_f'),r.get('predicted_departure_pack_f'),r.get('suggested_precondition_start_ts'),json.dumps(r,separators=(',',':'))))
    db.set_state('morning_readiness',r); return r

def readiness_history(limit:int=120):
    with db.connect() as con:
        rows=con.execute('SELECT created_at,departure_ts,status,confidence,predicted_departure_soc,predicted_arrival_soc,predicted_departure_pack_f FROM readiness_snapshots ORDER BY created_at DESC LIMIT ?',(max(1,min(int(limit),500)),)).fetchall()
    return [dict(r) for r in rows]

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

def _weather_at_departure(hourly, ts, now, observed_f):
    """Interpolate a nearby hourly forecast; never extrapolate stale forecasts."""
    values=[]
    for row in hourly or []:
        if not isinstance(row, dict):
            continue
        t=_f(row.get('ts')); f=_f(row.get('temp_f'))
        if t is not None and f is not None and -100 <= f <= 140:
            values.append((t,f))
    values.sort()
    if ts <= now or not values:
        return observed_f, False
    prev=(now, observed_f) if observed_f is not None else None
    for point in values:
        if point[0] <= now:
            continue
        if point[0] >= ts:
            if prev is not None and 0 < point[0]-prev[0] <= 3*3600:
                w=(ts-prev[0])/(point[0]-prev[0])
                return prev[1]+w*(point[1]-prev[1]), True
            if abs(point[0]-ts) <= 45*60:
                return point[1], True
            break
        prev=point
    if prev is not None and prev[0]>now and abs(ts-prev[0])<=45*60:
        return prev[1], True
    return observed_f, False


def _pack_at_departure(pack_c, outside_c, k, now, departure, hourly):
    """First-order passive pack cooling with weather updated every 30 minutes.

    No active cabin/battery heating is presumed. This remains a planning
    estimate, not a BMS temperature model or a heating recommendation.
    """
    if None in (pack_c, outside_c, k, departure) or k <= 0 or departure <= now:
        return pack_c, False
    elapsed=min(36*3600, departure-now)
    n=max(1, int(math.ceil(elapsed/1800)))
    dt_hours=elapsed/n/3600
    p=pack_c
    used=False
    outside_f=_c2f(outside_c)
    for i in range(n):
        ts=now+elapsed*(i+0.5)/n
        ambient_f, found=_weather_at_departure(hourly,ts,now,outside_f)
        used=used or found
        ambient_c=_f2c(ambient_f)
        p=ambient_c+(p-ambient_c)*math.exp(-k*dt_hours)
    return p, used


def _arrival_planning_buffer(trip_prediction, predicted_arrival):
    """Two holdout-MAE planning buffer; explicitly NOT a confidence interval."""
    if predicted_arrival is None or not isinstance(trip_prediction,dict):
        return None, None
    mod=trip_prediction.get('trip_soc_drop') or {}
    mae=_f(mod.get('mae'))
    if mae is None or mae <= 0 or mae > 30:
        return None, None
    margin=min(30.0, 2.0*mae)
    return max(0.0, predicted_arrival-margin), margin



def _comparable_commute_stats(rows, distance_mi, departure_ts):
    """Compare completed drives with a similar distance, weekday and time of day.

    This is NOT GPS-route matching. A weekday afternoon trip of approximately
    the same length is a useful empirical sanity check, not proof of route.
    """
    distance=_f(distance_mi)
    if distance is None or not 15 <= distance <= 120 or departure_ts is None:
        return {'status':'UNAVAILABLE','count':0,'basis':'distance/time-only; not route-verified'}
    lt=time.localtime(float(departure_ts))
    hour=lt.tm_hour
    window='MORNING' if 4 <= hour < 12 else 'AFTERNOON' if 12 <= hour < 20 else None
    if window is None:
        return {'status':'UNAVAILABLE','count':0,'basis':'departure outside commute windows'}
    weekend=lt.tm_wday>=5
    candidates=[]
    for r in rows:
        miles=_f(r['distance_km'])
        change=_f(r['soc_change'])
        ts=_f(r['start_ts'])
        if miles is None or change is None or ts is None:continue
        miles*=0.621371
        if miles < distance*0.80 or miles > distance*1.20:continue
        if change >= 0 or change < -60:continue
        when=time.localtime(ts)
        if (when.tm_wday>=5)!=weekend:continue
        if not (4<=when.tm_hour<12 if window=='MORNING' else 12<=when.tm_hour<20):continue
        candidates.append(r)
    count=len(candidates)
    if count<8:
        return {'status':'INSUFFICIENT','count':count,'window':window,
                'basis':'similar distance/time/weekday; not GPS-verified'}
    drops=[-_f(r['soc_change']) for r in candidates]
    temps=[_c2f(_f(r['avg_outside_c'])) for r in candidates if _f(r['avg_outside_c']) is not None]
    whmi=[_f(r['energy_used_kwh'])*1000/(_f(r['distance_km'])*0.621371)
          for r in candidates if _f(r['energy_used_kwh']) is not None
          and _f(r['energy_used_kwh'])>0 and _f(r['distance_km'])>0]
    return {
        'status':'SUPPORTED', 'window':window,'count':count,
        'median_soc_drop':round(statistics.median(drops),2),
        'median_wh_per_mile':round(statistics.median(whmi),1) if whmi else None,
        'observed_min_f':round(min(temps),1) if temps else None,
        'observed_max_f':round(max(temps),1) if temps else None,
        'basis':'last 90 days, weekday/weekend and time window matched, distance +/-20%; NOT GPS-route verified'
    }


def _historical_commute_guard(distance_mi, departure_ts, car_id, now):
    """Read-only empirical floor for trip SOC drop, never modifies training."""
    if distance_mi is None or departure_ts is None or not car_id:
        return {'status':'UNAVAILABLE','count':0}
    try:
        with db.connect() as con:
            rows=con.execute("""SELECT start_ts,distance_km,soc_change,
                   energy_used_kwh,avg_outside_c FROM vehicle_events
                   WHERE car_id=? AND event_type='drive'
                   AND start_ts>=? AND start_ts<=?
                   AND soc_change<0 AND soc_change>=-60
                   AND distance_km>=24
                   ORDER BY start_ts DESC LIMIT 400""",
                   (car_id,now-90*86400,now)).fetchall()
        return _comparable_commute_stats(rows,distance_mi,departure_ts)
    except Exception as exc:
        return {'status':'UNAVAILABLE','count':0,'reason':type(exc).__name__}

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

def current_readiness(now:float|None=None, weather_hours=None):
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
    if weather_hours is None:
        # Other readiness API consumers can reuse a *recent* cached forecast.
        # The winter-board endpoint passes its freshly requested hours instead.
        weather_hours=[]
        try:
            if config.get_bool('WEATHER_ENABLED',True):
                cached=db.get_state('winter_weather',{}) or {}
                if now-(_f(cached.get('fetched_at')) or 0) <= 3*3600:
                    weather_hours=cached.get('hours',[]) or []
        except Exception:
            pass
    future_out_f, outside_forecast=_weather_at_departure(
        weather_hours, dep, now, _c2f(out_c)) if dep is not None else (_c2f(out_c),False)
    if hours is not None and pack_c is not None and out_c is not None and k is not None and k>0:
        pred_pack_c, pack_forecast=_pack_at_departure(pack_c,out_c,k,now,dep,weather_hours)
        thermal_basis=(f'learned cooling k={k:.3f}/h + hourly forecast'
                       if pack_forecast else f'learned cold-soak k={k:.3f}/h; constant ambient fallback')
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
        trip_prediction=current_trip_prediction(profile.get('distance_mi'),pred_soc,pred_pack_f,future_out_f,dep)
        if trip_prediction.get('predicted_arrival_soc') is not None:
            arrival=float(trip_prediction['predicted_arrival_soc'])
            commute_drop=max(0,float(pred_soc)-arrival) if pred_soc is not None else commute_drop
    except Exception:
        trip_prediction={}
    # v1.1: cross-check the promoted model against completed comparable
    # trips. Keep raw model output untouched, and use a historical median
    # floor for SOC consumption ONLY when >=8 matched drives exist.
    # This intentionally does not claim cold-weather extrapolation accuracy.
    comparable=_historical_commute_guard(profile.get('distance_mi'),dep,latest['car_id'],now)
    raw_arrival=arrival
    model_drop=_f((trip_prediction.get('trip_soc_drop') or {}).get('value'))
    baseline_drop=_f(comparable.get('median_soc_drop')) if comparable.get('status')=='SUPPORTED' else None
    floor_applied=False
    if pred_soc is not None and baseline_drop is not None:
        raw_drop=max(0.0,float(pred_soc)-float(raw_arrival)) if raw_arrival is not None else None
        if raw_drop is None or raw_drop+0.1 < baseline_drop:
            arrival=max(0.0,float(pred_soc)-baseline_drop)
            commute_drop=baseline_drop
            floor_applied=True
    trip_prediction['historical_comparison']=comparable
    trip_prediction['raw_model_arrival_soc']=None if raw_arrival is None else round(raw_arrival,1)
    trip_prediction['model_soc_drop']=model_drop
    trip_prediction['operational_soc_drop']=None if pred_soc is None or arrival is None else round(max(0.0,pred_soc-arrival),2)
    trip_prediction['empirical_floor_applied']=floor_applied
    trip_prediction['operational_arrival_soc']=None if arrival is None else round(arrival,1)
    if floor_applied:
        trip_prediction['operational_basis']='Matched completed-drive median is higher than the model forecast; conservative consumption floor applied'
    else:
        trip_prediction['operational_basis']='Model or existing commute forecast; insufficient matched evidence or no floor needed'
    # Do not treat a warm-weather validation MAE as a winter guarantee.
    # This observed-drive coverage is separate from model training coverage.
    support={'status':'UNKNOWN','cold_drive_samples':0,'observed_min_f':None,'observed_max_f':None}
    if future_out_f is not None:
        try:
            with db.connect() as con:
                row=con.execute("""SELECT COUNT(*) n,
                    MIN(avg_outside_c) min_c,MAX(avg_outside_c) max_c,
                    SUM(CASE WHEN avg_outside_c<=? THEN 1 ELSE 0 END) cold_n
                    FROM vehicle_events WHERE event_type='drive'
                    AND distance_km>=3 AND start_soc IS NOT NULL
                    AND start_pack_c IS NOT NULL AND avg_outside_c IS NOT NULL
                    AND soc_change<0 AND soc_change>=-70""",(_f2c(45),)).fetchone()
            low=_f(row['min_c']); high=_f(row['max_c'])
            cold_n=int(row['cold_n'] or 0)
            support={'status':'WITHIN_OBSERVED_RANGE','cold_drive_samples':cold_n,
                     'observed_min_f':None if low is None else round(_c2f(low),1),
                     'observed_max_f':None if high is None else round(_c2f(high),1)}
            if low is None or high is None:
                support['status']='UNKNOWN'
            elif _f2c(future_out_f) < low-0.5 or _f2c(future_out_f) > high+0.5:
                support['status']='OUTSIDE_OBSERVED_RANGE'
            elif future_out_f < 45 and cold_n < 5:
                support['status']='INSUFFICIENT_COLD_DRIVES'
        except Exception:
            pass
    trip_prediction['weather_coverage']=support
    # Keep model output separately while operational readiness uses the
    # history-guarded forecast; the error buffer is not a confidence interval.
    arrival_buffered, buffer_pp=_arrival_planning_buffer(trip_prediction,arrival)
    winter_unvalidated=(future_out_f is not None and future_out_f<45 and support['status']!='WITHIN_OBSERVED_RANGE')
    trip_prediction['arrival_soc_buffered']=None if arrival_buffered is None or winter_unvalidated else round(arrival_buffered,1)
    trip_prediction['soc_planning_buffer_pp']=None if buffer_pp is None or winter_unvalidated else round(buffer_pp,1)
    trip_prediction['planning_buffer_basis']=('Cold-weather consumption not sufficiently observed: warm-data MAE buffer suppressed.'
        if winter_unvalidated else '2x held-out SOC-drop MAE, not a calibrated confidence interval'
        if buffer_pp is not None else 'not enough model evidence')
    trip_prediction['departure_outside_f']=None if future_out_f is None else round(future_out_f,1)
    trip_prediction['hourly_forecast_used']=bool(outside_forecast)
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
      'outside_f':None if out_c is None else round(_c2f(out_c),1),'predicted_departure_outside_f':None if future_out_f is None else round(future_out_f,1),'hourly_forecast_used':bool(outside_forecast),'target_pack_f':target_pack_f,
      'suggested_precondition_start_ts':pre_start,'suggested_precondition_minutes':None if pre_min is None else round(pre_min),
      'charge_target_soc':target_soc,'charge_target_ts':charge_target_time,'charging_now':charging,
      'thermal_basis':thermal_basis,'soc_basis':soc_basis,'reasons':reasons,
      'routine':profile,'dynamics':dyn,'events':summary,'trip_prediction':trip_prediction,
      'assumptions':['Comparable-distance and time-of-day completed drives provide a conservative SOC-use floor with 8+ samples; not GPS route matching or winter calibration.','Departure weather uses hourly forecast when available, otherwise current ambient; passive pack cooling assumes no active preheating.','Departure timing is learned from observed drive starts; the configured 06:00 work time is only a fading cold-start prior.','Readiness does not control the vehicle; it is prediction/advice only.']
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

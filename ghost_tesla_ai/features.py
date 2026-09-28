from __future__ import annotations
import bisect, math, time
from . import db, config

LEGACY_FEATURES = [
 'battery_level','usable_battery_level','outside_temp_c','inside_temp_c','battery_temp_c',
 'power_kw','speed_kmh','plugged_in','charger_power_kw','charger_voltage','charger_actual_current',
 'climate_on','preconditioning','hour_sin','hour_cos','dow_sin','dow_cos',
 'state_asleep','state_online','state_charging','state_driving'
]

V3_FEATURES = [
 'battery_level','usable_battery_level','outside_temp_c','inside_temp_c','battery_temp_c',
 'pack_power_kw','speed_kmh','plugged_in','charger_power_kw','charge_input_kw',
 'climate_on','preconditioning','battery_heater_on','energy_remaining_kwh',
 'module_temp_spread_c','pack_ambient_delta_c',
 'soc_delta_15m','pack_temp_delta_15m','cabin_temp_delta_15m','outside_temp_delta_15m',
 'avg_pack_power_15m','avg_charge_power_15m','active_fraction_15m',
 'hour_sin','hour_cos','dow_sin','dow_cos',
 'state_asleep','state_online','state_charging','state_driving'
]
BASE_FEATURES = V3_FEATURES
FEATURE_VERSION = 'v3-context-1'

MODEL_SPECS = {
 'soc_60m': {'target':'battery_level','horizon':60,'unit':'%','label':'SOC +60 min','regime':None},
 'soc_180m': {'target':'battery_level','horizon':180,'unit':'%','label':'SOC +3 hr','regime':None},
 'cabin_temp_60m': {'target':'inside_temp_c','horizon':60,'unit':'C','label':'Cabin temp +60 min','regime':None},
 'pack_temp_60m': {'target':'battery_temp_c','horizon':60,'unit':'C','label':'Pack temp +60 min','regime':None},
 'pack_temp_180m': {'target':'battery_temp_c','horizon':180,'unit':'C','label':'Pack temp +3 hr','regime':None},
 'cold_pack_60m': {'target':'battery_temp_c','horizon':60,'unit':'C','label':'Cold-soak pack +60 min','regime':'cold_soak','min_rows':60},
 'charge_soc_60m': {'target':'battery_level','horizon':60,'unit':'%','label':'L1 charge SOC +60 min','regime':'l1_charging','min_rows':60},
 'precondition_pack_30m': {'target':'battery_temp_c','horizon':30,'unit':'C','label':'Precondition pack +30 min','regime':'preconditioning','min_rows':40},
 'park_soc_180m': {'target':'battery_level','horizon':180,'unit':'%','label':'Parked SOC +3 hr','regime':'parked','min_rows':80},
}

def _get(row,key,default=None):
    try: return row[key]
    except Exception:
        try: return row.get(key,default)
        except Exception: return default

def _n(row,key):
    v=_get(row,key)
    try:
        x=float(v); return x if math.isfinite(x) else float('nan')
    except Exception: return float('nan')

def _finite(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except Exception: return None

def _truth(v):
    try: return bool(int(v))
    except Exception: return bool(v)

def _state_bits(state: str | None):
    s=(state or '').lower()
    return {
        'state_asleep':float(s=='asleep'),
        'state_online':float(s in {'online','awake'}),
        'state_charging':float(s=='charging'),
        'state_driving':float(s=='driving'),
    }

def classify_regime(row, prev=None, nxt=None) -> str:
    """Transparent operating-regime classifier used by both models and event extraction."""
    state=str(_get(row,'state','') or '').lower()
    shift=str(_get(row,'shift_state','') or '').upper()
    speed=_finite(_get(row,'speed_kmh')) or 0.0
    charge_state=str(_get(row,'charging_state','') or '').lower()
    charge_kw=_finite(_get(row,'charge_input_kw'))
    if charge_kw is None: charge_kw=_finite(_get(row,'charger_power_kw')) or 0.0
    driving = state=='driving' or shift in {'D','R','N'} or speed>2.0
    if not driving and prev is not None and nxt is not None:
        a=_finite(_get(prev,'odometer_km')); b=_finite(_get(nxt,'odometer_km'))
        if a is not None and b is not None and b-a>0.15: driving=True
    charging = charge_state=='charging' or charge_kw>0.15
    preconditioning = _truth(_get(row,'preconditioning')) or (_truth(_get(row,'climate_on')) and _truth(_get(row,'battery_heater_on')))
    if driving: return 'driving'
    if charging:
        volts=_finite(_get(row,'charger_voltage')) or 0.0
        return 'l1_charging' if (charge_kw<=2.5 and (volts==0 or volts<180)) else 'charging'
    if preconditioning: return 'preconditioning'
    outside=_finite(_get(row,'outside_temp_c'))
    if outside is not None and outside<=config.COLD_SOAK_THRESHOLD_C: return 'cold_soak'
    if state=='asleep': return 'sleeping'
    return 'parked'

def _nearest_prior(history, target_ts):
    if not history: return None
    times=[float(_get(r,'ts') or 0) for r in history]
    j=bisect.bisect_right(times,float(target_ts))-1
    return history[j] if j>=0 else None

def _avg(history,key):
    vals=[]
    for r in history:
        v=_finite(_get(r,key))
        if v is not None: vals.append(v)
    return sum(vals)/len(vals) if vals else None

def feature_map(row, history=None) -> dict[str,float]:
    history=list(history or [row])
    ts=float(_get(row,'ts') or time.time())
    cutoff=ts-15*60
    recent=[r for r in history if float(_get(r,'ts') or 0)>=cutoff and float(_get(r,'ts') or 0)<=ts]
    prior=_nearest_prior(history,cutoff)
    if prior is None: prior=history[0] if history else row
    lt=time.localtime(ts); hour=lt.tm_hour+lt.tm_min/60
    hour_a=2*math.pi*hour/24; dow_a=2*math.pi*lt.tm_wday/7
    out={}
    direct=['battery_level','usable_battery_level','outside_temp_c','inside_temp_c','battery_temp_c','power_kw','speed_kmh','plugged_in',
            'charger_power_kw','charger_voltage','charger_actual_current','climate_on','preconditioning','battery_heater_on','energy_remaining_kwh',
            'pack_power_kw','charge_input_kw','module_temp_spread_c','pack_ambient_delta_c']
    for k in direct: out[k]=_n(row,k)
    # derive locally if a stored historical row predates the v0.3 columns
    if math.isnan(out['pack_power_kw']):
        pv=_finite(_get(row,'pack_voltage_v')); pa=_finite(_get(row,'pack_current_a'))
        out['pack_power_kw']=float('nan') if pv is None or pa is None else pv*pa/1000.0
    if math.isnan(out['charge_input_kw']):
        cv=_finite(_get(row,'charger_voltage')); ca=_finite(_get(row,'charger_actual_current')); cp=_finite(_get(row,'charger_power_kw'))
        out['charge_input_kw']=cv*ca/1000.0 if cv is not None and ca is not None else (cp if cp is not None else float('nan'))
    if math.isnan(out['module_temp_spread_c']):
        lo=_finite(_get(row,'module_temp_min_c')); hi=_finite(_get(row,'module_temp_max_c'))
        out['module_temp_spread_c']=float('nan') if lo is None or hi is None else max(0.0,hi-lo)
    if math.isnan(out['pack_ambient_delta_c']):
        p=_finite(_get(row,'battery_temp_c')); a=_finite(_get(row,'outside_temp_c'))
        out['pack_ambient_delta_c']=float('nan') if p is None or a is None else p-a
    def delta(k):
        a=_finite(_get(row,k)); b=_finite(_get(prior,k)) if prior is not None else None
        return float('nan') if a is None or b is None else a-b
    out['soc_delta_15m']=delta('battery_level')
    out['pack_temp_delta_15m']=delta('battery_temp_c')
    out['cabin_temp_delta_15m']=delta('inside_temp_c')
    out['outside_temp_delta_15m']=delta('outside_temp_c')
    pp=[]; cp=[]; active=0
    for r in recent:
        pv=_finite(_get(r,'pack_power_kw'))
        if pv is None:
            vv=_finite(_get(r,'pack_voltage_v')); aa=_finite(_get(r,'pack_current_a')); pv=None if vv is None or aa is None else vv*aa/1000.0
        if pv is not None: pp.append(pv)
        q=_finite(_get(r,'charge_input_kw'))
        if q is None:
            vv=_finite(_get(r,'charger_voltage')); aa=_finite(_get(r,'charger_actual_current')); q=None if vv is None or aa is None else vv*aa/1000.0
        if q is not None: cp.append(q)
        if classify_regime(r) in {'driving','charging','l1_charging','preconditioning'}: active+=1
    out['avg_pack_power_15m']=sum(pp)/len(pp) if pp else float('nan')
    out['avg_charge_power_15m']=sum(cp)/len(cp) if cp else float('nan')
    out['active_fraction_15m']=active/max(1,len(recent))
    out.update({'hour_sin':math.sin(hour_a),'hour_cos':math.cos(hour_a),'dow_sin':math.sin(dow_a),'dow_cos':math.cos(dow_a)})
    out.update(_state_bits(str(_get(row,'state','') or '')))
    return out

def row_to_features(row, feature_names=None, history=None) -> list[float]:
    names=list(feature_names or LEGACY_FEATURES)
    fm=feature_map(row,history)
    return [float(fm.get(k,float('nan'))) for k in names]

def live_vector(row, feature_names=None):
    names=list(feature_names or LEGACY_FEATURES)
    ts=float(_get(row,'ts') or time.time()); car=str(_get(row,'car_id') or '')
    with db.connect() as con:
        hist=con.execute('SELECT * FROM telemetry WHERE car_id=? AND ts BETWEEN ? AND ? ORDER BY ts',(car,ts-3600,ts)).fetchall()
    return row_to_features(row,names,hist)

def _regime_match(spec_regime,row,prev,nxt):
    if not spec_regime: return True
    r=classify_regime(row,prev,nxt)
    if spec_regime=='parked': return r in {'parked','sleeping','cold_soak'}
    return r==spec_regime

def build_dataset(model_name: str):
    spec=MODEL_SPECS[model_name]; horizon=int(spec['horizon'])*60
    cutoff=time.time()-config.TRAIN_LOOKBACK_DAYS*86400
    car_id=db.latest_car_id() or str(config.CAR_ID)
    with db.connect() as con:
        rows=con.execute('SELECT * FROM telemetry WHERE ts>=? AND car_id=? ORDER BY ts ASC',(cutoff,car_id)).fetchall()
    if not rows: return [],[],[],[]
    times=[float(r['ts']) for r in rows]
    X=[]; y=[]; source_ids=[]; source_ts=[]
    target=spec['target']; tolerance=max(300,horizon*0.25); regime=spec.get('regime')
    for i,row in enumerate(rows):
        if _get(row,target) is None: continue
        prev=rows[i-1] if i else None; nxt=rows[i+1] if i+1<len(rows) else None
        if not _regime_match(regime,row,prev,nxt): continue
        want=times[i]+horizon
        j=bisect.bisect_left(times,want,i+1)
        if j>=len(rows) or times[j]-want>tolerance: continue
        if _get(rows[j],target) is None: continue
        # Regime-specific models should not train across an intervening drive, which
        # otherwise makes parked/cold predictions deceptively easy or noisy.
        if regime in {'cold_soak','parked','l1_charging'}:
            target_reg=classify_regime(rows[j], rows[j-1] if j else None, rows[j+1] if j+1<len(rows) else None)
            if regime=='parked' and target_reg not in {'parked','sleeping','cold_soak'}: continue
            if regime=='cold_soak' and target_reg not in {'cold_soak','sleeping','parked'}: continue
            if regime=='l1_charging' and target_reg not in {'l1_charging','parked'}: continue
        h0=bisect.bisect_left(times,times[i]-3600,0,i+1)
        history=rows[h0:i+1]
        X.append(row_to_features(row,V3_FEATURES,history)); y.append(float(rows[j][target])); source_ids.append(int(row['id'])); source_ts.append(float(row['ts']))
    return X,y,source_ids,source_ts

def spec_applicable(spec: dict, row) -> bool:
    regime=spec.get('regime') if spec else None
    if not regime:return True
    current=classify_regime(row)
    if regime=='parked':return current in {'parked','sleeping','cold_soak'}
    if regime=='cold_soak':return current=='cold_soak'
    return current==regime

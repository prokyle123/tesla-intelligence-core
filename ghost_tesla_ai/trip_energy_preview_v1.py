"""Read-only conditional multi-leg trip energy preview for GHOST.

Uses observed route transitions and chains ONLY; never equates nearby sites,
never creates a vehicle control instruction, never modifies the winter score.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
import json, math, sqlite3, time

ROOT = Path('/home/ghost/ghost-trip-sequence')
LIVE = Path('/var/lib/ghost-tesla-ai/ghost_ai.sqlite3')
MAX_HORIZON_H = 24


def _number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _future_clock(hhmm, now, after, group='weekday', hours=24):
    try:
        h,m = map(int, str(hhmm).split(':'))
        if not (0 <= h < 24 and 0 <= m < 60): return None
    except Exception: return None
    origin = datetime.fromtimestamp(now)
    for d in range(3):
        day = origin.date() + timedelta(days=d)
        if group == 'weekday' and day.weekday() >= 5: continue
        if group == 'weekend' and day.weekday() < 5: continue
        candidate = datetime(day.year,day.month,day.day,h,m).timestamp()
        if candidate > after + 1800 and candidate <= now + hours*3600:
            return candidate
    return None


def _observations(db_path=LIVE):
    try:
        c=sqlite3.connect(f'file:{db_path}?mode=ro',uri=True,timeout=1)
        c.row_factory=sqlite3.Row
        try:
            row=c.execute('SELECT ts,battery_level,shift_state,speed_kmh,charging_state FROM telemetry ORDER BY ts DESC LIMIT 1').fetchone()
            return dict(row) if row else None
        finally:c.close()
    except (sqlite3.Error, OSError):return None


def calculate(context, latest, now, *, horizon_hours=24):
    """Pure preview. No actual future charging or parking drain is assumed."""
    result={'version':'conditional-trip-energy-v1', 'shadow':True,
            'mode':'INSUFFICIENT','trip_count':0,'route_soc_demand_pp':None,
            'legs':[],'note':'Not enough verified connected-route evidence for a multi-trip energy scenario.'}
    if not isinstance(context,dict):return result
    transitions={}
    for t in context.get('transitions') or []:
        if not isinstance(t,dict):continue
        s,e=t.get('from_site'),t.get('to_site')
        pp=_number(t.get('median_soc_drop'))
        samples=int(t.get('energy_samples') or 0)
        days=int(t.get('support_days') or 0)
        if not s or not e or s==e or pp is None or not (0 < pp <= 40) or days<5 or samples<3:continue
        transitions[(s,e)]=dict(t, median_soc_drop=pp, support_days=days,energy_samples=samples)
    if not transitions:return result
    curr=context.get('current_site') or {}
    obs_age=_number(curr.get('observation_age_minutes'))
    age_telemetry=now - (_number((latest or {}).get('ts')) or 0)
    active_site = (curr.get('site') if obs_age is not None and 0<=obs_age<=20
                   and now-(_number(context.get('generated_at')) or 0)<=3600
                   and -120<=age_telemetry<=900
                   and str((latest or {}).get('shift_state') or '').upper() in ('P','PARK','PARKED')
                   and (_number((latest or {}).get('speed_kmh')) or 0) <= 3 else None)
    candidates=[]
    # Directly observed origin only when the parked current location is verified.
    if active_site:
        for (a,b),tr in transitions.items():
            if a==active_site:
                t=_future_clock(tr.get('typical_departure'),now,now-1801,tr.get('group'),horizon_hours)
                if t:
                    candidates.append(('DIRECT_OBSERVED_ORIGIN',[(tr,t)]))
    # Historical chain is a hypothetical when its start site != verified parked site.
    for chain in context.get('trip_chains') or []:
        parts=[s.strip() for s in str(chain.get('sequence') or '').split('->')]
        if len(parts)<3 or len(parts)>5 or int(chain.get('support_days') or 0)<5:continue
        legs=[]; after=now-1801; valid=True
        for pair in zip(parts,parts[1:]):
            tr=transitions.get(pair)
            if not tr:valid=False; break
            t=_future_clock(tr.get('typical_departure'),now,after,tr.get('group'),horizon_hours)
            if t is None:valid=False;break
            after=t;legs.append((tr,t))
        if valid and legs:
            mode='DIRECT_OBSERVED_ORIGIN' if active_site==parts[0] else 'CONDITIONAL_START_SITE'
            candidates.append((mode,legs))
    if not candidates:return result
    # Prefer currently verified direct starts. For conditional plans prefer more complete chains.
    ranked=sorted(candidates,key=lambda x:(0 if x[0]=='DIRECT_OBSERVED_ORIGIN' else 1,
                                             -len(x[1]), x[1][0][1]))
    mode,legs=ranked[0]
    result['mode']=mode
    result['legs']=[{'from_site':t['from_site'],'to_site':t['to_site'],
                     'departure_ts':round(dt,0),'departure_local':datetime.fromtimestamp(dt).strftime('%a %I:%M %p'),
                     'soc_demand_pp':round(t['median_soc_drop'],1),'support_days':int(t['support_days']),
                     'energy_samples':int(t['energy_samples'])} for t,dt in legs]
    result['trip_count']=len(legs)
    result['route_soc_demand_pp']=round(sum(t['median_soc_drop'] for t,_ in legs),1)
    first=result['legs'][0]['from_site']
    if mode=='DIRECT_OBSERVED_ORIGIN':
        result['note']='Observed departure from verified parked site; conditional demand assumes no change in route and excludes future charging or parking losses.'
    else:
        result['note']=('Historical chain starts at '+first+'; current site '+str(curr.get('site') or 'unknown')+
                        ' is NOT asserted to be the same. Demand is conditional; no arrival SOC forecast.')
    return result


def preview(now=None):
    now=float(now or time.time())
    try:
        path=ROOT/'latest-location-context.json'
        if not path.is_file() or path.stat().st_size>2_000_000:
            return calculate({},None,now)
        context=json.loads(path.read_text())
        return calculate(context,_observations(),now)
    except (ValueError, OSError, TypeError, json.JSONDecodeError):
        return calculate({},None,now)


def self_test():
    base=datetime(2026,10,8,18,0).timestamp()
    ctx={'generated_at':base,'current_site':{'site':'SITE_002','observation_age_minutes':2},
         'transitions':[{'from_site':'SITE_003','to_site':'SITE_001','median_soc_drop':13.5,'support_days':8,'energy_samples':8,'group':'weekday','typical_departure':'06:16'},
                        {'from_site':'SITE_001','to_site':'SITE_002','median_soc_drop':13,'support_days':8,'energy_samples':7,'group':'weekday','typical_departure':'14:42'}],
         'trip_chains':[{'sequence':'SITE_003 -> SITE_001 -> SITE_002','support_days':7}]}
    obs={'ts':base,'shift_state':'P','speed_kmh':0}
    r=calculate(ctx,obs,base)
    assert r['mode']=='CONDITIONAL_START_SITE' and r['trip_count']==2 and r['route_soc_demand_pp']==26.5
    assert 'NOT asserted to be the same' in r['note']
    ctx['current_site']['site']='SITE_003'
    r=calculate(ctx,obs,base)
    assert r['mode']=='DIRECT_OBSERVED_ORIGIN' and r['trip_count']==2
    obs['shift_state']='D'
    assert calculate(ctx,obs,base)['mode']=='CONDITIONAL_START_SITE'
    for t in ctx['transitions']:t['energy_samples']=0
    assert calculate(ctx,obs,base)['mode']=='INSUFFICIENT'
    print('SELF-TEST PASS: full chains, no nearby-site merge, motion/stale guard, insufficient route evidence')

if __name__=='__main__':
    import sys
    if '--self-test' in sys.argv:self_test()
    else:print(json.dumps(preview(),indent=2))

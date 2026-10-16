"""GHOST measured-only Right Now readiness score, version 2.

No learned route, predicted charge, departure time, neural model, or future
weather is allowed in this calculation. Not a range/safety guarantee.
This file is intentionally pure; Ghost database access is in the wrapper.
"""
from __future__ import annotations
import math

VERSION = 'measured-only-v2.0'
SOC_FULL_CREDIT = 80.0  # Fixed day-to-day readiness reference, not departure target.


def finite(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (ValueError, TypeError, OverflowError):
        return None


def clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def _is_true(v):
    return v is True or v == 1 or str(v).lower() in ('true','yes','on')


def score_measured(m):
    """m contains only a *single measured Tesla telemetry row*."""
    m = m or {}
    soc = finite(m.get('battery_level'))
    pack_c = finite(m.get('battery_temp_c'))
    out_c = finite(m.get('outside_temp_c'))
    if soc is None or pack_c is None or not (0 <= soc <= 100) or not (-60 <= pack_c <= 100):
        return {
            'available': False, 'state': 'LEARNING', 'status': 'LEARNING',
            'headline': 'CURRENT MEASUREMENTS UNAVAILABLE',
            'reason': 'Measured SOC or pack temperature is unavailable/invalid; no numeric readiness claim.',
            'data_basis': VERSION,
            'score_breakdown': {'human_penalties': [], 'human_checks': []}
        }

    pack_f = 32.0 + pack_c * 1.8
    outside_f = None if out_c is None else 32.0 + out_c * 1.8

    # Three physically distinct terms. No model forecasts or predicted arrival.
    raw_soc = clamp(soc / SOC_FULL_CREDIT * 100)
    raw_thermal = 100.0 if pack_f >= 50 else clamp((pack_f - 20.0) * 100.0 / 30.0)

    system_penalties = []
    if _is_true(m.get('not_enough_power_to_heat')):
        system_penalties.append(('heat_power', 30.0, 'Vehicle reports insufficient power for battery heating.'))
    if _is_true(m.get('battery_heater_no_power')):
        system_penalties.append(('heater_power', 35.0, 'Battery heater reports no available power.'))
    t_min, t_max = finite(m.get('module_temp_min_c')), finite(m.get('module_temp_max_c'))
    spread_f = None
    if t_min is not None and t_max is not None and t_max >= t_min:
        spread_f = 1.8 * (t_max - t_min)
        if spread_f > 12:
            system_penalties.append(('temp_spread', 30.0, f'Module temperature spread {spread_f:.1f}°F is high.'))
        elif spread_f > 6:
            system_penalties.append(('temp_spread', 10.0, f'Module temperature spread {spread_f:.1f}°F is elevated.'))
    raw_system = clamp(100.0 - sum(p for _,p,_ in system_penalties))

    source_parts = [
        ('current_soc', 'Battery charge now', 55.0, raw_soc,
         f'Measured {soc:.0f}% SOC; full charge-level credit at {SOC_FULL_CREDIT:.0f}% (reference, not forecast).'),
        ('thermal', 'Battery temperature now', 35.0, raw_thermal,
         f'Measured pack {pack_f:.1f}°F; full thermal credit at 50°F.'),
        ('vehicle_state', 'Current vehicle conditions', 10.0, raw_system,
         'Measured heater-power constraints and pack module-temperature spread; no future-charge assumption.')
    ]
    components=[]
    human=[]
    for key,label,weight,raw,reason in source_parts:
        points=round(weight*raw/100.0,2)
        penalty=round(weight-points,2)
        components.append({'key':key,'label':label,'weight':weight,'raw_score':round(raw,2),'points':points,'penalty':penalty,'reason':reason})
        if penalty >= .025:
            value = f'{soc:.0f}%' if key=='current_soc' else f'{pack_f:.1f}°F' if key=='thermal' else 'CONDITION LIMIT'
            human.append({'key':'now_'+key,'label':label.upper(),'value':value,
                          'detail':reason,'severity':'bad' if penalty>=12 else 'warn',
                          'score_penalty':penalty,'score_source':key})

    base = round(clamp(sum(x['points'] for x in components)),2)
    state = 'READY' if base >= 75 else 'WATCH' if base >= 55 else 'ACTION'
    headline = 'CURRENT WINTER READY' if state=='READY' else 'CURRENT WINTER WATCH' if state=='WATCH' else 'CURRENT ACTION RECOMMENDED'
    checks=[{'key':'now_basis','label':'CURRENT SCORE BASIS','state':'MEASURED','severity':'info',
             'detail':'Actual battery SOC, pack temperature and present vehicle limitations only. No next departure, learned commute, charging forecast or future weather.',
             'value':'LIVE INPUTS'}]
    if soc < 40:
        checks.append({'key':'now_low_soc','label':'CURRENT BATTERY LEVEL','state':'WATCH','severity':'warn',
                       'detail':'Current charge is below 40%; range for a particular trip is not estimated by this score.',
                       'value':f'{soc:.0f}%'})
    if pack_f < 50:
        checks.append({'key':'now_cold_pack','label':'PACK TEMPERATURE','state':'COLD','severity':'warn',
                       'detail':'Current measured battery pack is below the 50°F readiness reference.',
                       'value':f'{pack_f:.1f}°F'})
    for key,_,why in system_penalties:
        checks.append({'key':'now_'+key,'label':'VEHICLE LIMITATION','state':'ACTIVE','severity':'warn',
                       'detail':why,'value':'ACTIVE'})
    charging_state = str(m.get('charging_state') or 'Unknown')
    checks.append({'key':'now_charge_status','label':'CHARGER STATUS','state':'OBSERVED','severity':'info',
                   'detail':'Observed charging state only; it does not add future charge or alter current score.',
                   'value':charging_state[:32]})
    if _is_true(m.get('battery_heater_on')):
        action='Battery heater is active right now.'
    elif pack_f<50:
        action=f'Measured battery pack is {pack_f:.1f}°F, below the 50°F readiness reference.'
    elif soc < 40:
        action=f'Pack temperature is ready; current battery charge is {soc:.0f}%.'
    else:
        action='Pack temperature is ready based on current measurements.'

    return {
        'available':True, 'score':base, 'state':state, 'status':state, 'headline':headline,
        'action':action, 'current_soc':round(soc,1), 'pack_f':round(pack_f,1),
        'outside_f':None if outside_f is None else round(outside_f,1),
        'reference_soc_drop_pp':None,'reference_arrival_soc':None,
        'reference_note':'This score does not predict trip consumption or future charging.',
        'data_basis':VERSION,
        'score_breakdown':{'max_score':100.0,'base_score_unrounded':base,
                           'rich_context_penalty':0.0,'score_unrounded':base,
                           'total_penalty':round(100.0-base,2),
                           'components':components,
                           'active_penalties':[x for x in components if x['penalty']>=.025],
                           'execution_penalties':[{'key':key,'points':round(10*p/100,2),'reason':why}
                                                  for key,p,why in system_penalties],
                           'human_penalties':human,'human_checks':checks},
    }

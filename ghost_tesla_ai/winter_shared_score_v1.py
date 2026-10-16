"""Shared READY NOW / NEXT DEPARTURE 100-point scale.

Next Departure evaluates forecast SOC/pack conditions through EXACTLY the same
measured-only readiness kernel Right Now already uses. Prediction uncertainty,
route reserve, charge reliability and model accuracy remain advisory, not scored.
No writes, Tesla calls, training or vehicle control.
"""
from __future__ import annotations
from .readiness_now_v2 import score_measured

VERSION='shared-score-v1'

def score_projected(departure_soc, departure_pack_f, departure_outside_f, current_telemetry):
    # Absence of a forecast is not permission to fabricate a good score.
    telemetry=dict(current_telemetry or {})
    synthetic={
        'battery_level':departure_soc,
        'battery_temp_c':None if departure_pack_f is None else (float(departure_pack_f)-32.0)/1.8,
        'outside_temp_c':None if departure_outside_f is None else (float(departure_outside_f)-32.0)/1.8,
        # Current observed limitations are only a PROVISIONAL baseline; future
        # limitation state is not itself forecast by Ghost.
        'battery_heater_no_power':telemetry.get('battery_heater_no_power'),
        'not_enough_power_to_heat':telemetry.get('not_enough_power_to_heat'),
        'module_temp_min_c':telemetry.get('module_temp_min_c'),
        'module_temp_max_c':telemetry.get('module_temp_max_c'),
        'battery_heater_on':telemetry.get('battery_heater_on'),
        'charging_state':telemetry.get('charging_state'),
    }
    result=score_measured(synthetic)
    if not result.get('available'):
        result['reason']='Departure SOC or departure pack-temperature prediction is unavailable. A comparable departure score cannot yet be calculated.'
        return result
    result['data_basis']=VERSION
    result['reference_note']='Same scoring formula as Right Now; forecast SOC and pack substituted. Current vehicle limits are provisional, NOT forecast.'
    breakdown=result['score_breakdown']
    for part in breakdown['components']:
        if part['key']=='current_soc':
            part['key']='departure_charge'
            part['label']='Predicted charge at departure'
            part['reason']=f"Predicted departure SOC {float(departure_soc):.1f}%; full SOC credit at fixed 80% reference. Same 55-point weight as Right Now."
        elif part['key']=='thermal':
            part['label']='Predicted pack temperature at departure'
            part['reason']=f"Predicted departure pack {float(departure_pack_f):.1f}°F; full thermal credit at 50°F. Same 35-point weight as Right Now."
        elif part['key']=='vehicle_state':
            part['label']='Observed vehicle condition baseline'
            part['reason']='Uses current observed heater-power/module-spread conditions as a provisional baseline. These conditions are not forecast and could change before departure.'
    # The caller rebuilds human-facing forecast-specific diagnostic cards; keep
    # no measured-now wording in the projected breakdown.
    breakdown['human_penalties']=[]
    breakdown['human_checks']=[]
    return result

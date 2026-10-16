"""Read-only Tessie-backed vehicle sensors page; exports no VIN, location or raw payload."""
from __future__ import annotations
import json,math,sqlite3,time
from flask import Blueprint,jsonify,render_template
bp=Blueprint('ghost_vehicle_sensors_v1',__name__)
DB='/var/lib/ghost-tesla-ai/ghost_ai.sqlite3'
BAR_TO_PSI=14.5037738

def dig(v,*keys):
    for k in keys:
        if not isinstance(v,dict):return None
        v=v.get(k)
    return v

def finite(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (ValueError,TypeError,OverflowError):return None

def bool_value(v):
    if isinstance(v,bool):return v
    if isinstance(v,(int,float)) and v in (0,1):return bool(v)
    return None

def tire(v):
    raw=finite(v)
    # Official Tesla vehicle_state.tpms_pressure_* unit = bar.
    # Reject implausible numbers rather than silently assume PSI or show stale zero.
    if raw is None or not (1.2<=raw<=5.0):return None
    return round(raw*BAR_TO_PSI,1)

def snapshot(row,now=None):
    now=now or time.time()
    raw=json.loads(row['raw_json'] or '{}')
    state=raw.get('state') or {}
    vehicle=state.get('vehicle_state') or {}
    climate=state.get('climate_state') or {}
    charge=state.get('charge_state') or {}
    tires={k:tire(vehicle.get('tpms_pressure_'+k)) for k in ('fl','fr','rl','rr')}
    valid=[v for v in tires.values() if v is not None]
    spread=round(max(valid)-min(valid),1) if len(valid)==4 else None
    age_s=max(0,now-float(row['ts']))
    lock=bool_value(vehicle.get('locked'))
    sentry=bool_value(vehicle.get('sentry_mode'))
    if sentry is None:sentry=None if row['sentry_mode'] is None else bool(int(row['sentry_mode']))
    port=bool_value(charge.get('charge_port_door_open'))
    fan=finite(climate.get('fan_status'))
    return {
      'ok':True, 'at':float(row['ts']), 'age_seconds':round(age_s), 'stale':age_s>600,
      'source':'Tessie saved /state (read-only)',
      'tires_psi':tires,'tire_units':'PSI (Tesla TPMS bar x 14.5038)',
      'tire_spread_psi':spread,'tire_spread_check':spread is not None and spread>=5.0,
      'sentry_mode':'UNKNOWN' if sentry is None else 'ON' if sentry else 'OFF',
      'locked':'UNKNOWN' if lock is None else 'LOCKED' if lock else 'UNLOCKED',
      'charge_port':'UNKNOWN' if port is None else 'OPEN' if port else 'CLOSED',
      'climate_fan':'UNKNOWN' if fan is None else 'RUNNING' if fan>0 else 'OFF',
      'fan_status_raw':fan,
      'charge_limit_soc':finite(charge.get('charge_limit_soc')),
      'charging_state':str(charge.get('charging_state') or 'UNKNOWN'),
      'note':'TPMS reports last measured values, which can remain unchanged while parked. This endpoint does not wake the car or expose precise position.'
    }

@bp.get('/vehicle-sensors')
def vehicle_sensors_page():
    return render_template('ghost_vehicle_sensors.html')

@bp.get('/api/vehicle-sensors/v1')
def vehicle_sensors_data():
    try:
        con=sqlite3.connect('file:'+DB+'?mode=ro',uri=True,timeout=6)
        con.row_factory=sqlite3.Row
        con.execute('PRAGMA query_only=ON')
        try:
            row=con.execute('SELECT ts,raw_json,sentry_mode FROM telemetry ORDER BY ts DESC LIMIT 1').fetchone()
        finally:con.close()
        if row is None:return jsonify({'ok':False,'error':'No vehicle telemetry yet'}),503
        return jsonify(snapshot(row))
    except Exception as exc:
        return jsonify({'ok':False,'error':'Sensor data unavailable','kind':type(exc).__name__}),503

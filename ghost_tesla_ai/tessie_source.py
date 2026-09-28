from __future__ import annotations
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from . import config

MI_TO_KM = 1.609344

class TessieError(RuntimeError):
    pass

def _unwrap(payload: Any) -> Any:
    # Tessie normally returns objects/lists directly, but tolerate wrappers.
    if isinstance(payload, dict):
        for key in ('response', 'data'):
            if key in payload and len(payload) == 1:
                return payload[key]
    return payload

def _dig(d: Any, *path: str):
    cur = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur

def _first(d: Any, paths: list[tuple[str, ...]], default=None):
    for path in paths:
        v = _dig(d, *path)
        if v is not None:
            return v
    return default

def _recursive_find(obj: Any, names: set[str]):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in names and v is not None:
                return v
        for v in obj.values():
            found = _recursive_find(v, names)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _recursive_find(v, names)
            if found is not None:
                return found
    return None

def _num(v):
    try:
        if v is None or v == '': return None
        return float(v)
    except Exception:
        return None

def _bool(v):
    if v is None: return None
    if isinstance(v, bool): return 1 if v else 0
    if isinstance(v, (int, float)): return 1 if v else 0
    return 1 if str(v).strip().lower() in {'1','true','yes','on','connected','charging'} else 0

def _normalize_state(v):
    if v is None: return None
    s = str(v).strip().lower()
    return {'awake':'online','sleep':'asleep','offline':'asleep','waiting_for_sleep':'online'}.get(s, s)

class TessieClient:
    def __init__(self, token: str | None = None):
        self.token = (token or config.tessie_token()).strip()
        if not self.token:
            raise TessieError('Tessie token is not configured')
        self.base = config.TESSIE_BASE_URL
        self.vin = config.TESSIE_VIN or None

    def get(self, path: str, params: dict[str, Any] | None = None, timeout: int | None = None):
        url = self.base + path
        if params:
            q = urllib.parse.urlencode({k:v for k,v in params.items() if v is not None})
            if q: url += '?' + q
        req = urllib.request.Request(url, headers={
            'Authorization': f'Bearer {self.token}',
            'Accept': 'application/json',
            'User-Agent': 'GhostTeslaAI/0.8.27.6',
        })
        try:
            with urllib.request.urlopen(req, timeout=(timeout or config.TESSIE_TIMEOUT_SECONDS)) as r:
                raw = r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'replace')[:500]
            raise TessieError(f'HTTP {e.code}: {body or e.reason}') from e
        except urllib.error.URLError as e:
            raise TessieError(f'network error: {e.reason}') from e
        try:
            return _unwrap(json.loads(raw))
        except Exception as e:
            raise TessieError(f'invalid JSON from Tessie: {e}') from e

    def discover_vehicle(self):
        payload = self.get('/vehicles')
        vehicles = payload
        if isinstance(payload, dict):
            vehicles = payload.get('vehicles') or payload.get('results') or payload.get('data') or payload
        if isinstance(vehicles, dict):
            vehicles = list(vehicles.values())
        if not isinstance(vehicles, list) or not vehicles:
            raise TessieError('No vehicles returned by /vehicles')
        selected = None
        if self.vin:
            selected = next((v for v in vehicles if isinstance(v, dict) and str(v.get('vin','')).upper() == self.vin.upper()), None)
            if selected is None:
                raise TessieError(f'Configured VIN {self.vin} was not returned by Tessie')
        else:
            selected = next((v for v in vehicles if isinstance(v, dict) and v.get('vin')), vehicles[0])
            if isinstance(selected, dict):
                self.vin = str(selected.get('vin') or '').strip() or None
        if not self.vin:
            raise TessieError('Could not determine VIN from Tessie /vehicles response')
        return selected

    def state(self):
        if not self.vin:
            self.discover_vehicle()
        return self.get(f'/{urllib.parse.quote(self.vin)}/state', {'use_cache': 'true' if config.TESSIE_USE_CACHE else 'false'})

    def history(self, from_ts: float, to_ts: float, interval: int = 300):
        if not self.vin:
            self.discover_vehicle()
        return self.get(f'/{urllib.parse.quote(self.vin)}/states', {
            'from': int(from_ts), 'to': int(to_ts), 'interval': int(interval),
            'condense': 'false', 'distance_format': 'mi', 'temperature_format': 'c',
        }, timeout=max(config.TESSIE_TIMEOUT_SECONDS, 120))

    def battery(self):
        if not self.vin:
            self.discover_vehicle()
        return self.get(f'/{urllib.parse.quote(self.vin)}/battery')

    def status(self):
        if not self.vin:
            self.discover_vehicle()
        return self.get(f'/{urllib.parse.quote(self.vin)}/status')

def parse_state(state_payload: Any, battery_payload: Any = None, vin: str = '') -> dict[str, Any]:
    state_payload = _unwrap(state_payload)
    if not isinstance(state_payload, dict):
        raise TessieError('Tessie state response was not an object')

    charge = state_payload.get('charge_state') if isinstance(state_payload.get('charge_state'), dict) else {}
    climate = state_payload.get('climate_state') if isinstance(state_payload.get('climate_state'), dict) else {}
    drive = state_payload.get('drive_state') if isinstance(state_payload.get('drive_state'), dict) else {}
    vehicle = state_payload.get('vehicle_state') if isinstance(state_payload.get('vehicle_state'), dict) else {}

    # Tesla state responses traditionally use miles for range/odometer and mph for speed.
    rated_km = _num(_first(state_payload, [('charge_state','battery_range_km'), ('battery_range_km',)]))
    if rated_km is None:
        miles = _num(_first(state_payload, [('charge_state','battery_range'), ('battery_range',)]))
        rated_km = None if miles is None else miles * MI_TO_KM
    ideal_km = _num(_first(state_payload, [('charge_state','ideal_battery_range_km'), ('ideal_battery_range_km',)]))
    if ideal_km is None:
        miles = _num(_first(state_payload, [('charge_state','ideal_battery_range'), ('ideal_battery_range',)]))
        ideal_km = None if miles is None else miles * MI_TO_KM
    est_km = _num(_first(state_payload, [('charge_state','est_battery_range_km'), ('est_battery_range_km',)]))
    if est_km is None:
        miles = _num(_first(state_payload, [('charge_state','est_battery_range'), ('est_battery_range',)]))
        est_km = None if miles is None else miles * MI_TO_KM

    speed_kmh = _num(_first(state_payload, [('drive_state','speed_kmh'), ('speed_kmh',)]))
    if speed_kmh is None:
        mph = _num(_first(state_payload, [('drive_state','speed'), ('speed',)]))
        speed_kmh = None if mph is None else mph * MI_TO_KM

    odometer_km = _num(_first(state_payload, [('vehicle_state','odometer_km'), ('odometer_km',)]))
    if odometer_km is None:
        miles = _num(_first(state_payload, [('vehicle_state','odometer'), ('odometer',)]))
        odometer_km = None if miles is None else miles * MI_TO_KM

    charging_state = _first(state_payload, [('charge_state','charging_state'), ('charging_state',)])
    plugged = _first(state_payload, [('charge_state','plugged_in'), ('plugged_in',)])
    if plugged is None and charging_state is not None:
        plugged = str(charging_state).lower() not in {'disconnected', 'nopower'}

    batt_temp = None
    if battery_payload is not None:
        batt_temp = _num(_recursive_find(battery_payload, {'battery_temperature','battery_temp','pack_temperature','pack_temp','temperature_c'}))
    if batt_temp is None:
        batt_temp = _num(_recursive_find(state_payload, {'battery_temperature','battery_temp','pack_temperature','pack_temp'}))

    module_min = _num(_recursive_find(state_payload, {'module_temp_min','module_temperature_min'}))
    module_max = _num(_recursive_find(state_payload, {'module_temp_max','module_temperature_max'}))
    # Tessie's historical state stream exposes module min/max. Their midpoint is
    # a stable pack-temperature proxy and lets the thermal model train even when
    # the separate battery endpoint does not expose a single pack temperature.
    if batt_temp is None and module_min is not None and module_max is not None:
        batt_temp = (module_min + module_max) / 2.0

    timestamp = _num(_first(state_payload, [('timestamp',), ('vehicle_state','timestamp'), ('drive_state','timestamp'), ('charge_state','timestamp')]))
    if timestamp and timestamp > 10_000_000_000:
        timestamp /= 1000.0

    raw_state = _first(state_payload, [('state',), ('status',), ('vehicle_state','state')])
    power_kw = _num(_first(state_payload, [('drive_state','power'), ('power',)]))

    sample = {
        # Use the vehicle's own timestamp when available. This prevents cached
        # asleep-state responses from creating fake minute-by-minute training rows.
        'ts': timestamp or time.time(),
        'source': 'tessie_api',
        'car_id': vin or 'tessie',
        'state': _normalize_state(raw_state),
        'battery_level': _num(_first(state_payload, [('charge_state','battery_level'), ('battery_level',)])),
        'usable_battery_level': _num(_first(state_payload, [('charge_state','usable_battery_level'), ('usable_battery_level',)])),
        'rated_range_km': rated_km,
        'ideal_range_km': ideal_km,
        'est_range_km': est_km,
        'outside_temp_c': _num(_first(state_payload, [('climate_state','outside_temp'), ('outside_temp',)])),
        'inside_temp_c': _num(_first(state_payload, [('climate_state','inside_temp'), ('inside_temp',)])),
        'battery_temp_c': batt_temp,
        'power_kw': power_kw,
        'speed_kmh': speed_kmh,
        'odometer_km': odometer_km,
        'plugged_in': _bool(plugged),
        'charging_state': charging_state,
        'charge_energy_added_kwh': _num(_first(state_payload, [('charge_state','charge_energy_added'), ('charge_energy_added',)])),
        'charger_power_kw': _num(_first(state_payload, [('charge_state','charger_power'), ('charger_power',)])),
        'charger_voltage': _num(_first(state_payload, [('charge_state','charger_voltage'), ('charger_voltage',)])),
        'charger_actual_current': _num(_first(state_payload, [('charge_state','charger_actual_current'), ('charger_actual_current',)])),
        'climate_on': _bool(_first(state_payload, [('climate_state','is_climate_on'), ('is_climate_on',)])),
        'preconditioning': _bool(_first(state_payload, [('climate_state','is_preconditioning'), ('is_preconditioning',)])),
        'shift_state': _first(state_payload, [('drive_state','shift_state'), ('shift_state',)]),
        'battery_heater_on': _bool(_first(state_payload, [('climate_state','battery_heater'), ('battery_heater_on',), ('battery_heater',)])),
        'lifetime_energy_used_kwh': _num(_first(state_payload, [('lifetime_energy_used',), ('vehicle_state','lifetime_energy_used')])),
        'energy_remaining_kwh': _num(_first(state_payload, [('energy_remaining',), ('charge_state','energy_remaining')])),
        'pack_current_a': _num(_first(state_payload, [('pack_current',), ('charge_state','pack_current')])),
        'pack_voltage_v': _num(_first(state_payload, [('pack_voltage',), ('charge_state','pack_voltage')])),
        'module_temp_min_c': module_min,
        'module_temp_max_c': module_max,
    }
    sample['_vehicle_timestamp'] = timestamp
    sample['raw_json'] = json.dumps({'state': state_payload, 'battery': battery_payload}, separators=(',', ':'), default=str)
    return sample

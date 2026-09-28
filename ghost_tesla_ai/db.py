from __future__ import annotations
import json, math, sqlite3, time
from pathlib import Path
from . import config

SCHEMA = r'''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS telemetry (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  source TEXT NOT NULL DEFAULT 'unknown',
  car_id TEXT NOT NULL DEFAULT '1',
  state TEXT,
  battery_level REAL,
  usable_battery_level REAL,
  rated_range_km REAL,
  ideal_range_km REAL,
  est_range_km REAL,
  outside_temp_c REAL,
  inside_temp_c REAL,
  battery_temp_c REAL,
  power_kw REAL,
  speed_kmh REAL,
  odometer_km REAL,
  plugged_in INTEGER,
  charging_state TEXT,
  charge_energy_added_kwh REAL,
  charger_power_kw REAL,
  charger_voltage REAL,
  charger_actual_current REAL,
  climate_on INTEGER,
  preconditioning INTEGER,
  shift_state TEXT,
  battery_heater_on INTEGER,
  lifetime_energy_used_kwh REAL,
  energy_remaining_kwh REAL,
  pack_current_a REAL,
  pack_voltage_v REAL,
  module_temp_min_c REAL,
  module_temp_max_c REAL,
  pack_power_kw REAL,
  charge_input_kw REAL,
  module_temp_spread_c REAL,
  pack_ambient_delta_c REAL,
  raw_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_telemetry_ts ON telemetry(ts);
CREATE INDEX IF NOT EXISTS idx_telemetry_car_ts ON telemetry(car_id, ts);
CREATE INDEX IF NOT EXISTS idx_telemetry_source_ts ON telemetry(source, ts);

CREATE TABLE IF NOT EXISTS model_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  model_name TEXT NOT NULL,
  backend TEXT NOT NULL,
  generation INTEGER NOT NULL,
  trained_at REAL NOT NULL,
  rows_total INTEGER NOT NULL,
  rows_train INTEGER NOT NULL,
  rows_test INTEGER NOT NULL,
  mae REAL,
  rmse REAL,
  r2 REAL,
  promoted INTEGER NOT NULL DEFAULT 0,
  artifact_path TEXT,
  features_json TEXT,
  target TEXT,
  horizon_minutes INTEGER,
  notes TEXT,
  validation_strategy TEXT,
  test_start_ts REAL,
  test_end_ts REAL,
  regime TEXT,
  feature_version TEXT
);
CREATE INDEX IF NOT EXISTS idx_model_runs_name ON model_runs(model_name, trained_at DESC);

CREATE TABLE IF NOT EXISTS challenger_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  model_name TEXT NOT NULL,
  backend TEXT NOT NULL,
  generation INTEGER NOT NULL,
  trained_at REAL NOT NULL,
  rows_total INTEGER NOT NULL,
  rows_train INTEGER NOT NULL,
  rows_test INTEGER NOT NULL,
  mae REAL,
  rmse REAL,
  r2 REAL,
  artifact_path TEXT,
  features_json TEXT,
  validation_strategy TEXT,
  feature_version TEXT,
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_challenger_model ON challenger_runs(model_name, trained_at DESC);


CREATE TABLE IF NOT EXISTS event_model_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  model_name TEXT NOT NULL,
  generation INTEGER NOT NULL,
  trained_at REAL NOT NULL,
  rows_total INTEGER NOT NULL,
  rows_train INTEGER NOT NULL,
  rows_test INTEGER NOT NULL,
  mae REAL,
  rmse REAL,
  r2 REAL,
  promoted INTEGER NOT NULL DEFAULT 0,
  artifact_path TEXT,
  features_json TEXT,
  target TEXT,
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_event_model_runs ON event_model_runs(model_name, trained_at DESC);

CREATE TABLE IF NOT EXISTS predictions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  model_name TEXT NOT NULL,
  generation INTEGER,
  horizon_minutes INTEGER,
  predicted_value REAL,
  actual_value REAL,
  abs_error REAL,
  source_telemetry_id INTEGER
);

CREATE TABLE IF NOT EXISTS prediction_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  predicted_at REAL NOT NULL,
  target_ts REAL NOT NULL,
  model_name TEXT NOT NULL,
  generation INTEGER NOT NULL,
  horizon_minutes INTEGER NOT NULL,
  target_field TEXT NOT NULL,
  predicted_value REAL NOT NULL,
  actual_value REAL,
  signed_error REAL,
  abs_error REAL,
  source_telemetry_id INTEGER NOT NULL,
  actual_telemetry_id INTEGER,
  resolved_at REAL,
  resolution_gap_seconds REAL,
  status TEXT NOT NULL DEFAULT 'pending',
  UNIQUE(model_name, generation, source_telemetry_id)
);
CREATE INDEX IF NOT EXISTS idx_prediction_audit_due ON prediction_audit(status, target_ts);
CREATE INDEX IF NOT EXISTS idx_prediction_audit_model ON prediction_audit(model_name, resolved_at DESC);

CREATE TABLE IF NOT EXISTS vehicle_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  car_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  start_ts REAL NOT NULL,
  end_ts REAL NOT NULL,
  duration_min REAL,
  source_points INTEGER,
  start_soc REAL,
  end_soc REAL,
  soc_change REAL,
  start_pack_c REAL,
  end_pack_c REAL,
  pack_change_c REAL,
  avg_pack_c REAL,
  avg_outside_c REAL,
  min_outside_c REAL,
  max_outside_c REAL,
  start_odometer_km REAL,
  end_odometer_km REAL,
  distance_km REAL,
  energy_used_kwh REAL,
  energy_remaining_delta_kwh REAL,
  avg_pack_power_kw REAL,
  avg_charge_power_kw REAL,
  charge_energy_added_kwh REAL,
  wh_per_mile REAL,
  metadata_json TEXT,
  UNIQUE(car_id,event_type,start_ts,end_ts)
);
CREATE INDEX IF NOT EXISTS idx_events_type_start ON vehicle_events(event_type,start_ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_car_start ON vehicle_events(car_id,start_ts DESC);

CREATE TABLE IF NOT EXISTS readiness_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at REAL NOT NULL,
  car_id TEXT,
  departure_ts REAL,
  status TEXT,
  confidence REAL,
  current_soc REAL,
  predicted_departure_soc REAL,
  predicted_arrival_soc REAL,
  current_pack_f REAL,
  predicted_departure_pack_f REAL,
  suggested_precondition_start_ts REAL,
  payload_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_readiness_created ON readiness_snapshots(created_at DESC);


CREATE TABLE IF NOT EXISTS neural_v4_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  model_name TEXT NOT NULL,
  backend TEXT NOT NULL,
  generation INTEGER NOT NULL,
  trained_at REAL NOT NULL,
  rows_total INTEGER NOT NULL,
  rows_train INTEGER NOT NULL,
  rows_test INTEGER NOT NULL,
  artifact_path TEXT NOT NULL,
  architecture TEXT,
  window_minutes INTEGER,
  step_minutes INTEGER,
  input_features_json TEXT,
  targets_json TEXT,
  metrics_json TEXT,
  baseline_json TEXT,
  validation_strategy TEXT,
  best_epoch INTEGER,
  torch_version TEXT,
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_neural_v4_runs ON neural_v4_runs(generation DESC);

CREATE TABLE IF NOT EXISTS neural_v4_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  predicted_at REAL NOT NULL,
  target_ts REAL NOT NULL,
  generation INTEGER NOT NULL,
  target_name TEXT NOT NULL,
  target_field TEXT NOT NULL,
  horizon_minutes INTEGER NOT NULL,
  predicted_value REAL NOT NULL,
  baseline_predicted_value REAL,
  baseline_model_name TEXT,
  baseline_generation INTEGER,
  actual_value REAL,
  signed_error REAL,
  abs_error REAL,
  baseline_signed_error REAL,
  baseline_abs_error REAL,
  source_telemetry_id INTEGER NOT NULL,
  actual_telemetry_id INTEGER,
  resolved_at REAL,
  resolution_gap_seconds REAL,
  status TEXT NOT NULL DEFAULT 'pending',
  UNIQUE(generation,target_name,source_telemetry_id)
);
CREATE INDEX IF NOT EXISTS idx_neural_v4_audit_due ON neural_v4_audit(status,target_ts);
CREATE INDEX IF NOT EXISTS idx_neural_v4_audit_target ON neural_v4_audit(target_name,resolved_at DESC);
CREATE INDEX IF NOT EXISTS idx_neural_v4_audit_generation ON neural_v4_audit(generation,target_name,predicted_at DESC);

CREATE TABLE IF NOT EXISTS neural_v4_governor (
  generation INTEGER PRIMARY KEY,
  stage TEXT NOT NULL DEFAULT 'TRAINED',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  shadow_started_at REAL,
  truth_qualified_at REAL,
  canary_started_at REAL,
  production_started_at REAL,
  rolled_back_at REAL,
  holdout_pass INTEGER NOT NULL DEFAULT 0,
  truth_pass INTEGER NOT NULL DEFAULT 0,
  canary_pass INTEGER NOT NULL DEFAULT 0,
  rollback_guard TEXT,
  reason TEXT,
  payload_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_neural_v4_governor_stage ON neural_v4_governor(stage,updated_at DESC);

CREATE TABLE IF NOT EXISTS neural_v4_governor_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  generation INTEGER NOT NULL,
  from_stage TEXT,
  to_stage TEXT,
  event TEXT NOT NULL,
  detail_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_neural_v4_governor_events ON neural_v4_governor_events(generation,ts DESC);

CREATE TABLE IF NOT EXISTS system_state (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at REAL NOT NULL
);
'''

TELEMETRY_MIGRATIONS = {
    'shift_state': 'TEXT',
    'battery_heater_on': 'INTEGER',
    'lifetime_energy_used_kwh': 'REAL',
    'energy_remaining_kwh': 'REAL',
    'pack_current_a': 'REAL',
    'pack_voltage_v': 'REAL',
    'module_temp_min_c': 'REAL',
    'module_temp_max_c': 'REAL',
    'pack_power_kw': 'REAL',
    'charge_input_kw': 'REAL',
    'module_temp_spread_c': 'REAL',
    'pack_ambient_delta_c': 'REAL',
}

MODEL_RUN_MIGRATIONS = {
    'validation_strategy':'TEXT',
    'test_start_ts':'REAL',
    'test_end_ts':'REAL',
    'regime':'TEXT',
    'feature_version':'TEXT',
}

NEURAL_V4_AUDIT_MIGRATIONS = {
    'baseline_predicted_value':'REAL',
    'baseline_model_name':'TEXT',
    'baseline_generation':'INTEGER',
    'baseline_signed_error':'REAL',
    'baseline_abs_error':'REAL',
}

TELEMETRY_FIELDS = [
  'ts','source','car_id','state','battery_level','usable_battery_level','rated_range_km','ideal_range_km','est_range_km',
  'outside_temp_c','inside_temp_c','battery_temp_c','power_kw','speed_kmh','odometer_km','plugged_in','charging_state',
  'charge_energy_added_kwh','charger_power_kw','charger_voltage','charger_actual_current','climate_on','preconditioning',
  'shift_state','battery_heater_on','lifetime_energy_used_kwh','energy_remaining_kwh','pack_current_a','pack_voltage_v',
  'module_temp_min_c','module_temp_max_c','pack_power_kw','charge_input_kw','module_temp_spread_c','pack_ambient_delta_c','raw_json'
]

LOCK_WORDS = ('database is locked', 'database table is locked', 'database is busy')

def _is_lock_error(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and any(w in str(exc).lower() for w in LOCK_WORDS)

def _retry_write(fn, attempts: int = 7):
    delay = 0.10
    last = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last = exc
            if not _is_lock_error(exc) or attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2.0, 2.0)
    raise last

def connect(path: Path | None = None) -> sqlite3.Connection:
    p = path or config.DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=60)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA busy_timeout=60000')
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA synchronous=NORMAL')
    con.execute('PRAGMA wal_autocheckpoint=1000')
    return con

def _migrate_table(con: sqlite3.Connection, table: str, migrations: dict[str,str]) -> None:
    existing = {r['name'] for r in con.execute(f'PRAGMA table_info({table})').fetchall()}
    for name, typ in migrations.items():
        if name not in existing:
            con.execute(f'ALTER TABLE {table} ADD COLUMN {name} {typ}')

def _migrate(con: sqlite3.Connection) -> None:
    _migrate_table(con,'telemetry',TELEMETRY_MIGRATIONS)
    _migrate_table(con,'model_runs',MODEL_RUN_MIGRATIONS)
    _migrate_table(con,'neural_v4_audit',NEURAL_V4_AUDIT_MIGRATIONS)

def init_db(path: Path | None = None) -> None:
    def op():
        with connect(path) as con:
            con.executescript(SCHEMA)
            _migrate(con)
    _retry_write(op)

def set_state(key: str, value) -> None:
    payload = value if isinstance(value, str) else json.dumps(value, separators=(',', ':'))
    def op():
        with connect() as con:
            con.execute('INSERT INTO system_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at', (key, payload, time.time()))
    _retry_write(op)

def get_state(key: str, default=None):
    with connect() as con:
        row = con.execute('SELECT value FROM system_state WHERE key=?', (key,)).fetchone()
    if not row: return default
    v = row['value']
    try: return json.loads(v)
    except Exception: return v

def _num(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None

def enrich_sample(sample: dict) -> dict:
    """Add deterministic local features without changing raw cloud telemetry."""
    s=dict(sample)
    pv=_num(s.get('pack_voltage_v')); pa=_num(s.get('pack_current_a'))
    if s.get('pack_power_kw') is None and pv is not None and pa is not None:
        s['pack_power_kw']=round(pv*pa/1000.0,6)
    cv=_num(s.get('charger_voltage')); ca=_num(s.get('charger_actual_current')); cp=_num(s.get('charger_power_kw'))
    if s.get('charge_input_kw') is None:
        if cv is not None and ca is not None:
            s['charge_input_kw']=round(cv*ca/1000.0,6)
        elif cp is not None:
            s['charge_input_kw']=cp
    lo=_num(s.get('module_temp_min_c')); hi=_num(s.get('module_temp_max_c'))
    if s.get('module_temp_spread_c') is None and lo is not None and hi is not None:
        s['module_temp_spread_c']=round(max(0.0,hi-lo),6)
    pack=_num(s.get('battery_temp_c')); out=_num(s.get('outside_temp_c'))
    if s.get('pack_ambient_delta_c') is None and pack is not None and out is not None:
        s['pack_ambient_delta_c']=round(pack-out,6)
    return s

def insert_telemetry(sample: dict) -> int:
    sample=enrich_sample(sample)
    vals = [sample.get(f) for f in TELEMETRY_FIELDS]
    def op():
        with connect() as con:
            cur = con.execute(f"INSERT INTO telemetry({','.join(TELEMETRY_FIELDS)}) VALUES({','.join('?' for _ in TELEMETRY_FIELDS)})", vals)
            return int(cur.lastrowid)
    return int(_retry_write(op))

def latest_car_id() -> str | None:
    with connect() as con:
        row = con.execute("SELECT car_id FROM telemetry WHERE car_id IS NOT NULL AND car_id<>'' ORDER BY ts DESC LIMIT 1").fetchone()
    return None if not row else str(row['car_id'])

def backfill_derived(batch_size: int = 1000) -> dict:
    """Populate deterministic v0.3 derived columns for already stored history."""
    init_db(); updated=0; scanned=0
    with connect() as con:
        last=0
        while True:
            rows=con.execute('''SELECT id,pack_voltage_v,pack_current_a,charger_voltage,charger_actual_current,charger_power_kw,
                                module_temp_min_c,module_temp_max_c,battery_temp_c,outside_temp_c,
                                pack_power_kw,charge_input_kw,module_temp_spread_c,pack_ambient_delta_c
                                FROM telemetry WHERE id>? ORDER BY id LIMIT ?''',(last,int(batch_size))).fetchall()
            if not rows: break
            for r in rows:
                last=int(r['id']); scanned+=1
                d=enrich_sample(dict(r)); sets=[]; vals=[]
                for f in ('pack_power_kw','charge_input_kw','module_temp_spread_c','pack_ambient_delta_c'):
                    if r[f] is None and d.get(f) is not None:
                        sets.append(f'{f}=?'); vals.append(d[f])
                if sets:
                    vals.append(last); con.execute(f"UPDATE telemetry SET {','.join(sets)} WHERE id=?",vals); updated+=1
            con.commit()
    out={'scanned':scanned,'updated':updated,'finished_at':time.time()}
    set_state('derived_backfill',out)
    return out

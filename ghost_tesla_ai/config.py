from __future__ import annotations
import os
from pathlib import Path

DEFAULT_ENV = Path('/etc/ghost-tesla-ai/ghost.env')

def _load_env_file(path: Path = DEFAULT_ENV) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return out

_FILE = _load_env_file()

def get(name: str, default: str = '') -> str:
    return os.environ.get(name, _FILE.get(name, default))

def get_int(name: str, default: int) -> int:
    try:
        return int(get(name, str(default)))
    except Exception:
        return default

def get_float(name: str, default: float) -> float:
    try:
        return float(get(name, str(default)))
    except Exception:
        return default

def get_bool(name: str, default: bool = False) -> bool:
    return get(name, '1' if default else '0').lower() in {'1','true','yes','on'}

DATA_DIR = Path(get('GHOST_AI_DATA_DIR', '/var/lib/ghost-tesla-ai'))
DB_PATH = Path(get('GHOST_AI_DB', str(DATA_DIR / 'ghost_ai.sqlite3')))
MODEL_DIR = Path(get('GHOST_AI_MODEL_DIR', str(DATA_DIR / 'models')))
HOST = get('GHOST_AI_HOST', '0.0.0.0')
PORT = get_int('GHOST_AI_PORT', 8766)

# Source selection: auto = Tessie when a token exists, otherwise TeslaMate MQTT.
SOURCE_MODE = get('SOURCE_MODE', 'auto').strip().lower()

MQTT_HOST = get('MQTT_HOST', '127.0.0.1')
MQTT_PORT = get_int('MQTT_PORT', 1883)
MQTT_USER = get('MQTT_USER', '')
MQTT_PASSWORD = get('MQTT_PASSWORD', '')
MQTT_TLS = get_bool('MQTT_TLS', False)
CAR_ID = get('TESLAMATE_CAR_ID', '1')

TESSIE_BASE_URL = get('TESSIE_BASE_URL', 'https://api.tessie.com').rstrip('/')
TESSIE_TOKEN_FILE = Path(get('TESSIE_TOKEN_FILE', '/etc/ghost-tesla-ai/tessie.token'))
TESSIE_VIN = get('TESSIE_VIN', '').strip()
TESSIE_POLL_SECONDS = max(30, get_int('TESSIE_POLL_SECONDS', 60))
TESSIE_TIMEOUT_SECONDS = max(5, get_int('TESSIE_TIMEOUT_SECONDS', 20))
TESSIE_USE_CACHE = get_bool('TESSIE_USE_CACHE', True)
TESSIE_FETCH_BATTERY_WHEN_ACTIVE = get_bool('TESSIE_FETCH_BATTERY_WHEN_ACTIVE', True)


# v0.8.26 EcoFlow RIVER 3 top-bar telemetry. Credentials stay server-side and
# are never sent to the browser. The US Open API host is the default but can
# be overridden in ghost.env when EcoFlow assigns a different regional host.
ECOFLOW_ACCESS_KEY = get('ECOFLOW_ACCESS_KEY', '').strip()
ECOFLOW_SECRET_KEY = get('ECOFLOW_SECRET_KEY', '').strip()
ECOFLOW_RIVER3_SN = get('ECOFLOW_RIVER3_SN', '').strip()
ECOFLOW_API_BASE = get('ECOFLOW_API_BASE', 'https://api-a.ecoflow.com').rstrip('/')
ECOFLOW_POLL_SECONDS = max(20, get_int('ECOFLOW_POLL_SECONDS', 30))
ECOFLOW_TIMEOUT_SECONDS = max(2, get_int('ECOFLOW_TIMEOUT_SECONDS', 5))
ECOFLOW_APP_CREDENTIALS_FILE = get('ECOFLOW_APP_CREDENTIALS_FILE', '/var/lib/ghost-tesla-ai/ecoflow_app.json').strip()
ECOFLOW_MQTT_RECERT_SECONDS = max(300, get_int('ECOFLOW_MQTT_RECERT_SECONDS', 540))
ECOFLOW_MQTT_KEEPALIVE_SECONDS = max(15, get_int('ECOFLOW_MQTT_KEEPALIVE_SECONDS', 20))

SNAPSHOT_SECONDS = max(15, get_int('SNAPSHOT_SECONDS', 60))
MIN_TRAIN_ROWS = max(50, get_int('MIN_TRAIN_ROWS', 120))
TRAIN_LOOKBACK_DAYS = max(7, get_int('TRAIN_LOOKBACK_DAYS', 180))
AUTO_PROMOTE = get_bool('AUTO_PROMOTE', True)
PROMOTE_IMPROVEMENT = max(0.0, get_float('PROMOTE_IMPROVEMENT', 0.02))

def tessie_token() -> str:
    env = get('TESSIE_TOKEN', '').strip()
    if env:
        return env
    try:
        return TESSIE_TOKEN_FILE.read_text().strip()
    except FileNotFoundError:
        return ''

# v0.3 Event Intelligence / challenger settings
EVENT_LOOKBACK_DAYS = max(7, get_int('EVENT_LOOKBACK_DAYS', 60))
EVENT_MAX_GAP_MINUTES = max(5, get_int('EVENT_MAX_GAP_MINUTES', 20))
COLD_SOAK_THRESHOLD_C = get_float('COLD_SOAK_THRESHOLD_C', 10.0)  # 50 F policy threshold
READINESS_TARGET_PACK_F = get_float('READINESS_TARGET_PACK_F', 50.0)
READINESS_MIN_ARRIVAL_SOC = get_float('READINESS_MIN_ARRIVAL_SOC', 20.0)
# EXPECTED_DEPARTURE is now a fading schedule seed, not a permanent override.
# It helps cold-start GHOST around the known work routine while observed drive events
# progressively take over departure timing.
EXPECTED_DEPARTURE = get('EXPECTED_DEPARTURE', '').strip()
EXPECTED_DEPARTURE_WINDOW_MINUTES = max(30, get_int('EXPECTED_DEPARTURE_WINDOW_MINUTES', 90))
DEPARTURE_LEARNING_ENABLED = get_bool('DEPARTURE_LEARNING_ENABLED', True)
DEPARTURE_LOOKBACK_DAYS = max(14, get_int('DEPARTURE_LOOKBACK_DAYS', 90))
DEPARTURE_BIN_MINUTES = max(5, min(30, get_int('DEPARTURE_BIN_MINUTES', 15)))
DEPARTURE_KERNEL_MINUTES = max(20, min(120, get_int('DEPARTURE_KERNEL_MINUTES', 45)))
DEPARTURE_MIN_DRIVE_KM = max(0.1, get_float('DEPARTURE_MIN_DRIVE_KM', 0.35))
DEPARTURE_SECONDARY_TRIP_WEIGHT = max(0.05, min(1.0, get_float('DEPARTURE_SECONDARY_TRIP_WEIGHT', 0.35)))
DEPARTURE_PRIOR_STRENGTH = max(0.0, min(0.9, get_float('DEPARTURE_PRIOR_STRENGTH', 0.55)))
DEPARTURE_PRIOR_FADE_DAYS = max(5, get_int('DEPARTURE_PRIOR_FADE_DAYS', 20))
DEPARTURE_PREDICTION_THRESHOLD = max(0.05, min(0.8, get_float('DEPARTURE_PREDICTION_THRESHOLD', 0.22)))
NEURAL_CHALLENGER = get_bool('NEURAL_CHALLENGER', True)
NEURAL_MIN_ROWS = max(1000, get_int('NEURAL_MIN_ROWS', 7000))

# v0.4 PyTorch temporal challenger. These defaults are deliberately small enough
# for a Raspberry Pi 5 CPU while still giving the sequence model real capacity.
NEURAL_V4_ENABLED = get_bool('NEURAL_V4_ENABLED', True)
NEURAL_V4_MIN_ROWS = max(2000, get_int('NEURAL_V4_MIN_ROWS', 6500))
NEURAL_V4_WINDOW_MINUTES = max(30, get_int('NEURAL_V4_WINDOW_MINUTES', 60))
NEURAL_V4_STEP_MINUTES = max(1, get_int('NEURAL_V4_STEP_MINUTES', 5))
NEURAL_V4_HIDDEN = max(16, get_int('NEURAL_V4_HIDDEN', 64))
NEURAL_V4_LAYERS = max(1, min(3, get_int('NEURAL_V4_LAYERS', 2)))
NEURAL_V4_DROPOUT = max(0.0, min(.5, get_float('NEURAL_V4_DROPOUT', .12)))
NEURAL_V4_BATCH_SIZE = max(32, get_int('NEURAL_V4_BATCH_SIZE', 256))
NEURAL_V4_EPOCHS = max(20, get_int('NEURAL_V4_EPOCHS', 180))
NEURAL_V4_PATIENCE = max(5, get_int('NEURAL_V4_PATIENCE', 18))
NEURAL_V4_LR = max(1e-5, get_float('NEURAL_V4_LR', .0015))

# v0.6 Neural Governor. The GRU stays shadow-only until these gates are earned
# against both the same blocked holdout and resolved live Truth outcomes.
NEURAL_GOVERNOR_ENABLED = get_bool('NEURAL_GOVERNOR_ENABLED', True)
NEURAL_GOVERNOR_AUTO_PROMOTE = get_bool('NEURAL_GOVERNOR_AUTO_PROMOTE', True)
NEURAL_HOLDOUT_MIN_IMPROVEMENT = max(0.0, get_float('NEURAL_HOLDOUT_MIN_IMPROVEMENT', 0.0))
NEURAL_HOLDOUT_MIN_HEADS = max(1, min(5, get_int('NEURAL_HOLDOUT_MIN_HEADS', 4)))
NEURAL_TRUTH_MIN_RESOLVED_PER_HEAD = max(3, get_int('NEURAL_TRUTH_MIN_RESOLVED_PER_HEAD', 12))
NEURAL_TRUTH_MIN_IMPROVEMENT = max(0.0, get_float('NEURAL_TRUTH_MIN_IMPROVEMENT', 0.02))
NEURAL_CANARY_MIN_NEW_PER_HEAD = max(2, get_int('NEURAL_CANARY_MIN_NEW_PER_HEAD', 5))
NEURAL_CANARY_MIN_IMPROVEMENT = max(0.0, get_float('NEURAL_CANARY_MIN_IMPROVEMENT', 0.01))
NEURAL_ROLLBACK_MIN_NEW_PER_HEAD = max(2, get_int('NEURAL_ROLLBACK_MIN_NEW_PER_HEAD', 5))
NEURAL_ROLLBACK_MEAN_REGRESSION = max(0.0, get_float('NEURAL_ROLLBACK_MEAN_REGRESSION', 0.08))
NEURAL_ROLLBACK_CRITICAL_REGRESSION = max(0.0, get_float('NEURAL_ROLLBACK_CRITICAL_REGRESSION', 0.15))

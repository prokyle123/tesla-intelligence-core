#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="0.8.27.6"
REPO_URL="${GHOST_REPO_URL:-https://github.com/prokyle123/tesla-intelligence-core.git}"
INSTALL_DIR="/opt/ghost-tesla-ai"
DATA_DIR="/var/lib/ghost-tesla-ai"
CONF_DIR="/etc/ghost-tesla-ai"

banner(){
  echo "============================================================"
  echo " Tesla Intelligence Core v${VERSION} - Interactive Installer"
  echo "============================================================"
}
fail(){ echo "ERROR: $*" >&2; exit 1; }
yn(){
  local prompt="$1" default="${2:-n}" ans
  if [[ "$default" == "y" ]]; then read -r -p "$prompt [Y/n] " ans || true; ans="${ans:-y}"; else read -r -p "$prompt [y/N] " ans || true; ans="${ans:-n}"; fi
  [[ "$ans" =~ ^[Yy]$ ]]
}
prompt_default(){
  local __var="$1" text="$2" def="$3" val
  read -r -p "$text [$def]: " val || true
  printf -v "$__var" '%s' "${val:-$def}"
}

# curl | bash bootstrap: clone the full repo, then re-run the local installer.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
if [[ ! -d "$SCRIPT_DIR/ghost_tesla_ai" ]]; then
  command -v git >/dev/null 2>&1 || { command -v sudo >/dev/null 2>&1 && sudo apt-get update -y && sudo apt-get install -y git; }
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  echo "Downloading Tesla Intelligence Core..."
  git clone --depth 1 "$REPO_URL" "$TMP/repo"
  exec bash "$TMP/repo/install.sh" "$@"
fi
ROOT="$SCRIPT_DIR"

banner
if [[ "${EUID}" -eq 0 ]]; then SUDO=""; CALLING_USER="${SUDO_USER:-root}"; else command -v sudo >/dev/null 2>&1 || fail "sudo is required"; SUDO="sudo"; CALLING_USER="${USER}"; fi
DEFAULT_USER="$CALLING_USER"
[[ "$DEFAULT_USER" == "root" ]] && DEFAULT_USER="$(logname 2>/dev/null || echo pi)"
prompt_default INSTALL_USER "Linux user that should run Tesla Intelligence Core" "$DEFAULT_USER"
id "$INSTALL_USER" >/dev/null 2>&1 || fail "Linux user '$INSTALL_USER' does not exist"

ARCH="$(uname -m)"
OS_NAME="$(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-Linux}")"
echo "Platform : $OS_NAME / $ARCH"
echo "User     : $INSTALL_USER"
echo

# Timezone is important because departure learning uses local wall-clock time.
CURRENT_TZ="$(timedatectl show -p Timezone --value 2>/dev/null || echo UTC)"
prompt_default TIMEZONE "System timezone used for learned departures" "$CURRENT_TZ"
if [[ "$TIMEZONE" != "$CURRENT_TZ" ]]; then
  if yn "Change this Pi's system timezone from $CURRENT_TZ to $TIMEZONE?" y; then $SUDO timedatectl set-timezone "$TIMEZONE"; fi
fi

cat <<'TXT'
Telemetry source:
  1) Tessie API (recommended; supports historical backfill)
  2) TeslaMate MQTT
TXT
prompt_default SOURCE_CHOICE "Choose source" "1"
SOURCE_MODE="tessie"
TESSIE_TOKEN=""; TESSIE_VIN=""; MQTT_HOST="127.0.0.1"; MQTT_PORT="1883"; MQTT_USER=""; MQTT_PASSWORD=""; MQTT_TLS="false"; TESLAMATE_CAR_ID="1"
if [[ "$SOURCE_CHOICE" == "2" ]]; then
  SOURCE_MODE="mqtt"
  prompt_default MQTT_HOST "TeslaMate MQTT host" "127.0.0.1"
  prompt_default MQTT_PORT "TeslaMate MQTT port" "1883"
  prompt_default TESLAMATE_CAR_ID "TeslaMate car ID" "1"
  read -r -p "MQTT username (blank if none): " MQTT_USER || true
  read -r -s -p "MQTT password (blank if none): " MQTT_PASSWORD || true; echo
  yn "Use MQTT TLS?" n && MQTT_TLS="true"
else
  read -r -s -p "Tessie API token: " TESSIE_TOKEN || true; echo
  [[ -n "$TESSIE_TOKEN" ]] || fail "A Tessie token is required for Tessie mode"
  read -r -p "Tesla VIN (blank = auto-discover first vehicle): " TESSIE_VIN || true
fi

read -r -p "Typical departure seed HH:MM (blank = learn with no seed): " EXPECTED_DEPARTURE || true
if [[ -n "$EXPECTED_DEPARTURE" && ! "$EXPECTED_DEPARTURE" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]; then fail "Departure must be HH:MM, for example 06:00"; fi
prompt_default BACKFILL_DAYS "Historical days to learn on first install (Tessie only)" "30"
prompt_default DASH_PORT "Dashboard port" "8766"

CONFIG_ECOFLOW=false; ECOFLOW_RIVER3_SN=""
if yn "Configure optional EcoFlow RIVER 3 telemetry?" n; then
  CONFIG_ECOFLOW=true
  read -r -p "EcoFlow device serial: " ECOFLOW_RIVER3_SN || true
fi
CONFIG_STARLINK=false
if yn "Install optional Starlink local power telemetry support?" n; then CONFIG_STARLINK=true; fi
CONFIG_FUNNEL=false
if yn "Configure optional PIN-protected Tailscale Funnel after install?" n; then CONFIG_FUNNEL=true; fi

echo
banner
echo "Installing operating-system dependencies..."
$SUDO apt-get update -y
$SUDO apt-get install -y git curl ca-certificates python3 python3-venv python3-pip python3-dev build-essential
# Prefer distro Python packages on Raspberry Pi/Debian; pip is the fallback below.
$SUDO apt-get install -y python3-numpy python3-sklearn python3-flask python3-paho-mqtt python3-joblib 2>/dev/null || true
# Prefer Debian's ARM-friendly PyTorch package when available.
$SUDO apt-get install -y python3-torch 2>/dev/null || true

# Back up code only. Runtime history/models live separately and are never deleted here.
if [[ -d "$INSTALL_DIR" ]]; then
  BACKUP="${INSTALL_DIR}.backup-$(date +%Y%m%d-%H%M%S)"
  $SUDO cp -a "$INSTALL_DIR" "$BACKUP"
  echo "Code backup: $BACKUP"
fi
$SUDO mkdir -p "$INSTALL_DIR" "$DATA_DIR/models" "$CONF_DIR"
$SUDO rm -rf "$INSTALL_DIR/ghost_tesla_ai" "$INSTALL_DIR/web" "$INSTALL_DIR/systemd"
$SUDO cp -a "$ROOT/ghost_tesla_ai" "$INSTALL_DIR/"
$SUDO cp -a "$ROOT/web" "$INSTALL_DIR/"
$SUDO cp -a "$ROOT/systemd" "$INSTALL_DIR/"
$SUDO cp "$ROOT/VERSION" "$ROOT/requirements.txt" "$ROOT/requirements-starlink.txt" "$INSTALL_DIR/"

if [[ ! -x "$INSTALL_DIR/venv/bin/python" ]]; then
  $SUDO python3 -m venv --system-site-packages "$INSTALL_DIR/venv"
fi
$SUDO "$INSTALL_DIR/venv/bin/python" -m pip install --upgrade pip wheel >/dev/null
if ! $SUDO "$INSTALL_DIR/venv/bin/python" - <<'PY'
import flask, numpy, sklearn, joblib, torch
import paho.mqtt.client
PY
then
  echo "Installing Python runtime packages (PyTorch may take a while)..."
  $SUDO "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
fi
if $CONFIG_STARLINK; then
  $SUDO "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements-starlink.txt" || echo "WARN: Starlink optional dependencies failed; core GHOST install will continue."
fi

# Preserve an existing config on upgrades, but create a fresh interactive config on first install.
ENV_FILE="$CONF_DIR/ghost.env"
if [[ -f "$ENV_FILE" ]]; then
  echo "Existing config detected: $ENV_FILE"
  if yn "Keep the existing GHOST configuration?" y; then KEEP_CONFIG=true; else KEEP_CONFIG=false; fi
else KEEP_CONFIG=false; fi

if ! $KEEP_CONFIG; then
  TMP_ENV="$(mktemp)"
  cat > "$TMP_ENV" <<ENV
# Tesla Intelligence Core v$VERSION
GHOST_AI_HOST=0.0.0.0
GHOST_AI_PORT=$DASH_PORT
GHOST_AI_DATA_DIR=$DATA_DIR
GHOST_AI_DB=$DATA_DIR/ghost_ai.sqlite3
GHOST_AI_MODEL_DIR=$DATA_DIR/models
SOURCE_MODE=$SOURCE_MODE
TESSIE_BASE_URL=https://api.tessie.com
TESSIE_TOKEN_FILE=$CONF_DIR/tessie.token
TESSIE_VIN=$TESSIE_VIN
TESSIE_POLL_SECONDS=60
TESSIE_USE_CACHE=true
TESSIE_FETCH_BATTERY_WHEN_ACTIVE=true
MQTT_HOST=$MQTT_HOST
MQTT_PORT=$MQTT_PORT
MQTT_USER=$MQTT_USER
MQTT_PASSWORD=$MQTT_PASSWORD
MQTT_TLS=$MQTT_TLS
TESLAMATE_CAR_ID=$TESLAMATE_CAR_ID
SNAPSHOT_SECONDS=60
MIN_TRAIN_ROWS=120
TRAIN_LOOKBACK_DAYS=180
AUTO_PROMOTE=true
PROMOTE_IMPROVEMENT=0.02
EVENT_LOOKBACK_DAYS=60
EVENT_MAX_GAP_MINUTES=20
COLD_SOAK_THRESHOLD_C=10.0
READINESS_TARGET_PACK_F=50.0
READINESS_MIN_ARRIVAL_SOC=20.0
EXPECTED_DEPARTURE=$EXPECTED_DEPARTURE
EXPECTED_DEPARTURE_WINDOW_MINUTES=90
DEPARTURE_LEARNING_ENABLED=true
DEPARTURE_LOOKBACK_DAYS=90
DEPARTURE_PRIOR_STRENGTH=0.55
DEPARTURE_PRIOR_FADE_DAYS=20
NEURAL_CHALLENGER=true
NEURAL_V4_ENABLED=true
NEURAL_GOVERNOR_ENABLED=true
NEURAL_GOVERNOR_AUTO_PROMOTE=true
ECOFLOW_RIVER3_SN=$ECOFLOW_RIVER3_SN
ECOFLOW_APP_CREDENTIALS_FILE=$DATA_DIR/ecoflow_app.json
WEATHER_ENABLED=true
WEATHER_CACHE_MINUTES=20
ENV
  $SUDO install -m 640 -o root -g "$INSTALL_USER" "$TMP_ENV" "$ENV_FILE"
  rm -f "$TMP_ENV"
fi

if [[ "$SOURCE_MODE" == "tessie" && -n "$TESSIE_TOKEN" ]]; then
  printf '%s\n' "$TESSIE_TOKEN" | $SUDO tee "$CONF_DIR/tessie.token" >/dev/null
  $SUDO chmod 640 "$CONF_DIR/tessie.token"
  $SUDO chown root:"$INSTALL_USER" "$CONF_DIR/tessie.token"
fi

$SUDO chown -R "$INSTALL_USER:$INSTALL_USER" "$INSTALL_DIR" "$DATA_DIR"

# Render generic systemd templates for the selected Linux user.
for t in "$ROOT"/systemd/templates/*.in; do
  [[ -f "$t" ]] || continue
  out="/etc/systemd/system/$(basename "${t%.in}")"
  sed "s/__GHOST_USER__/$INSTALL_USER/g" "$t" | $SUDO tee "$out" >/dev/null
done

cat <<'WRAP' | $SUDO tee /usr/local/bin/ghost-ai >/dev/null
#!/usr/bin/env bash
cd /opt/ghost-tesla-ai
export PYTHONPATH=/opt/ghost-tesla-ai
exec /opt/ghost-tesla-ai/venv/bin/python -m ghost_tesla_ai.cli "$@"
WRAP
$SUDO chmod 755 /usr/local/bin/ghost-ai

$SUDO -u "$INSTALL_USER" env PYTHONPATH="$INSTALL_DIR" "$INSTALL_DIR/venv/bin/python" -m ghost_tesla_ai.cli init-db >/dev/null
$SUDO systemctl daemon-reload
$SUDO systemctl enable --now ghost-tesla-ai-collector.service ghost-tesla-ai-web.service ghost-tesla-ai-train.timer ghost-tesla-ai-intelligence.timer ghost-tesla-ai-neural.timer
sleep 3

if $CONFIG_ECOFLOW; then
  echo
  echo "EcoFlow setup (credentials stay on this Pi):"
  $SUDO -u "$INSTALL_USER" env PYTHONPATH="$INSTALL_DIR" "$INSTALL_DIR/venv/bin/python" -m ghost_tesla_ai.ecoflow_setup || echo "WARN: EcoFlow setup was skipped/failed; you can retry later."
  $SUDO systemctl restart ghost-tesla-ai-web.service
fi

if [[ "$SOURCE_MODE" == "tessie" && "$BACKFILL_DAYS" =~ ^[0-9]+$ && "$BACKFILL_DAYS" -gt 0 ]]; then
  echo
  if yn "Start a $BACKFILL_DAYS-day historical backfill now? It can continue while you use the dashboard." y; then
    # Run detached under the service user; log is kept in the GHOST data directory.
    $SUDO -u "$INSTALL_USER" bash -lc "cd '$INSTALL_DIR' && nohup '$INSTALL_DIR/venv/bin/python' -m ghost_tesla_ai.backfill --days '$BACKFILL_DAYS' --interval 300 --train-after > '$DATA_DIR/bootstrap.log' 2>&1 &"
    echo "Historical learning started: $DATA_DIR/bootstrap.log"
  fi
fi

if $CONFIG_FUNNEL; then
  echo
  if ! command -v tailscale >/dev/null 2>&1; then
    echo "Tailscale is not installed. Core Tesla Intelligence Core is complete; install/connect Tailscale, then run:"
    echo "  sudo -u $INSTALL_USER $INSTALL_DIR/venv/bin/python -m ghost_tesla_ai.funnel_pin_setup"
    echo "  sudo systemctl enable --now ghost-tesla-ai-funnel-gateway.service"
    echo "  sudo tailscale funnel --bg http://127.0.0.1:8777"
  elif ! tailscale status >/dev/null 2>&1; then
    echo "Tailscale is installed but not connected. Run 'sudo tailscale up', then use the commands shown in docs/REMOTE_ACCESS.md."
  else
    $SUDO -u "$INSTALL_USER" env PYTHONPATH="$INSTALL_DIR" "$INSTALL_DIR/venv/bin/python" -m ghost_tesla_ai.funnel_pin_setup
    $SUDO systemctl enable --now ghost-tesla-ai-funnel-gateway.service
    $SUDO tailscale funnel --bg http://127.0.0.1:8777 || echo "WARN: Funnel could not be enabled automatically. See docs/REMOTE_ACCESS.md."
  fi
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "===== VALIDATION ====="
if curl -fsS "http://127.0.0.1:${DASH_PORT}/api/health" >/dev/null; then echo "Dashboard/API : PASS"; else echo "Dashboard/API : STARTING (check: sudo journalctl -u ghost-tesla-ai-web -n 80)"; fi
$SUDO systemctl --no-pager --plain is-active ghost-tesla-ai-collector.service ghost-tesla-ai-web.service ghost-tesla-ai-intelligence.timer ghost-tesla-ai-neural.timer || true

echo
echo "============================================================"
echo " Tesla Intelligence Core installed"
echo " Dashboard : http://${IP:-localhost}:${DASH_PORT}"
echo " Status    : ghost-ai status"
echo " Config    : $ENV_FILE"
echo " Data      : $DATA_DIR"
echo "============================================================"

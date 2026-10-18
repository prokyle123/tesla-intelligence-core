# GHOST Hive — first real network pilot

**Draft engineering preview, October 2026.** This milestone adds a real authenticated
monthly-summary transport and a static public Hive website without exposing
Classic GHOST's private dashboard or raw vehicle data to the internet.

## Components already developed

- GHOST remains ONE installed local app, with the existing full-screen Hive tab.
- Separate loopback Hive coordinator (`genesis.hive_server`) with private SQLite,
  enrolled bearer tokens, repeat-report deduplication, and authenticated
  contributor-controlled revocation and data erasure.
- `genesis.hive_member`: opt-in OFF by default; an exact reviewable payload of
  **month, forecast count, total absolute temperature-error sum**, plus
  constant schema identifiers, only. Independent send confirmation required.
- No GPS, VIN, location, address, trip timestamps, raw traces, individual
  forecasts, raw sensor records or PyTorch model weights are uploaded.
- A server can show authenticated installations reporting since onboarding,
  starting at one. Group forecast-error data is withheld until ten registered
  reporting nodes contribute in the same month. That does NOT certify
  ten unique people, data provenance or full anonymity.
- `genesis.hive_models` stores strictly typed model **metadata** in a
  quarantined registry. This does NOT transfer actual weights or promote
  a model. Real model-file exchange remains blocked pending security and
  privacy review (safe tensor format, integrity signatures, leakage testing,
  model-card compatibility and manual approval).
- A screenshot-style static public Hive site is staged on the `gh-pages`
  branch with honest zero/unknown initial numbers. No credential or direct
  connection to GHOST's internal database is required to view it.

## One-host local pilot on GHOST (does not open the Pi to the Internet)

Run from a staged development checkout as a normal user:

    cd ~/genesis-product-source
    bash scripts/genesis_stage_preview.sh stage
    bash scripts/hive_preview.sh stop
    bash scripts/hive_preview.sh start

Then set up the **private client**. Use the Classic GHOST venv interpreter
without modifying any installed Python packages:

    PY=/opt/ghost-tesla-ai/venv/bin/python
    APP=$HOME/genesis-product/current
    HUB=$HOME/genesis-product/state/hive-server/hive.sqlite3
    MEMBER=$HOME/genesis-product/state/hive-client
    mkdir -p "$MEMBER" && chmod 700 "$MEMBER"
    cd "$APP"
    "$PY" -m genesis.hive_server --db "$HUB" enroll --token-file "$MEMBER/token"
    "$PY" -m genesis.hive_member --state-dir "$MEMBER" configure --endpoint http://127.0.0.1:8778 --token-file "$MEMBER/token"
    "$PY" -m genesis.hive_member --state-dir "$MEMBER" preview
    "$PY" -m genesis.hive_member --state-dir "$MEMBER" status

The commands above create the private token and OFF-by-default client.
**No telemetry or aggregate leaves the Pi.** The local coordinator is on
127.0.0.1, not publicly accessible. A real live contribution requires
the user's informed approval:

    "$PY" -m genesis.hive_member --state-dir "$MEMBER" consent --i-understand-pseudonymous-aggregate-sharing
    "$PY" -m genesis.hive_member --state-dir "$MEMBER" send --confirm-upload

The send submits only an eligible month with >=25 locally resolved battery
temperature forecasts. It does not submit any individual measurement.
All model metadata and weights remain OFF and unaffected.

Stop local contribution immediately:

    "$PY" -m genesis.hive_member --state-dir "$MEMBER" disable

Ask the coordinator to delete ALL stored contributions and revoke enrollment:

    "$PY" -m genesis.hive_member --state-dir "$MEMBER" revoke-remote --confirm-delete

Local disabling does not delete server history. Remote revocation does;
backups may be retained under a separately configured retention policy.

## Local GHOST Hive page update (preserves Home exactly)

The original additive Hive tab has already been installed on the owner's
Ghost device. DO NOT rerun the old integration installer. Use the
checksum-checked two-file module updater:

    python3 scripts/ghost_hive_update.py --live /opt/ghost-tesla-ai --backup "$HOME/ghost-hive-module-upgrades" --check
    sudo python3 scripts/ghost_hive_update.py --live /opt/ghost-tesla-ai --backup "$HOME/ghost-hive-module-upgrades" --apply
    sudo systemctl restart ghost-tesla-ai-web.service

Only `ghost_tesla_ai/hive_local.py` and `web/templates/hive.html` change.
Other Home and readiness pages, collectors and production model files
are NEVER replaced. New local UI checks only the loopback Hive coordinator
and local consent status. On any unexpected difference, the updater refuses
to modify files. Backups are verified before rollback.

## Public site

A public-ready static dashboard exists in repo branch `gh-pages`: files
`index.html` and `network.json`. The initial JSON says zero reporting
nodes and no public fleet errors, not fictional screenshot statistics.

To publish, open GitHub repository Settings > Pages, select
**Deploy from a branch**, `gh-pages`, folder `/ (root)`, then Save.
GitHub Pages hosting may take several minutes to activate.

Current site data is a reviewed static JSON snapshot. To update it manually:

    python3 -m genesis.hive_public --db "$HUB" --out /tmp/hive-public-network.json

Review that JSON, then publish ONLY its approved aggregate fields to the
`gh-pages` branch's `network.json`. No server DB, token or config file
belongs in the public repository. A separate workflow in the development
branch supports hourly automatic refresh **after** a trusted HTTPS-only
`HIVE_PUBLIC_URL` is configured and that workflow is activated on main.

## Before accepting external nodes

- Deploy the coordinator behind properly configured HTTPS, a firewall,
  rate limits and a dedicated authentication boundary. Do not expose
  Classic GHOST's existing server or raw SQLite source to public ingress.
- Use independent secrets per installation, certificate validation, token
  rotation, incident response, backups, retention and abuse monitoring.
- Document that the coordinator can access per-participant aggregate rows.
  It is **pseudonymous**, not anonymous, and neither secure aggregation
  nor differential privacy is provided yet.
- Independently review model-weight serialization and training-data
  leakage; reject pickle-based uploads and never promote downloaded
  weights into live models automatically.
- Account for the absence of verified distinct humans and the fact
  that server-received metrics are self-reported.

Neither adding the local coordinator nor preparing the public dashboard
implies these Internet-deployment conditions have been met.

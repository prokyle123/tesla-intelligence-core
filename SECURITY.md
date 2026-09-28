# Security

## Reporting

For security-sensitive reports, use a private GitHub security advisory if enabled for the repository rather than posting credentials or exploit details in a public issue.

## Secrets

The installer stores secrets outside the repository. Never commit:

- Tessie API tokens
- MQTT passwords
- EcoFlow credentials
- `funnel_pin.json`
- SQLite databases or raw telemetry exports

## Remote exposure

Port `8766` is the raw Flask dashboard/API. Treat it as private LAN/tailnet access.

For public Tailscale Funnel use, send Funnel traffic to `127.0.0.1:8777`, which is the PIN gateway. The gateway rate-limits failed PIN attempts and uses a hashed PIN plus signed session cookie.

This is an enthusiast project, not a hardened enterprise authentication product. Put it behind networks/identity controls appropriate to your own threat model.

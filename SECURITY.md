# Security

Tesla Intelligence Core is an enthusiast project. It is not a hardened enterprise authentication platform.

## Reporting a security issue

If GitHub private security advisories are available for this repository, use one for credential exposure, authentication bypasses or other security-sensitive reports.

Do not post credentials, tokens, exploitable private deployment details, or unredacted telemetry in a public issue.

## Secrets

The installer keeps secrets outside the repository.

Never commit:
- Tessie API tokens;
- MQTT passwords;
- EcoFlow credentials;
- Funnel PIN data;
- SQLite databases;
- raw telemetry exports.

## Network exposure

Raw dashboard/API:

```text
:8766
```

Treat this as private LAN/tailnet access.

Optional PIN gateway:

```text
127.0.0.1:8777
```

For the intended public Funnel path, send Funnel traffic to `8777`, not directly to `8766`.

## PIN gateway

The included gateway:
- hashes the PIN using `scrypt` with a random salt;
- uses a signed session cookie;
- marks the session cookie Secure / HttpOnly;
- is intended to rate-limit failed PIN attempts.

It should be considered a lightweight protection layer for the project's optional Funnel workflow, not a replacement for a mature identity/access platform.

## Dependency / host security

Users remain responsible for:
- OS updates;
- Tailscale account security;
- network/firewall policy;
- Tessie/TeslaMate credential security;
- physical access to the Pi;
- backups containing telemetry.

## Read-only scope

Tesla Intelligence Core is currently designed as observation/prediction software and does not intentionally send vehicle control commands. Keeping that boundary narrow reduces the impact of application-layer bugs.

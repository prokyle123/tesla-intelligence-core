# Privacy

Tesla Intelligence Core processes vehicle telemetry, and vehicle telemetry can be highly personal.

It may reveal:
- driving times;
- recurring routines;
- energy/charging behavior;
- vehicle state;
- potentially location-related information present in provider payloads.

## Local-first storage

By default, Tesla Intelligence Core stores:
- SQLite telemetry/history locally;
- learned event state locally;
- trained model artifacts locally.

The project does not intentionally upload its local database or trained model artifacts to a project-operated cloud service.

## External services

Some configured integrations communicate with third-party services:

- **Tessie** — cloud telemetry provider; use of Tessie means Tesla data flows through Tessie according to Tessie's own terms/privacy practices.
- **TeslaMate MQTT** — depends on the user's TeslaMate deployment and data path.
- **Open-Meteo** — weather context is requested over the Internet.
- **EcoFlow** — optional integration can contact EcoFlow services.
- **Tailscale Funnel** — optional public remote access intentionally publishes the PIN gateway through Tailscale infrastructure.

## Sensitive files

Do not publish or commit:

```text
/etc/ghost-tesla-ai
/var/lib/ghost-tesla-ai
```

In particular, do not post:
- Tessie API tokens;
- MQTT passwords;
- EcoFlow credentials;
- `funnel_pin.json`;
- SQLite databases;
- raw telemetry exports;
- screenshots containing VINs or exact location information.

## GitHub issues

Before attaching logs or JSON to a public issue, redact:
- VIN;
- coordinates;
- addresses;
- tokens;
- device serials you consider private;
- stable identifiers that are not required to debug the problem.

Synthetic or deliberately redacted telemetry is preferred for public bug reports.

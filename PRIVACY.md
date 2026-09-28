# Privacy

Vehicle telemetry can reveal driving times, routines, energy use and potentially location-related information present in provider payloads.

GHOST stores its SQLite database and trained models locally by default. The project does not intentionally upload its local database or model artifacts anywhere.

However:

- Tessie is a cloud telemetry provider; using Tessie means Tesla data flows through Tessie according to Tessie's own service/privacy terms.
- TeslaMate MQTT depends on the user's TeslaMate installation and its data path.
- Open-Meteo requests weather context over the Internet.
- Optional EcoFlow integration contacts EcoFlow services.
- Optional Tailscale Funnel intentionally exposes the PIN gateway through Tailscale's public Funnel service.

Do not commit `/etc/ghost-tesla-ai`, `/var/lib/ghost-tesla-ai`, exported databases, tokens, app credentials, Funnel PIN data or raw private telemetry to GitHub.

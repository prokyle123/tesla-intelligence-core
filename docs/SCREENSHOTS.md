# Public screenshots and privacy

## Current GHOST AI development dashboard

The main [README preview](../README.md) now uses the **original screenshot provided from the running October 2026 dashboard**, stored as a pixel-identical lossless WebP at [images/ghost-v2-dashboard-live.webp](images/ghost-v2-dashboard-live.webp). It shows local AI insight, Voice & Alerts, live winter readiness, pack forecast, Open-Meteo weather, heater/HVAC signals and the electrical power-path view.

The original historical v1 screenshot gallery remains intact with its existing checksums. This new image is a genuine operator-supplied screenshot, not an AI rendering, and reflects the **development Pi ahead of the public installer**.

---


Tesla Intelligence Core is a **vehicle telemetry** product. Its dashboards may display battery data, a local hostname, route/site IDs, usage patterns, timestamps, charge location clues, and other personal details. Never publish an unreviewed capture from a live car.

## Current screenshots

The [README visual tour](../README.md#visual-tour) uses privacy-reviewed screenshots captured from the running Ghost development dashboard in October 2026. Private stable-location references were redacted from departure planning. These captures demonstrate the live UI, not independent validation of model accuracy.

New captures needed for the v1 release notes:

- Future pack-temperature panel with its new 3h / 6h / 12h outdoor-weather row
- Forecast Quality v2, clearly indicating window-vs-episode scoring
- Trip Quality v3.2.1, including all-journey/weekend and withheld-forecast context
- Vehicle Sensors with TPMS PSI and freshness states
- Overall home dashboard and neural atlas, if materially changed

## Local screenshot collection (Windows PC)

From a PC that can reach a test or running Ghost dashboard, use:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Capture-Ghost-Release-Screenshots.ps1 -BaseUrl "http://YOUR_PI_HOST:8766"
```

The capture helper saves four local PNG files under `Downloads\Ghost-v1-Release-Screenshots`. It **does not** upload, commit, publish, authenticate to Tessie or change Ghost services. If the desired winter card is below the fold, navigate to the Winter section and capture that element manually.

Before publishing, check each image for VIN, coordinates, address, site registry, route geometry, private IP/host names, unique vehicle identity, tokens, or other personal data. Crop or redact anything private. Use neutral example data if exact live values would identify a specific owner. Keep the unredacted originals out of GitHub and public release attachments.

After reviewing, add appropriately named images under `docs/images/`, update README image links, and explicitly caption which version was running. Do not substitute conceptual renders for verified screenshots.

# Tesla Intelligence Core Companion — Android v0.3.0

Android companion for the Tesla Intelligence Core Raspberry Pi dashboard.

The package remains `com.ghost.tesla.mobile` for continuity with the original GHOST companion builds.

## v0.3.0

This release rebuilds the connection layer and fixes modern Android safe-area behavior.

### Connection Center

- Adds a dedicated **Connection Center** instead of relying on three passive URL fields.
- Adds **Auto-Find Pi on Local Network**.
- Scans the current local /24 for the default Tesla Intelligence Core dashboard port `8766`.
- Verifies discovered hosts by checking the dashboard itself, not just whether a port is open.
- Tests Local / Tailnet / Public routes **in parallel**.
- Prefers the most private working route:
  - Local LAN
  - private Tailscale
  - public HTTPS / PIN gateway
- Stores the last successful route for diagnostics.
- Adds **Test These Endpoints** before saving.
- Adds **Open Public URL Anyway** for cases where WebView can reach a public login page even when a Java probe is inconclusive.
- Recognizes public PIN/login pages and displays **LOGIN** instead of making the app look offline.
- Retains detailed per-endpoint diagnostics.

### Android system-bar fixes

- Handles Android display cutouts / status-bar insets.
- Keeps the companion header below the phone status bar.
- Keeps the app navigation above the Android navigation area.
- Requests visible system navigation controls without using immersive mode.
- Re-applies safe-area insets when the app regains focus.
- Uses `adjustResize` so the keyboard does not cover the connection setup.

### Current quick navigation

`READY · EVENTS · NEURAL · TRUTH · THERMAL · MORE`

**MORE** includes AI Lab, Models, Data Quality, Sources, Production, History, full Neural Atlas, Connection Center, Tesla Browser Access and connection diagnostics.

## Endpoint order

```text
Local LAN -> private Tailnet -> optional public HTTPS
```

Any endpoint can be left blank.

```text
Local:   http://192.168.x.x:8766
Tailnet: http://100.x.x.x:8766
         http://hostname:8766
Public:  https://your-public-hostname.example/
```

The public endpoint should terminate at the PIN gateway rather than intentionally exposing the raw dashboard.

## Tesla in-car browser

On the setup this app was developed with, the Tesla browser would not load the Pi's local/private dashboard URL. A working route was:

```text
Tesla browser
  -> public HTTPS Tailscale Funnel URL
  -> PIN gateway
  -> Tesla Intelligence Core dashboard
```

Vehicle software, networking and installations can vary. See [the full Tesla browser guide](../../docs/TESLA_BROWSER.md).

## Build locally on Windows

With Android Platform Tools installed and USB debugging enabled:

```powershell
powershell -ExecutionPolicy Bypass -File .\Build-And-Install.ps1
```

The helper downloads Gradle 8.9 when needed, builds the debug APK, installs it over ADB and launches it.

## Public APK

The repository workflow builds a public debug-signed APK and attaches it to the current GitHub release.

A public debug-signed build is useful for sideloading/testing, but Android signatures can differ from APKs built on another machine. If an older local build has a different signature, it may need to be uninstalled once before the GitHub APK can be installed.

A protected dedicated release-signing key is the appropriate next step before treating the APK as a long-term production distribution channel.

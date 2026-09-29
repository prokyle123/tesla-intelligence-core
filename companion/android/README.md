# Tesla Intelligence Core Companion — Android v0.9.1

Android companion for the Tesla Intelligence Core Raspberry Pi dashboard.

The package remains `com.ghost.tesla.mobile` for continuity with earlier GHOST companion builds.

## What changed in v0.9.1

### One bottom navigation bar

The duplicate Android-native navigation bar has been removed.

The companion now uses the dashboard-owned navigation only:

```text
HOME · READY · EVENTS · NEURAL · TRUTH · THERMAL · MORE
```

It is a single horizontally swipeable row. The app explicitly reserves the Android status/cutout area at the top and the navigation/gesture area at the bottom, so the tab row does not sit underneath Home / Back / Recents.

**HOME** opens the top of the winter-readiness dashboard.

**READY** opens the same Home view and jumps directly to the Winter Readiness hero.

**MORE** exposes the secondary dashboard views plus Notifications, Connection Center, Tesla Browser Access and diagnostics.

### Background monitoring

v0.9.1 adds `BackgroundMonitorJobService`, scheduled through Android `JobScheduler`.

The OS wakes the monitor approximately every 15 minutes when scheduling and networking permit. The job:

1. reads the saved Local / Tailnet / Public routes;
2. prefers the last-known-good route first;
3. queries `/api/v3/winter`;
4. evaluates alert conditions;
5. stores the latest monitor result;
6. exits again.

It does **not** keep a permanent always-awake loop running.

The schedule is persisted across reboot/package replacement.

### Notification Center

Open:

```text
MORE → Notifications
```

Available alert types:

- connection lost / restored;
- Winter Readiness below a configurable threshold;
- readiness recovery;
- warm-up / preconditioning recommendation;
- projected arrival SOC below a configurable threshold;
- projected arrival SOC recovery;
- optional battery-heater activation.

Defaults:

```text
Winter Readiness alert: below 70
Projected arrival SOC: below 20%
Battery-heater alert: off
```

The Notification Center also includes:

- **Send Test Notification**
- **Run Background Check Now**
- last background-check timestamp
- last background-check status/error

Android 13+ requires the normal notification runtime permission.

### Connection Center

The companion still supports:

```text
Local LAN
    ↓ fallback
Private Tailscale
    ↓ fallback
Public HTTPS / PIN gateway
```

The connector verifies the real Tesla Intelligence Core API rather than trusting a generic HTTP 200 page.

The public PIN gateway is recognized as authentication and WebView keeps the gateway session cookie after login.

### Android safe areas

The activity window keeps Android system bars visible and explicitly applies:

- status-bar inset;
- display-cutout inset;
- navigation-bar inset;
- mandatory-gesture inset.

The WebView therefore ends above the Android navigation/gesture area instead of drawing companion controls beneath it.

## Build locally on Windows

With Android Platform Tools installed and USB debugging enabled:

```powershell
powershell -ExecutionPolicy Bypass -File .\Build-And-Install.ps1
```

The helper builds the current source, updates the physical USB phone with `adb install -r`, and launches the companion.

A locally built APK normally reuses that PC's Android debug signing key, which is useful when updating an existing locally built companion without losing its saved endpoints.

## Public APK

The GitHub workflow attaches a public debug-signed APK, checksum and source archive to the current Tesla Intelligence Core release.

A public debug-signed build may not update an APK that was built with another machine's debug key. Android will report `INSTALL_FAILED_UPDATE_INCOMPATIBLE` when signatures differ.

## Background-monitor limitations

Android JobScheduler timing is approximate rather than exact. The 15-minute interval is a minimum periodic cadence, and Android may defer work for battery/network reasons.

The background monitor can use Local or private Tailnet HTTP routes directly. A public PIN-protected route requires a valid app/WebView gateway session; if that session is unavailable, the monitor falls through to the other configured routes or reports the route unreachable.

## Tesla in-car browser

The tested in-car route remains:

```text
Tesla browser
  → HTTPS Tailscale Funnel
  → PIN gateway
  → Tesla Intelligence Core dashboard
```

See [the Tesla browser guide](../../docs/TESLA_BROWSER.md).

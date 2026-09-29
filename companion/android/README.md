# Tesla Intelligence Core Companion — Android v0.9.5

Android companion for the Tesla Intelligence Core Raspberry Pi dashboard.

## What changed in v0.9.5

### Learned warm-up planning + governed six-hour pack prediction

The companion now consumes GHOST's learned preconditioning plan from `/api/v3/winter`. When warm-up is recommended, the persistent notification can show the recommended start time, estimated minutes, expected pack temperature before heating, target pack temperature, model source and confidence.

The Pi now has a true **+6 hour pack-temperature model horizon**. A tree champion is trained first as the safe baseline; the new neural +6h head stays behind the same holdout → live Truth → canary → production governor used by the other neural targets. Until it proves itself, the existing learned thermal-retention forecast remains the 6-hour fallback.

The warm-up duration model learns from real preconditioning events on this car. It requires at least 40 eligible events and its first promoted generation must perform at least as well as the observed heat-rate fallback on a chronological holdout. If it is unavailable or not good enough, GHOST keeps using the existing learned heat-rate calculation.

## What changed in v0.9.4

### Persistent Winter Status notification

When Background Monitoring is enabled, the companion now keeps one silent, ongoing notification in the Android notification shade.

Collapsed view:

```text
GHOST Winter • 82/100 READY
Pack 47°F • 6h 41°F • SOC 78%
```

Expanded view adds current-to-6-hour outside temperature, battery-heater or preconditioning state, and the last successful update time. The notification refreshes after every successful background check, retains the last good winter values if the Pi becomes unreachable, and changes its title to `OFFLINE` while the connection is unavailable.

The status notification uses its own low-importance channel, does not vibrate or make a sound on periodic refresh, opens the Winter Readiness view when tapped, and disappears when Background Monitoring is disabled.

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

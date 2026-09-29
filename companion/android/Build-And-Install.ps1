$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Version = '0.9.2'
$Package = 'com.ghost.tesla.mobile'

Write-Host "============================================================"
Write-Host " TESLA INTELLIGENCE CORE COMPANION v$Version"
Write-Host "============================================================"

$adb = (Get-Command adb -ErrorAction SilentlyContinue).Source
if (-not $adb) {
  $candidate = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
  if (Test-Path $candidate) { $adb = $candidate }
}
if (-not $adb) { throw "adb not found. Install Android SDK Platform Tools or add adb to PATH." }

& $adb start-server | Out-Null
$devices = & $adb devices
Write-Host $devices

$physical = @($devices | Select-String "\tdevice$" | ForEach-Object { ($_ -split "\s+")[0] })
if ($physical.Count -lt 1) {
  throw "No authorized Android device found. Connect the phone, enable USB debugging, and accept the RSA prompt."
}

Write-Host "`n===== PHONE ====="
& $adb -d shell getprop ro.product.model
& $adb -d shell getprop ro.build.version.release
& $adb -d shell getprop ro.build.version.sdk

$gradle = (Get-Command gradle -ErrorAction SilentlyContinue).Source
if (-not $gradle) {
  $tools = Join-Path $Root ".tools"
  $gdir = Join-Path $tools "gradle-8.9"
  $gradle = Join-Path $gdir "bin\gradle.bat"

  if (-not (Test-Path $gradle)) {
    New-Item -ItemType Directory -Path $tools -Force | Out-Null
    $zip = Join-Path $tools "gradle-8.9-bin.zip"
    Write-Host "Downloading Gradle 8.9..."
    Invoke-WebRequest -Uri "https://services.gradle.org/distributions/gradle-8.9-bin.zip" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $tools -Force
  }
}

Write-Host "`n[1/3] Building debug APK..."
& $gradle --no-daemon :app:assembleDebug
if ($LASTEXITCODE -ne 0) { throw "Gradle build failed with exit code $LASTEXITCODE" }

$apk = Join-Path $Root "app\build\outputs\apk\debug\app-debug.apk"
if (-not (Test-Path $apk)) { throw "APK was not produced: $apk" }

Write-Host "`n[2/3] Installing through ADB..."
& $adb -d install -r $apk
if ($LASTEXITCODE -ne 0) {
  Write-Host ""
  Write-Host "Android rejected the update." -ForegroundColor Yellow
  Write-Host "If INSTALL_FAILED_UPDATE_INCOMPATIBLE appears, the installed copy was signed with a different key." -ForegroundColor Yellow
  Write-Host "Do not uninstall automatically if you want to preserve the current app settings." -ForegroundColor Yellow
  throw "ADB install failed with exit code $LASTEXITCODE"
}

Write-Host "`n[3/3] Launching companion..."
& $adb -d shell am force-stop $Package | Out-Null
& $adb -d shell am start -n "$Package/.MainActivity"

Write-Host ""
Write-Host "Installed package:" -ForegroundColor DarkGray
& $adb -d shell dumpsys package $Package | Select-String "versionName=|versionCode=" | Select-Object -First 2

Write-Host ""
Write-Host "Installed + launched: Tesla Intelligence Core Companion v$Version" -ForegroundColor Green
Write-Host "Expected connection state after startup: LOCAL / TAILNET / PUBLIC with LIVE or API LIVE detail."
Write-Host "Bottom navigation: one swipeable dashboard row - HOME / READY / EVENTS / NEURAL / TRUTH / THERMAL / MORE."

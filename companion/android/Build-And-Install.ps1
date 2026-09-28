$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "============================================================"
Write-Host " TESLA INTELLIGENCE CORE COMPANION v0.2.0"
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
if (($devices | Select-String "\tdevice$").Count -lt 1) {
  throw "No authorized Android device found. Connect the phone, enable USB debugging, and accept the RSA prompt."
}

Write-Host "`n===== PHONE ====="
& $adb shell getprop ro.product.model
& $adb shell getprop ro.build.version.release
& $adb shell getprop ro.build.version.sdk

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
& $adb install -r $apk
if ($LASTEXITCODE -ne 0) {
  Write-Host "If the installed copy was signed on another machine, uninstall com.ghost.tesla.mobile once and retry." -ForegroundColor Yellow
  throw "ADB install failed with exit code $LASTEXITCODE"
}

Write-Host "`n[3/3] Launching companion..."
& $adb shell am force-stop com.ghost.tesla.mobile | Out-Null
& $adb shell am start -n com.ghost.tesla.mobile/.MainActivity

Write-Host ""
Write-Host "Installed + launched: Tesla Intelligence Core Companion v0.2.0" -ForegroundColor Green
Write-Host "Fresh installs ask for Local / Tailnet / Public endpoints inside the app."

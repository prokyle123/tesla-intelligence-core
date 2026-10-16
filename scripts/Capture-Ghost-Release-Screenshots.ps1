# Safe release screenshot capture from a Windows PC already on the same Tailnet.
# Never publishes images automatically: review for VIN, sites, tokens and addresses.
param(
    [string]$BaseUrl = "http://100.117.230.72:8766",
    [string]$OutputDir = "$env:USERPROFILE\Downloads\Ghost-v1-Release-Screenshots"
)
$ErrorActionPreference = "Stop"
$edge = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { throw "Microsoft Edge not found. Capture the pages manually with your browser." }
$parsed = [uri]$BaseUrl
if ($parsed.Scheme -ne "http" -and $parsed.Scheme -ne "https") {
    throw "Only HTTP(S) local dashboard URLs are supported."
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$pages = @(
    @{name="home"; path="/"},
    @{name="forecast-quality"; path="/forecast-quality"},
    @{name="trip-quality"; path="/trip-quality"},
    @{name="vehicle-sensors"; path="/vehicle-sensors"}
)
foreach ($p in $pages) {
    $target = $BaseUrl.TrimEnd("/") + $p.path
    $png = Join-Path $OutputDir ($p.name + ".png")
    $profile = Join-Path $env:TEMP ("ghost-release-capture-" + [guid]::NewGuid().ToString("N"))
    try {
        $arguments = @("--headless=new","--disable-gpu","--hide-scrollbars",
            "--no-first-run","--window-size=1440,1000",
            "--virtual-time-budget=15000","--user-data-dir=$profile",
            "--screenshot=$png",$target)
        & $edge @arguments 2>$null | Out-Null
        if (-not (Test-Path $png)) { throw "No image captured: $target" }
        Write-Host "CAPTURED $png"
    }
    finally {
        Remove-Item $profile -Recurse -Force -ErrorAction SilentlyContinue
    }
}
Write-Host ""
Write-Host "Review EVERY screenshot locally BEFORE uploading or committing."
Write-Host "Look for locations, VIN, precise routes, site IDs, account info or tokens."
Write-Host "Capture the Future Pack Temperature card manually if it is below the fold."
Write-Host "Nothing has been posted to GitHub."

# Safe release screenshot capture from a Windows PC already on the same Tailnet.
# Never publishes images automatically: review for VIN, sites, tokens and addresses.
param(
    [Parameter(Mandatory=$true)][string]$BaseUrl,
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
        # Avoid mistaking an old screenshot for a successful new capture.
        Remove-Item -LiteralPath $png -Force -ErrorAction SilentlyContinue
        try {
            $response = Invoke-WebRequest -Uri $target -UseBasicParsing -TimeoutSec 15
            if ([int]$response.StatusCode -ne 200) {
                throw "Unexpected HTTP status $($response.StatusCode)"
            }
        }
        catch {
            throw "Dashboard page did not respond at $target : $($_.Exception.Message)"
        }
        $arguments = @("--headless=new","--disable-gpu","--hide-scrollbars",
            "--no-first-run","--window-size=1440,1000",
            "--virtual-time-budget=15000","--user-data-dir=$profile",
            "--screenshot=$png",$target)
        # Chromium can emit non-fatal renderer diagnostics on stderr.
        # Windows PowerShell 5.1 converts those native stderr lines to errors
        # when ErrorActionPreference is Stop, even if the PNG is generated.
        # Capture native streams to files, then validate actual output.
        $stderrFile = Join-Path $profile "edge-stderr.txt"
        $stdoutFile = Join-Path $profile "edge-stdout.txt"
        New-Item -ItemType Directory -Force -Path $profile | Out-Null
        $pRun = Start-Process -FilePath $edge -ArgumentList $arguments `
            -Wait -PassThru -RedirectStandardError $stderrFile `
            -RedirectStandardOutput $stdoutFile -WindowStyle Hidden
        if (-not (Test-Path -LiteralPath $png)) {
            $details = if (Test-Path $stderrFile) {
                (Get-Content $stderrFile -Tail 4 -ErrorAction SilentlyContinue) -join " "
            } else { "No Edge diagnostics available" }
            throw "No image captured: $target (Edge exit $($pRun.ExitCode)). $details"
        }
        $imageBytes = [System.IO.File]::ReadAllBytes($png)
        $pngHeader = [byte[]](137,80,78,71,13,10,26,10)
        $validPng = $imageBytes.Length -ge 2000
        if ($validPng) {
            for ($i = 0; $i -lt $pngHeader.Length; $i++) {
                if ($imageBytes[$i] -ne $pngHeader[$i]) { $validPng = $false; break }
            }
        }
        if (-not $validPng) {
            throw "Screenshot is not a valid nonempty PNG: $png"
        }
        Write-Host "CAPTURED $png ($([math]::Round($imageBytes.Length / 1KB, 1)) KB)"
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

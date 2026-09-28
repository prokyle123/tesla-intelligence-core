$ErrorActionPreference = "Stop"

$Repo = "prokyle123/tesla-intelligence-core"
$Description = "Self-hosted Tesla predictive intelligence for Raspberry Pi - battery thermal forecasts, Level 1 charging analytics, learned departures, SOC prediction and PyTorch GRU."

$Topics = @(
  "tesla",
  "electric-vehicle",
  "ev",
  "raspberry-pi",
  "self-hosted",
  "machine-learning",
  "android",
  "pytorch",
  "time-series",
  "time-series-forecasting",
  "telemetry",
  "battery",
  "battery-analytics",
  "charging",
  "level-1-charging",
  "winter-driving",
  "teslamate",
  "tessie",
  "predictive-analytics",
  "energy-monitoring"
)

Write-Host "Tesla Intelligence Core - GitHub metadata" -ForegroundColor Cyan

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
  throw "GitHub CLI (gh) is not installed or not in PATH."
}

gh auth status
if ($LASTEXITCODE -ne 0) { throw "GitHub CLI is not authenticated." }

Write-Host "Updating repository description / community settings..."
gh api --method PATCH "repos/$Repo" -f "description=$Description" -F has_issues=true -F has_discussions=true -F has_wiki=false -F delete_branch_on_merge=true | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Repository metadata update failed." }

Write-Host "Replacing repository Topics with the discovery-focused set..."
$tmp = New-TemporaryFile
try {
  @{ names = $Topics } | ConvertTo-Json -Depth 3 | Set-Content $tmp -Encoding UTF8
  gh api --method PUT "repos/$Repo/topics" --input $tmp | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Topic update failed." }
}
finally {
  Remove-Item $tmp -Force -ErrorAction SilentlyContinue
}

$Labels = @(
  @{ name="compatibility"; color="0e8a16"; description="Vehicle, model-year or telemetry-source compatibility" },
  @{ name="telemetry"; color="1d76db"; description="Telemetry collection, normalization or signal mapping" },
  @{ name="neural-engine"; color="7057ff"; description="PyTorch GRU, model generations, governor or Truth Lab" },
  @{ name="winter-readiness"; color="0b5394"; description="Winter Readiness, cold soak, thermal forecasts or limiters" },
  @{ name="charging"; color="f9d0c4"; description="Charging behavior, Level 1, deadlines or energy flow" },
  @{ name="tessie"; color="5319e7"; description="Tessie source or backfill integration" },
  @{ name="teslamate"; color="0052cc"; description="TeslaMate MQTT integration" },
  @{ name="installer"; color="fbca04"; description="Install, update, systemd or deployment behavior" },
  @{ name="dashboard"; color="00b4d8"; description="Dashboard UI, visualization or usability" },
  @{ name="documentation"; color="0075ca"; description="Documentation improvements" }
)

Write-Host "Creating/updating useful issue labels..."
foreach ($label in $Labels) {
  gh label create $label.name -R $Repo --color $label.color --description $label.description --force | Out-Null
}

Write-Host ""
Write-Host "GitHub discovery metadata applied." -ForegroundColor Green
Write-Host "Description : $Description"
Write-Host "Topics      : $($Topics -join ', ')"
Write-Host "Discussions : enabled"
Write-Host "Wiki        : disabled"
Write-Host "Labels      : updated"

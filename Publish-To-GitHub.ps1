param(
  [string]$RepoName = "ghost-tesla-ai",
  [string]$Description = "Local-first Tesla winter-readiness, thermal, charging and trip-pattern AI for Raspberry Pi",
  [ValidateSet("public","private")][string]$Visibility = "public"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " GHOST Tesla AI - Publish to GitHub" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
  throw "GitHub CLI (gh) is not installed. Install it from https://cli.github.com/ then run this script again."
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git is not installed." }

try { gh auth status 2>$null | Out-Null } catch { gh auth login }
$Owner = (gh api user --jq .login).Trim()
if (-not $Owner) { throw "Could not determine the authenticated GitHub username." }

$entered = Read-Host "Repository name [$RepoName]"
if ($entered) { $RepoName = $entered.Trim() }
$vis = Read-Host "Visibility public/private [$Visibility]"
if ($vis) { $Visibility = $vis.Trim().ToLower() }
if ($Visibility -notin @("public","private")) { throw "Visibility must be public or private." }
$Full = "$Owner/$RepoName"

Write-Host "`nRepository : $Full"
Write-Host "Visibility : $Visibility"
Write-Host "Description: $Description"
$go = Read-Host "Create/update this repository and push everything? [Y/n]"
if ($go -and $go -notmatch '^[Yy]$') { Write-Host "Cancelled."; exit 0 }

if (-not (Test-Path .git)) {
  git init
  git branch -M main
}

if (-not (git config user.name)) { git config user.name $Owner }
if (-not (git config user.email)) {
  $Id = (gh api user --jq .id).Trim()
  git config user.email "$Id+$Owner@users.noreply.github.com"
}

git add -A
$pending = git status --porcelain
if ($pending) {
  git commit -m "Open-source GHOST Tesla AI v0.8.27.6"
}

$exists = $false
try { gh repo view $Full --json name 2>$null | Out-Null; $exists = $true } catch {}
if (-not $exists) {
  if ($Visibility -eq "public") { gh repo create $Full --public --description $Description }
  else { gh repo create $Full --private --description $Description }
}

$remote = git remote get-url origin 2>$null
if ($LASTEXITCODE -ne 0 -or -not $remote) { git remote add origin "https://github.com/$Full.git" }
else { git remote set-url origin "https://github.com/$Full.git" }

git push -u origin main

gh repo edit $Full --description $Description --enable-issues --enable-wiki=false
$topics = @("tesla","raspberry-pi","machine-learning","pytorch","tessie","teslamate","battery","energy-monitoring","winter","self-hosted","tailscale","flask")
foreach ($topic in $topics) { try { gh repo edit $Full --add-topic $topic | Out-Null } catch {} }

# Create/update a release archive without putting build output in git.
$Temp = Join-Path $env:TEMP "GhostTeslaAI-v0.8.27.6-source.zip"
Remove-Item $Temp -Force -ErrorAction SilentlyContinue
$Stage = Join-Path $env:TEMP "ghost-tesla-ai-release"
Remove-Item $Stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $Stage | Out-Null
Get-ChildItem -Force $Root | Where-Object { $_.Name -ne ".git" } | ForEach-Object { Copy-Item $_.FullName $Stage -Recurse -Force }
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Temp -Force
Remove-Item $Stage -Recurse -Force
try { gh release view v0.8.27.6 -R $Full 2>$null | Out-Null; gh release upload v0.8.27.6 $Temp -R $Full --clobber }
catch { gh release create v0.8.27.6 $Temp -R $Full --title "GHOST Tesla AI v0.8.27.6" --notes "First consolidated public release. See CHANGELOG.md and README.md for features and installation." }

Write-Host "`nPUBLISHED" -ForegroundColor Green
Write-Host "https://github.com/$Full"
Write-Host "One-line installer after publish:"
Write-Host "bash <(curl -fsSL https://raw.githubusercontent.com/$Full/main/install.sh)" -ForegroundColor Cyan

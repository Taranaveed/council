<#
.SYNOPSIS
  Verify that HEAD boots and passes suites from a clean git worktree.

.DESCRIPTION
  Creates a temporary worktree of the current HEAD (no dirty overlay),
  installs backend + market-service deps, starts both services, runs:
    - backend pytest
    - market-service npm test
    - scripts/smoke_deal_finder_region.py --fixtures
  Tears down services and removes the worktree unless -KeepWorktree.

  Local secrets are copied from the source repo's backend/.env and
  market-service/.env when present (never committed). Without them,
  fixture smoke and unit suites still run; live market calls may fail.

.EXAMPLE
  powershell -File scripts/verify_clean_checkout.ps1
#>
[CmdletBinding()]
param(
  [string]$RepoRoot = "",
  [string]$WorktreePath = "",
  [int]$BackendPort = 8011,
  [int]$MarketPort = 3011,
  [switch]$KeepWorktree
)

$ErrorActionPreference = "Stop"
$env:Path = "C:\Program Files\Git\cmd;C:\Program Files\Git\bin;" + $env:Path

if (-not $RepoRoot) {
  $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
if (-not $WorktreePath) {
  $WorktreePath = Join-Path (Split-Path $RepoRoot -Parent) ("sf-clean-verify-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
}

function Write-Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "FAIL: $msg" -ForegroundColor Red; exit 1 }

Set-Location $RepoRoot
$head = (git rev-parse HEAD).Trim()
Write-Step "Clean worktree at $WorktreePath (HEAD $head)"
if (Test-Path $WorktreePath) {
  git worktree remove --force $WorktreePath 2>$null
  if (Test-Path $WorktreePath) { Remove-Item -Recurse -Force $WorktreePath }
}
git worktree add $WorktreePath $head
if ($LASTEXITCODE -ne 0) { Fail "git worktree add failed" }

# Confirm worktree is clean (no dirty overlay)
Push-Location $WorktreePath
$dirty = git status --porcelain
if ($dirty) {
  Write-Host $dirty
  Fail "worktree is not clean"
}
Pop-Location

# Copy local env (optional but needed for some suites / live market)
foreach ($rel in @("backend\.env", "market-service\.env")) {
  $src = Join-Path $RepoRoot $rel
  $dst = Join-Path $WorktreePath $rel
  if (Test-Path $src) {
    Copy-Item $src $dst -Force
    Write-Host "copied $rel (local only)"
  } else {
    Write-Host "WARN: missing $src — continuing without it"
  }
}

Write-Step "Install backend deps"
Push-Location (Join-Path $WorktreePath "backend")
python -m pip install -r requirements.txt -q
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "pip install failed" }
Pop-Location

Write-Step "Install market-service deps"
Push-Location (Join-Path $WorktreePath "market-service")
npm install --no-fund --no-audit
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "npm install failed" }
Pop-Location

# Point backend at this worktree's market-service
$backendEnv = Join-Path $WorktreePath "backend\.env"
if (Test-Path $backendEnv) {
  $lines = Get-Content $backendEnv
  $out = @()
  $seen = $false
  foreach ($line in $lines) {
    if ($line -match '^\s*MARKET_SERVICE_URL\s*=') {
      $out += "MARKET_SERVICE_URL=http://127.0.0.1:$MarketPort"
      $seen = $true
    } else {
      $out += $line
    }
  }
  if (-not $seen) { $out += "MARKET_SERVICE_URL=http://127.0.0.1:$MarketPort" }
  Set-Content -Path $backendEnv -Value $out -Encoding utf8
}

$marketLog = Join-Path $WorktreePath "market-service.verify.log"
$backendLog = Join-Path $WorktreePath "backend.verify.log"
$marketProc = $null
$backendProc = $null

try {
  Write-Step "Boot market-service :$MarketPort"
  $marketProc = Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c", "set PORT=$MarketPort&& node index.js" `
    -WorkingDirectory (Join-Path $WorktreePath "market-service") `
    -RedirectStandardOutput $marketLog -RedirectStandardError $marketLog `
    -PassThru -WindowStyle Hidden

  Write-Step "Boot backend :$BackendPort"
  $backendProc = Start-Process -FilePath "python" `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$BackendPort" `
    -WorkingDirectory (Join-Path $WorktreePath "backend") `
    -RedirectStandardOutput $backendLog -RedirectStandardError $backendLog `
    -PassThru -WindowStyle Hidden

  # Wait for health
  $okMarket = $false
  $okBackend = $false
  for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 1
    try {
      $r = Invoke-WebRequest -Uri "http://127.0.0.1:$MarketPort/health" -UseBasicParsing -TimeoutSec 2
      if ($r.StatusCode -eq 200) { $okMarket = $true }
    } catch {}
    try {
      $r = Invoke-WebRequest -Uri "http://127.0.0.1:$BackendPort/health" -UseBasicParsing -TimeoutSec 2
      if ($r.StatusCode -eq 200) { $okBackend = $true }
    } catch {}
    if ($okMarket -and $okBackend) { break }
  }
  if (-not $okMarket) {
    Write-Host (Get-Content $marketLog -ErrorAction SilentlyContinue | Select-Object -Last 40)
    Fail "market-service failed to become healthy on :$MarketPort"
  }
  if (-not $okBackend) {
    Write-Host (Get-Content $backendLog -ErrorAction SilentlyContinue | Select-Object -Last 40)
    Fail "backend failed to become healthy on :$BackendPort"
  }
  Write-Host "boot ok (market + backend)"

  Write-Step "Backend pytest"
  Push-Location (Join-Path $WorktreePath "backend")
  python -m pytest tests/ -q --tb=line
  $backendCode = $LASTEXITCODE
  Pop-Location
  if ($backendCode -ne 0) { Fail "backend pytest failed (exit $backendCode)" }

  Write-Step "Market-service npm test"
  Push-Location (Join-Path $WorktreePath "market-service")
  npm test
  $marketCode = $LASTEXITCODE
  Pop-Location
  if ($marketCode -ne 0) { Fail "market-service tests failed (exit $marketCode)" }

  Write-Step "Fixture smoke"
  Push-Location $WorktreePath
  $env:PYTHONUNBUFFERED = "1"
  $env:PYTHONIOENCODING = "utf-8"
  Remove-Item Env:SMOKE_BASE_URL -ErrorAction SilentlyContinue
  # Prefer in-process TestClient against clean tree code
  python -u scripts/smoke_deal_finder_region.py --fixtures
  $smokeCode = $LASTEXITCODE
  Pop-Location
  if ($smokeCode -ne 0) { Fail "fixture smoke failed (exit $smokeCode)" }

  Write-Step "CLEAN CHECKOUT VERIFY PASSED"
  Write-Host "HEAD: $head"
  Write-Host "Worktree: $WorktreePath"
  exit 0
}
finally {
  if ($backendProc -and -not $backendProc.HasExited) {
    Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue
  }
  if ($marketProc -and -not $marketProc.HasExited) {
    Stop-Process -Id $marketProc.Id -Force -ErrorAction SilentlyContinue
  }
  if (-not $KeepWorktree) {
    Set-Location $RepoRoot
    git worktree remove --force $WorktreePath 2>$null
    if (Test-Path $WorktreePath) { Remove-Item -Recurse -Force $WorktreePath -ErrorAction SilentlyContinue }
  } else {
    Write-Host "Keeping worktree at $WorktreePath"
  }
}

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
  market-service/.env when present (never committed).

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
  $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
  $WorktreePath = Join-Path (Split-Path $RepoRoot -Parent) ("sf-clean-verify-" + $stamp)
}

function Write-Step([string]$msg) {
  Write-Host ""
  Write-Host "=== $msg ===" -ForegroundColor Cyan
}

function Fail([string]$msg) {
  Write-Host "FAIL: $msg" -ForegroundColor Red
  exit 1
}

Set-Location $RepoRoot
$head = (git rev-parse HEAD).Trim()
Write-Step "Clean worktree at $WorktreePath (HEAD $head)"
if (Test-Path $WorktreePath) {
  git worktree remove --force $WorktreePath 2>$null | Out-Null
  if (Test-Path $WorktreePath) {
    Remove-Item -Recurse -Force $WorktreePath
  }
}
git worktree add $WorktreePath $head
if ($LASTEXITCODE -ne 0) { Fail "git worktree add failed" }

Push-Location $WorktreePath
$dirty = git status --porcelain
if ($dirty) {
  Write-Host $dirty
  Pop-Location
  Fail "worktree is not clean"
}
Pop-Location

foreach ($rel in @("backend\.env", "market-service\.env")) {
  $src = Join-Path $RepoRoot $rel
  $dst = Join-Path $WorktreePath $rel
  if (Test-Path $src) {
    Copy-Item $src $dst -Force
    Write-Host "copied $rel (local only)"
  } else {
    Write-Host "WARN: missing $src - continuing without it"
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

$backendEnv = Join-Path $WorktreePath "backend\.env"
if (Test-Path $backendEnv) {
  $lines = Get-Content $backendEnv
  $out = New-Object System.Collections.Generic.List[string]
  $seen = $false
  foreach ($line in $lines) {
    if ($line -match '^\s*MARKET_SERVICE_URL\s*=') {
      [void]$out.Add("MARKET_SERVICE_URL=http://127.0.0.1:$MarketPort")
      $seen = $true
    } else {
      [void]$out.Add($line)
    }
  }
  if (-not $seen) {
    [void]$out.Add("MARKET_SERVICE_URL=http://127.0.0.1:$MarketPort")
  }
  Set-Content -Path $backendEnv -Value $out.ToArray() -Encoding utf8
}

$marketOut = Join-Path $WorktreePath "market-service.verify.out.log"
$marketErr = Join-Path $WorktreePath "market-service.verify.err.log"
$backendOut = Join-Path $WorktreePath "backend.verify.out.log"
$backendErr = Join-Path $WorktreePath "backend.verify.err.log"
$marketProc = $null
$backendProc = $null
$passed = $false

try {
  Write-Step "Boot market-service :$MarketPort"
  $marketCmd = "set PORT=$MarketPort& node index.js"
  $marketProc = Start-Process -FilePath "cmd.exe" `
    -ArgumentList @("/c", $marketCmd) `
    -WorkingDirectory (Join-Path $WorktreePath "market-service") `
    -RedirectStandardOutput $marketOut `
    -RedirectStandardError $marketErr `
    -PassThru -WindowStyle Hidden

  Write-Step "Boot backend :$BackendPort"
  $backendProc = Start-Process -FilePath "python" `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$BackendPort") `
    -WorkingDirectory (Join-Path $WorktreePath "backend") `
    -RedirectStandardOutput $backendOut `
    -RedirectStandardError $backendErr `
    -PassThru -WindowStyle Hidden

  $okMarket = $false
  $okBackend = $false
  for ($i = 0; $i -lt 45; $i++) {
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
    Write-Host "--- market stdout ---"
    Get-Content $marketOut -ErrorAction SilentlyContinue | Select-Object -Last 40
    Write-Host "--- market stderr ---"
    Get-Content $marketErr -ErrorAction SilentlyContinue | Select-Object -Last 40
    Fail "market-service failed to become healthy on :$MarketPort"
  }
  if (-not $okBackend) {
    Write-Host "--- backend stdout ---"
    Get-Content $backendOut -ErrorAction SilentlyContinue | Select-Object -Last 40
    Write-Host "--- backend stderr ---"
    Get-Content $backendErr -ErrorAction SilentlyContinue | Select-Object -Last 40
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
  python -u scripts/smoke_deal_finder_region.py --fixtures
  $smokeCode = $LASTEXITCODE
  Pop-Location
  if ($smokeCode -ne 0) { Fail "fixture smoke failed (exit $smokeCode)" }

  Write-Step "CLEAN CHECKOUT VERIFY PASSED"
  Write-Host "HEAD: $head"
  Write-Host "Worktree: $WorktreePath"
  $passed = $true
}
finally {
  foreach ($proc in @($backendProc, $marketProc)) {
    if ($proc -and -not $proc.HasExited) {
      Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
  }
  # Also stop child node/python that may hold worktree files open
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine.Contains($WorktreePath) } |
    ForEach-Object {
      Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
  Start-Sleep -Seconds 1
  if (-not $KeepWorktree) {
    Set-Location $RepoRoot
    git worktree remove --force $WorktreePath 2>$null | Out-Null
    if (Test-Path $WorktreePath) {
      Remove-Item -Recurse -Force $WorktreePath -ErrorAction SilentlyContinue
    }
  } else {
    Write-Host "Keeping worktree at $WorktreePath"
  }
}

if (-not $passed) { exit 1 }
exit 0

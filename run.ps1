param(
  [ValidateSet("run", "doctor", "repair", "docker", "stop", "logs")]
  [string]$Action = "run",
  [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
. .\scripts\install-utils.ps1
Initialize-Install -RepositoryRoot $PSScriptRoot -ProductName "AgentGymnasium"
trap { Write-InstallFailure $_; Exit-InstallLock; exit 1 }
$UvVersion = "0.12.5"
$Url = "http://127.0.0.1:8765"

function Resolve-Uv {
  $command = Get-Command uv -ErrorAction SilentlyContinue
  $candidates = @($(if ($command) { $command.Source }), "$env:USERPROFILE\.local\bin\uv.exe", "$env:USERPROFILE\.cargo\bin\uv.exe")
  foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
  }
  return $null
}

function Install-Uv {
  $installer = Join-Path $env:TEMP "agentarium-uv-$UvVersion.ps1"
  try {
    Save-InstallDownload -Url "https://astral.sh/uv/$UvVersion/install.ps1" -Destination $installer -Label "uv download"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer
  } finally {
    Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
  }
  $uv = Resolve-Uv
  if (-not $uv) { throw "uv installed but could not be located. Open a new terminal and run this file again." }
  return $uv
}

function Wait-Ready([string]$HealthUrl) {
  for ($i = 0; $i -lt 60; $i++) {
    try {
      Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2 | Out-Null
      return $true
    } catch { Start-Sleep -Milliseconds 500 }
  }
  return $false
}
function Test-Ready([string]$HealthUrl) {
  try { Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2 | Out-Null; return $true } catch { return $false }
}

if ($Action -in @("docker", "stop", "logs")) {
  $docker = Get-Command docker -ErrorAction SilentlyContinue
  $engineRunning = $false
  if ($docker) { docker info *> $null; $engineRunning = ($LASTEXITCODE -eq 0) }
  if ($Action -eq "stop" -and -not $engineRunning) { Write-Host "The native server runs in the foreground. Press Ctrl+C in its terminal to stop it."; exit 0 }
  if ($Action -eq "logs" -and -not $engineRunning) { Write-Host "The native server writes logs to its foreground terminal."; exit 0 }
  if (-not $docker) { throw "Docker is not installed. Install Docker Desktop, then rerun with '$Action'." }
  if (-not $engineRunning) { throw "Docker is installed but its engine is not running." }
  if ($Action -eq "stop") { docker compose down; exit $LASTEXITCODE }
  if ($Action -eq "logs") { docker compose logs --follow; exit $LASTEXITCODE }
  Enter-InstallLock
  Assert-InstallFreeSpace -Path $PSScriptRoot -RequiredGB 2
  docker compose up --detach --build
  if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed to start AgentGymnasium." }
  if (-not (Wait-Ready "$Url/api/health")) { docker compose logs; throw "AgentGymnasium did not become healthy at $Url." }
  Complete-Install
  Write-Host "AgentGymnasium is ready at $Url" -ForegroundColor Green
  if (-not $NoBrowser) { Start-Process $Url }
  exit 0
}

$uv = Resolve-Uv
if ($Action -eq "doctor") {
  if (-not $uv) { throw "uv is missing. Run .\run.ps1 once to install the managed runtime." }
  & $uv run --frozen --no-sync agentarium --help *> $null
  if ($LASTEXITCODE -ne 0) { throw "The managed AgentGymnasium environment is missing or stale. Run .\run.ps1 repair." }
  if (-not (Test-Path -LiteralPath "backend\agentarium\static\index.html")) { throw "The prebuilt web UI is missing." }
  Write-Host "AgentGymnasium native environment is ready." -ForegroundColor Green
  exit 0
}

Enter-InstallLock
Assert-InstallFreeSpace -Path $PSScriptRoot -RequiredGB 2
if (-not $uv) { $uv = Install-Uv }
Write-Host "==> Synchronizing the locked runtime" -ForegroundColor Cyan
$syncArgs = @("sync", "--frozen", "--no-dev")
if ($Action -eq "repair") { $syncArgs += "--reinstall" }
Invoke-InstallRetry "dependency synchronization" {
  $output = & $uv @syncArgs 2>&1
  if ($LASTEXITCODE -ne 0) { throw "uv sync failed: $($output -join [Environment]::NewLine)" }
  $output | Write-Host
}

if (-not (Test-Path -LiteralPath "backend\agentarium\static\index.html")) {
  if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "The prebuilt UI is missing and Node/npm is unavailable. Restore the release payload or install Node 20+." }
  Push-Location frontend
  try {
    Invoke-InstallRetry "frontend dependency installation" {
      $output = & npm ci 2>&1
      if ($LASTEXITCODE -ne 0) { throw "npm ci failed: $($output -join [Environment]::NewLine)" }
      $output | Write-Host
    }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
  } finally { Pop-Location }
}

Complete-Install
if (Test-Ready "$Url/api/health") {
  Write-Host "AgentGymnasium is already running at $Url" -ForegroundColor Green
  if (-not $NoBrowser) { Start-Process $Url }
  exit 0
}
$serveArgs = @("run", "--frozen", "--no-sync", "agentarium", "serve", "--no-reload")
if (-not $NoBrowser) { $serveArgs += "--open" }
Write-Host "==> Starting AgentGymnasium at $Url" -ForegroundColor Cyan
& $uv @serveArgs
exit $LASTEXITCODE

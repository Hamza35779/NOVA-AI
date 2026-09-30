<#
.SYNOPSIS
    Install NOVA AI on a Windows PC with NO internet connection.

.DESCRIPTION
    Run this from INSIDE an offline bundle produced by make-offline-bundle.ps1.
    It uses only the files that sit next to it:

      bin\uv.exe        -> the uv binary (never downloaded)
      runtime\          -> a uv-managed CPython (never downloaded)
      cache\            -> a pre-populated wheel cache (never downloaded)
      app\              -> NOVA AI source + uv.lock
      EXTRAS            -> which uv extras to install
      models\*.gguf     -> optional offline model

    Everything runs under `uv ... --offline`, so if the bundle is complete it
    installs with zero network. If it is missing something, uv fails loudly
    rather than silently phoning home.

.USAGE
    powershell -ExecutionPolicy Bypass -File install-offline.ps1
#>

[CmdletBinding()]
param(
    [switch] $Force
)

$ErrorActionPreference = 'Stop'

function Write-Info ($m) { Write-Host "[info]  $m" -ForegroundColor Cyan }
function Write-Ok   ($m) { Write-Host "[ok]    $m" -ForegroundColor Green }
function Write-Warn2 ($m){ Write-Host "[warn]  $m" -ForegroundColor Yellow }
function Write-Fail ($m) { Write-Host "[fail]  $m" -ForegroundColor Red; exit 1 }

function Native {
    param([string] $Exe, [string[]] $Params = @())
    $eap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $o = & $Exe @Params 2>&1; $c = $LASTEXITCODE } finally { $ErrorActionPreference = $eap }
    return @{ Out = $o; Code = $c }
}

$root = $PSScriptRoot
$uv    = Join-Path $root 'bin\uv.exe'
$app   = Join-Path $root 'app'
$cache = Join-Path $root 'cache'
$rt    = Join-Path $root 'runtime'
if (-not (Test-Path $uv))    { Write-Fail "Bundle incomplete: missing $uv" }
if (-not (Test-Path $app))   { Write-Fail "Bundle incomplete: missing $app" }
if (-not (Test-Path (Join-Path $app 'uv.lock'))) { Write-Fail "Bundle incomplete: missing app\uv.lock" }

# Force uv to use ONLY the bundled interpreter + cache, and never hit the net.
$env:UV_PYTHON_INSTALL_DIR    = $rt
$env:UV_CACHE_DIR             = $cache
$env:UV_PYTHON_PREFERENCE     = 'only-managed'
$env:NOVA_AI_NO_UPDATER       = '1'
$env:Path                     = "$(Join-Path $root 'bin');$env:Path"
if (Test-Path (Join-Path $root 'VERSION')) {
    $env:SETUPTOOLS_SCM_PRETEND_VERSION = (Get-Content (Join-Path $root 'VERSION')).Trim()
}

# Which extras to install (recorded by the bundle maker).
$Extras = 'server'
if (Test-Path (Join-Path $root 'EXTRAS')) { $Extras = (Get-Content (Join-Path $root 'EXTRAS')).Trim() }
Write-Info "Installing NOVA AI offline (extras: $Extras)..."

$extraArgs = @()
foreach ($e in ($Extras -split '[,\s]+' | Where-Object { $_ })) { $extraArgs += @('--extra', $e) }

# Auto-heal: a half-created / invalid .venv (dir present but no
# Scripts\python.exe) makes uv abort with "not a valid Python environment
# (no Python executable was found)" instead of self-correcting. Remove it so
# the offline sync can rebuild it from the bundled interpreter + wheel cache.
$bvenv = Join-Path $app '.venv'
if ((Test-Path $bvenv) -and -not (Test-Path (Join-Path $bvenv 'Scripts\python.exe'))) {
    Write-Info "Removing invalid .venv (no Scripts\python.exe) at $bvenv ..."
    try {
        Remove-Item -Recurse -Force $bvenv -ErrorAction Stop
    } catch {
        # A running nova/python may hold a Windows lock; stop it, then retry.
        Write-Warn2 'Could not remove .venv (a process likely holds a lock); stopping it...'
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.ExecutablePath -like "$bvenv*" } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Milliseconds 500
        Remove-Item -Recurse -Force $bvenv -ErrorAction SilentlyContinue
    }
    if (Test-Path $bvenv) { Write-Fail "Stale .venv still present: $bvenv. Close any running 'nova' and re-run." }
    Write-Ok 'Invalid .venv removed; offline sync will recreate it.'
}

Push-Location $app
try {
    $sync = Native $uv (@('sync', '--frozen', '--offline', '--no-dev') + $extraArgs)
    $sync.Out | Select-Object -Last 12 | ForEach-Object { Write-Host $_ }
    if ($sync.Code -ne 0) {
        Write-Fail "Offline install failed (exit $($sync.Code)). The bundle cache may be incomplete for these extras; rebuild it with the same -Extras."
    }
} finally { Pop-Location }
Write-Ok 'Environment installed (offline)'

# --- optional GGUF model: place it where NOVA's model host looks ---
$modelDir = Join-Path $root 'models'
if ((Test-Path $modelDir) -and (Get-ChildItem $modelDir -Filter *.gguf -ErrorAction SilentlyContinue)) {
    $dest = Join-Path $env:USERPROFILE '.nova_ai\models'
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Copy-Item (Join-Path $modelDir '*.gguf') $dest -Force
    Write-Ok "Model(s) copied to $dest (set it as default via 'nova model' or config; needs the GGUF engine)."
}

# --- install the robust nova.cmd launcher ---
$binDir = Join-Path $env:USERPROFILE '.local\bin'
if (-not (Test-Path $binDir)) { New-Item -ItemType Directory -Force -Path $binDir | Out-Null }
$shimPath = Join-Path $binDir 'nova.cmd'
$shim = @"
@echo off
setlocal
set "NOVA_HOME=$app"
set "VENV=%NOVA_HOME%\.venv\Scripts\nova.exe"
set "UV=$uv"
if exist "%VENV%" (
  "%VENV%" %*
) else (
  "%UV%" run --project "%NOVA_HOME%" nova %*
)
"@
Set-Content -Path $shimPath -Value $shim -Encoding ASCII
Write-Ok "nova launcher installed at $shimPath"

# ensure the launcher dir is on the persisted User PATH
$userPath = [System.Environment]::GetEnvironmentVariable('Path', 'User')
$onPath = $false
if ($userPath) {
    foreach ($entry in ($userPath -split ';')) {
        if ([System.Environment]::ExpandEnvironmentVariables($entry) -ieq $binDir) { $onPath = $true; break }
    }
}
if (-not $onPath) {
    $newPath = if ($userPath) { "$userPath;$binDir" } else { $binDir }
    [System.Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
    Write-Info "Added $binDir to your User PATH (new shells pick it up)."
}

# --- verify ---
Write-Info 'Verifying...'
$env:Path = "$binDir;$env:Path"
$check = Native $shimPath @('--version')
$ver = ($check.Out | Out-String).Trim()
if ($check.Code -eq 0 -and $ver) { Write-Ok "nova -> $ver" } else { Write-Warn2 'Launcher installed; open a new PowerShell and run nova --version.' }

Write-Host ''
Write-Host '  +---------------------------------------------+' -ForegroundColor Green
Write-Host '  |   NOVA AI installed OFFLINE - done          |' -ForegroundColor Green
Write-Host '  +---------------------------------------------+' -ForegroundColor Green
Write-Host ''
Write-Host "  App:      $app"
Write-Host "  Launcher: $shimPath"
Write-Host ''
Write-Host '  Open a NEW PowerShell and run:' -ForegroundColor Yellow
Write-Host '     nova doctor'
Write-Host '     nova ask "hello"'
Write-Host ''
Write-Host '  NOTE: local chat still needs a model engine. Fully offline options:'
Write-Host '    - bundle a GGUF with make-offline-bundle.ps1 -Gguf <file>'
Write-Host '    - or pre-install Ollama + run "ollama pull <model>" on the target'

<#
.SYNOPSIS
    Build a fully OFFLINE NOVA AI deployment bundle for Windows x64.

.DESCRIPTION
    Run this ONCE on an internet-connected Windows box. It produces a
    self-contained folder (or .zip) that installs NOVA AI on a target PC
    with NO internet at all, because it bundles:

      * the `uv` binary                -> bundle\bin
      * a uv-managed CPython 3.13      -> bundle\runtime
      * a project-scoped wheel cache   -> bundle\cache   (all deps, prebuilt)
      * the NOVA AI source + lockfile  -> bundle\app
      * an offline installer           -> bundle\install-offline.ps1

    The target simply runs install-offline.ps1, which drives
    `uv sync --frozen --offline` against the shipped cache/interpreter.

    Offline inference (optional): pass -Gguf <path.gguf> to drop a model into
    bundle\models and add the in-process GGUF extra so NOVA can run it with no
    server and no downloads. NOTE: the GGUF engine (llama-cpp-python) is a
    compiled wheel; bundling it requires it to build/download here first.

.USAGE
    powershell -ExecutionPolicy Bypass -File deploy\windows\make-offline-bundle.ps1
    powershell -ExecutionPolicy Bypass -File deploy\windows\make-offline-bundle.ps1 -Extras "server" -Zip
    powershell -ExecutionPolicy Bypass -File deploy\windows\make-offline-bundle.ps1 -Gguf "C:\models\qwen2.5:0.5b-q4.gguf"

.FLAGS
    -BundleDir   Where to build the bundle (default: .\offline-bundle next to repo).
    -Extras      Comma/space separated uv extras to bundle (default: server).
    -PythonVersion  Managed CPython to bundle (default: 3.13).
    -Gguf        Optional .gguf file to include for offline inference.
    -Zip         Also produce a single .zip of the bundle when done.
    -RepoRoot    Explicit source repo root (default: this script's repo).
#>

[CmdletBinding()]
param(
    [string] $BundleDir = '',
    [string] $Extras = 'server',
    [string] $PythonVersion = '3.13',
    [string] $Gguf = '',
    [switch] $Zip,
    [string] $RepoRoot = ''
)

$ErrorActionPreference = 'Stop'

function Write-Info ($m) { Write-Host "[info] $m" -ForegroundColor Cyan }
function Write-Ok   ($m) { Write-Host "[ok]   $m" -ForegroundColor Green }
function Write-Fail ($m) { Write-Host "[fail] $m" -ForegroundColor Red; exit 1 }

# Native helper (uv writes progress to stderr -> Stop preference would abort).
function Native {
    param([string] $Exe, [string[]] $Params = @())
    $eap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $o = & $Exe @Params 2>&1; $c = $LASTEXITCODE } finally { $ErrorActionPreference = $eap }
    return @{ Out = $o; Code = $c }
}

# --- locate repo + uv ---
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
if (-not (Test-Path (Join-Path $RepoRoot 'pyproject.toml'))) { Write-Fail "Repo root not found: $RepoRoot" }
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { $uv = Join-Path $env:USERPROFILE '.local\bin\uv.exe' }
if (-not (Test-Path $uv)) { Write-Fail "uv not found. Run bootstrap-nova.ps1 first (this maker needs an online uv)." }
Write-Ok "uv: $uv"

if (-not $BundleDir) { $BundleDir = Join-Path (Split-Path -Parent $RepoRoot) 'NOVA-AI-offline' }
Write-Info "Bundle root: $BundleDir"

$binP   = Join-Path $BundleDir 'bin'
$rtP    = Join-Path $BundleDir 'runtime'
$cacheP = Join-Path $BundleDir 'cache'
$appP   = Join-Path $BundleDir 'app'
$modelP = Join-Path $BundleDir 'models'
foreach ($d in @($BundleDir, $binP, $rtP, $cacheP, $appP)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }

# --- 1. ship uv binary ---
Copy-Item $uv (Join-Path $binP 'uv.exe') -Force
Write-Ok 'uv.exe copied'

# --- 2. ship a managed CPython INTO the bundle (no system python needed) ---
Write-Info "Installing uv-managed CPython $PythonVersion into $rtP ..."
$env:UV_PYTHON_INSTALL_DIR = $rtP
$py = Native $uv @('python', 'install', $PythonVersion)
$py.Out | ForEach-Object { Write-Host $_ }
if ($py.Code -ne 0) { Write-Fail 'uv python install failed.' }
Write-Ok 'Managed CPython bundled'

# --- 3. copy the source (exclude heavy/volatile trees; rebuild venv on target) ---
Write-Info 'Copying project source (excluding .git/.venv/caches/assets)...'
$robocopyArgs = @(
    $RepoRoot, $appP, '/MIR',
    '/XD', '.git', '.venv', '__pycache__', 'node_modules', 'build', 'dist',
    '.pytest_cache', '.mypy_cache', '.ruff_cache', 'assets', 'docs', '.github', $BundleDir,
    '/XF', '*.log',
    '/NFL', '/NDL', '/NJH', '/NJS', '/NP'
)
$rc = & robocopy @robocopyArgs
if ($rc -ge 8) { Write-Fail "robocopy failed with code $rc." }
Write-Ok 'Source copied to bundle\app'

# capture a stable version string so the target build keeps a real version
$ver = ''
try { $ver = (Native (Join-Path $appP '.venv\Scripts\python.exe') @('-c','import nova_ai;print(nova_ai.__version__)')).Out -join '' } catch {}
if (-not $ver) { $ver = '0.0.0+offline' }
Set-Content -Path (Join-Path $BundleDir 'VERSION') -Value $ver.Trim() -Encoding ASCII
Write-Ok "Version recorded: $($ver.Trim())"

# --- 4. populate a CLEAN project-scoped cache (this is the online step) ---
Write-Info "Populating offline wheel cache via 'uv sync' (extras: $Extras)..."
$extraArgs = @()
foreach ($e in ($Extras -split '[,\s]+' | Where-Object { $_ })) { $extraArgs += @('--extra', $e) }
Push-Location $appP
try {
    $env:UV_CACHE_DIR = $cacheP
    $env:SETUPTOOLS_SCM_PRETEND_VERSION = $ver.Trim()
    $sync = Native $uv (@('sync', '--frozen') + $extraArgs)
    $sync.Out | Select-Object -Last 8 | ForEach-Object { Write-Host $_ }
    if ($sync.Code -ne 0) { Write-Fail "uv sync failed (exit $($sync.Code)); cache not built." }
} finally { Pop-Location }
Write-Ok 'Wheel cache built'

# remove the build-time .venv; target recreates it offline from cache
Remove-Item -Recurse -Force (Join-Path $appP '.venv') -ErrorAction SilentlyContinue
Write-Info 'Removed build-time .venv (target rebuilds offline).'

# --- 5. optional GGUF model for offline inference ---
if ($Gguf) {
    if (-not (Test-Path $Gguf)) { Write-Fail "GGUF not found: $Gguf" }
    New-Item -ItemType Directory -Force -Path $modelP | Out-Null
    Copy-Item $Gguf (Join-Path $modelP (Split-Path -Leaf $Gguf)) -Force
    Write-Ok "Model bundled: $(Split-Path -Leaf $Gguf)  (install-offline adds the GGUF engine)"
}

# --- 6. record chosen extras + write the offline installer ---
Set-Content -Path (Join-Path $BundleDir 'EXTRAS') -Value $Extras -Encoding ASCII

$installer = Join-Path $BundleDir 'install-offline.ps1'
Copy-Item (Join-Path $PSScriptRoot 'install-offline.ps1') $installer -Force
if (-not (Test-Path $installer)) { Write-Fail "install-offline.ps1 not found next to this maker at $PSScriptRoot" }
Write-Ok 'Offline installer placed in bundle'

# --- 7. optional zip ---
if ($Zip) {
    $zipPath = "$BundleDir.zip"
    Write-Info "Compressing to $zipPath (this can take a minute)..."
    Compress-Archive -Path (Join-Path $BundleDir '*') -DestinationPath $zipPath -Force
    Write-Ok "Bundle zip: $zipPath"
}

Write-Host ''
Write-Host '  +---------------------------------------------+' -ForegroundColor Green
Write-Host '  |   Offline bundle ready                        |' -ForegroundColor Green
Write-Host '  +---------------------------------------------+' -ForegroundColor Green
Write-Host ''
Write-Host "  Bundle:  $BundleDir"
Write-Host "  Extras:  $Extras"
if (Test-Path (Join-Path $modelP '_')) { }
Write-Host ''
Write-Host '  DEPLOY TO A TARGET PC (no internet needed):' -ForegroundColor Yellow
Write-Host "   1. Copy the '$(Split-Path -Leaf $BundleDir)' folder to the PC."
Write-Host   '   2. From inside it, run:'
Write-Host   '        powershell -ExecutionPolicy Bypass -File install-offline.ps1'
Write-Host   '   3. Open a NEW PowerShell and run:  nova doctor   |   nova ask "..."'
Write-Host ''

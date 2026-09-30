<#
.SYNOPSIS
    NOVA AI self-contained bootstrap for native Windows (deploy-anywhere).

.DESCRIPTION
    One script that installs EVERYTHING NOVA AI needs on a clean Windows box,
    requiring no pre-installed Python, git, or uv - just PowerShell + internet.

    The trick that makes it fully self-contained: `uv` can download and manage
    its own standalone CPython (`uv python install`), so the system "Store
    alias" Python and winget are no longer hard dependencies.

    Steps (all idempotent / re-runnable):
      1. Refuse non-Windows / Windows < 10 1809.
      2. Install `uv` (https://astral.sh/uv) if it is not on PATH.
      3. Install a uv-managed CPython (default 3.13) if one is absent.
      4. Locate the NOVA AI project folder (this script's repo root, or
         $RepoRoot, or clone if git is available).
      5. `uv sync --extra desktop`  -> creates .venv with all runtime deps.
      6. Install a robust `nova.cmd` launcher into %USERPROFILE%\.local\bin
         (already on PATH, and it resolves uv by ABSOLUTE path so it never
         breaks on an un-refreshed PATH like the old shim did).
      7. Optional (-Full): install + start Ollama and pull a starter model.
      8. Verify with `nova --version` and `nova doctor`.

    USAGE
      From inside the copied project folder (recommended - no git needed):
        powershell -ExecutionPolicy Bypass -File deploy\windows\bootstrap-nova.ps1
      Full setup (also installs Ollama + a model, ~1.8 GB download):
        powershell -ExecutionPolicy Bypass -File deploy\windows\bootstrap-nova.ps1 -Full

    FLAGS
      -Full            Install/start Ollama and pull $Model (default: off).
      -SkipDeps        Do not run `uv sync` (already done / offline).
      -Force           Re-run every step even if state says done.
      -Model <tag>     Starter model to pull with -Full (default qwen2.5:0.5b).
      -Extras <list>   Comma/space uv extras to install (default: desktop).
      -PythonVersion   uv-managed CPython to install (default: 3.13).
      -RepoRoot <dir>  Explicit NOVA AI project directory.

    ENVIRONMENT OVERRIDES
      $env:NOVA_AI_REPO_URL   git URL used only if it must clone (no local folder).
      $env:NOVA_AI_HOME       Same as -RepoRoot.

.NOTES
    The `nova` launcher becomes available in a NEW PowerShell window (PATH is a
    User-scope change). This script pre-pends the dir for its own verification.
#>

[CmdletBinding()]
param(
    [switch] $Full,
    [switch] $SkipDeps,
    [switch] $Force,
    [string] $Model = 'qwen2.5:0.5b',
    [string] $Extras = 'desktop',
    [string] $PythonVersion = '3.13',
    [string] $RepoRoot = ''
)

$ErrorActionPreference = 'Stop'

# Make uv prefer its own managed CPython over any system / MS Store "python"
# stub. This is the core of the deploy-anywhere robustness.
$env:UV_PYTHON_PREFERENCE = 'only-managed'

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
function Write-Info  ($m) { Write-Host "[info]  $m" -ForegroundColor Cyan }
function Write-Ok    ($m) { Write-Host "[ok]    $m" -ForegroundColor Green }
function Write-Warn2 ($m) { Write-Host "[warn]  $m" -ForegroundColor Yellow }
function Write-Fail  ($m) { Write-Host "[fail]  $m" -ForegroundColor Red; exit 1 }

# Pull latest Machine + User PATH from the registry into this session,
# expanding REG_EXPAND_SZ placeholders. Tools installed mid-run (uv) update
# the User PATH but the running process can't see it without this.
function Update-PathFromRegistry {
    $mp = [System.Environment]::GetEnvironmentVariable('Path', 'Machine')
    $up = [System.Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = [System.Environment]::ExpandEnvironmentVariables("$mp;$up")
}

# Run a native executable safely. uv / ollama / nova write progress and
# diagnostics to STDERR, which under $ErrorActionPreference='Stop' becomes a
# terminating NativeCommandError (same trap install.ps1 documents at L343-348).
# We relax the preference just for the external call and report the merged
# output + exit code so callers can branch on $LASTEXITCODE themselves.
function Native {
    param([string] $Exe, [string[]] $Params = @())
    $eap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $o = & $Exe @Params 2>&1
        $c = $LASTEXITCODE
    } finally { $ErrorActionPreference = $eap }
    return @{ Out = $o; Code = $c }
}

# ---------------------------------------------------------------------------
# 1. OS check
# ---------------------------------------------------------------------------
Write-Info 'Checking OS...'
if ($PSVersionTable.Platform -and $PSVersionTable.Platform -ne 'Win32NT') {
    Write-Fail 'bootstrap-nova.ps1 is for native Windows.'
}
$build = [System.Environment]::OSVersion.Version.Build
if ($build -lt 17763) {
    Write-Fail "Windows 10 1809 (build 17763) or newer required. Detected build $build."
}
Write-Ok "Windows build $build"

# ---------------------------------------------------------------------------
# 2. Ensure uv
# ---------------------------------------------------------------------------
Write-Info 'Checking uv...'
$uvExe = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uvExe) {
    Write-Info '  uv not found - installing via astral.sh/uv...'
    try {
        Invoke-RestMethod -Uri 'https://astral.sh/uv/install.ps1' -UseBasicParsing | Invoke-Expression
    } catch {
        Write-Fail "uv install failed: $($_.Exception.Message)"
    }
    Update-PathFromRegistry
    $uvDir = Join-Path $env:USERPROFILE '.local\bin'
    if (Test-Path (Join-Path $uvDir 'uv.exe')) { $env:Path = "$uvDir;$env:Path" }
    $uvExe = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if (-not $uvExe) { Write-Fail "uv installed but not on PATH. Re-open PowerShell and re-run." }
}
Write-Ok "uv ($uvExe)"

# ---------------------------------------------------------------------------
# 3. Ensure a uv-managed CPython (no system python needed)
# ---------------------------------------------------------------------------
Write-Info "Ensuring uv-managed Python $PythonVersion..."
$pyInstall = Native $uvExe @('python', 'install', $PythonVersion)
if ($pyInstall.Code -ne 0) {
    Write-Warn2 "uv python install $PythonVersion exited $($pyInstall.Code); probing any 3.10-3.13."
}
# Confirm at least one usable managed interpreter exists.
$found = $null
foreach ($v in @('3.13', '3.12', '3.11', '3.10')) {
    $probe = Native $uvExe @('python', 'find', $v)
    if ($probe.Code -eq 0 -and $probe.Out) { $found = ($probe.Out | Select-Object -First 1); break }
}
if (-not $found) { Write-Fail "No usable CPython 3.10-3.13 available via uv. Check internet and re-run." }
Write-Ok "Python interpreter: $found"

# ---------------------------------------------------------------------------
# 4. Locate the project folder
# ---------------------------------------------------------------------------
Write-Info 'Locating NOVA AI project...'
if (-not $RepoRoot -and $env:NOVA_AI_HOME) { $RepoRoot = $env:NOVA_AI_HOME }
if (-not $RepoRoot) {
    # This script lives at <repo>\deploy\windows\bootstrap-nova.ps1
    $guess = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    if (Test-Path (Join-Path $guess 'pyproject.toml')) { $RepoRoot = $guess }
}
if (-not $RepoRoot -or -not (Test-Path (Join-Path $RepoRoot 'pyproject.toml'))) {
    $gitExe = (Get-Command git -ErrorAction SilentlyContinue).Source
    if ($gitExe) {
        $RepoRoot = Join-Path $env:LOCALAPPDATA 'NOVA AI\src'
        if (-not (Test-Path (Join-Path $RepoRoot '.git'))) {
            $url = if ($env:NOVA_AI_REPO_URL) { $env:NOVA_AI_REPO_URL } else { 'https://github.com/Hamza35779/NOVA-AI.git' }
            Write-Info "  No local folder - cloning $url to $RepoRoot ..."
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $RepoRoot) | Out-Null
            $clone = Native $gitExe @('clone', '--depth', '1', $url, $RepoRoot)
            if ($clone.Code -ne 0) { Write-Fail 'git clone failed.' }
        }
    } else {
        Write-Fail @"
Could not find the NOVA AI project folder and git is not installed.

Easiest fix: copy the whole 'NOVA AI' folder onto this PC, cd into it, and
run this script again. Or pass -RepoRoot 'C:\path\to\NOVA AI'.
"@
    }
}
Write-Ok "Project root: $RepoRoot"

# ---------------------------------------------------------------------------
# 5. uv sync (install all runtime dependencies into .venv)
# ---------------------------------------------------------------------------
# Pre-heal a half-created / invalid .venv (interrupted sync, or the Windows
# file-lock-on-remove issue leaves a dir with no Scripts\python.exe /
# pyvenv.cfg). In that state `uv sync` aborts with "not a valid Python
# environment (no Python executable was found)". Detect and remove it so the
# rebuild is never blocked.
$venv = Join-Path $RepoRoot '.venv'
if ((Test-Path $venv) -and -not (Test-Path (Join-Path $venv 'Scripts\python.exe'))) {
    Write-Info "Found an invalid .venv (no Scripts\python.exe) at $venv - removing it..."
    try {
        Remove-Item -Recurse -Force $venv -ErrorAction Stop
    } catch {
        # A running nova/python may hold a lock (Windows); stop it, then retry.
        Write-Warn2 'Could not remove .venv (a process likely holds a lock); stopping it...'
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.ExecutablePath -like "$venv*" } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Milliseconds 500
        Remove-Item -Recurse -Force $venv -ErrorAction SilentlyContinue
    }
    if (Test-Path $venv) { Write-Fail "Stale .venv still present: $venv. Close any running 'nova', then re-run." }
    Write-Ok 'Invalid .venv removed; uv sync will recreate it.'
}

if ($SkipDeps) {
    Write-Warn2 'Skipping uv sync (-SkipDeps).'
} else {
    Write-Info "Running 'uv sync --extra $Extras' in $RepoRoot (a few minutes)..."
    Push-Location $RepoRoot
    try {
        $extraArgs = @()
        foreach ($e in ($Extras -split '[,\s]+' | Where-Object { $_ })) { $extraArgs += @('--extra', $e) }
        $sync = Native $uvExe (@('sync') + $extraArgs)
        $sync.Out | ForEach-Object { Write-Host $_ }
        if ($sync.Code -ne 0) { Write-Fail "uv sync failed (exit $($sync.Code)). Check output above." }
    } finally { Pop-Location }
    Write-Ok 'Dependencies installed'
}

# ---------------------------------------------------------------------------
# 6. Install the robust nova.cmd launcher
# ---------------------------------------------------------------------------
$binDir = Join-Path $env:USERPROFILE '.local\bin'
if (-not (Test-Path $binDir)) { New-Item -ItemType Directory -Force -Path $binDir | Out-Null }
$shimPath = Join-Path $binDir 'nova.cmd'

# %~dp0 = the folder of this .cmd (holds uv.exe). Fall back to bare uv, then
# to the install-time absolute path. --project pins NOVA to THIS repo's .venv.
# Launcher strategy (most robust first):
#   1. Run the project's own .venv\Scripts\nova.exe directly - instant, and
#      needs NO uv on PATH at runtime (uv is only required during install).
#   2. If the venv is missing, fall back to `uv run --project <repo>`, resolving
#      uv by %~dp0 (this folder holds uv.exe), then the install-time path,
#      then bare PATH. This is why the old bare-uv shim broke on an
#      un-refreshed PATH - we never depend on bare `uv` first.
$shim = @"
@echo off
setlocal
set "NOVA_HOME=$RepoRoot"
set "VENV=%NOVA_HOME%\.venv\Scripts\nova.exe"
if exist "%VENV%" (
  "%VENV%" %*
  exit /b %ERRORLEVEL%
)
set "UV=%~dp0uv.exe"
if not exist "%UV%" set "UV=$uvExe"
if not exist "%UV%" set "UV=uv"
"%UV%" run --project "%NOVA_HOME%" nova %*
"@
Set-Content -Path $shimPath -Value $shim -Encoding ASCII
Write-Ok "nova launcher installed at $shimPath"

# Ensure .local\bin is persisted to the User PATH (in case uv was there but
# PATH was never written by the astral installer).
$userPath = [System.Environment]::GetEnvironmentVariable('Path', 'User')
if (-not ($userPath -split ';' | ForEach-Object { [System.Environment]::ExpandEnvironmentVariables($_) } | Where-Object { $_ -ieq $binDir })) {
    $newPath = if ($userPath) { "$userPath;$binDir" } else { $binDir }
    [System.Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
    Write-Info "Added $binDir to your User PATH (new shells will pick it up)."
}

# ---------------------------------------------------------------------------
# 7. Optional: Ollama + starter model
# ---------------------------------------------------------------------------
$ollamaExe = (Get-Command ollama -ErrorAction SilentlyContinue).Source
if ($Full -and -not $ollamaExe) {
    Write-Info 'Installing Ollama (official installer, ~150 MB)...'
    $setup = Join-Path $env:TEMP 'OllamaSetup.exe'
    $prev = $ProgressPreference; $ProgressPreference = 'SilentlyContinue'
    try {
        Invoke-WebRequest -Uri 'https://ollama.com/download/OllamaSetup.exe' -OutFile $setup -UseBasicParsing
        Start-Process -FilePath $setup -ArgumentList '/S' -Wait
        Remove-Item $setup -ErrorAction SilentlyContinue
    } catch {
        Write-Warn2 "Ollama install failed: $($_.Exception.Message). You can add a model manually later."
    } finally { $ProgressPreference = $prev }
    Update-PathFromRegistry
    $ollamaExe = (Get-Command ollama -ErrorAction SilentlyContinue).Source
}

if ($ollamaExe) {
    Write-Info "Waiting for Ollama daemon..."
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        $probe = Native $ollamaExe @('list')
        if ($probe.Code -eq 0) { $ready = $true; break }
        if ($i -eq 4) { Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WindowStyle Hidden -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 1
    }
    if ($ready) {
        Write-Info "Pulling starter model '$Model'..."
        $pull = Native $ollamaExe @('pull', $Model)
        if ($pull.Code -eq 0) { Write-Ok "Model '$Model' ready" } else { Write-Warn2 "Pull failed; run 'ollama pull $Model' later." }
    } else { Write-Warn2 'Ollama daemon not ready; run the model pull later.' }
} elseif ($Full) {
    Write-Warn2 'Ollama not installed; chat needs a model. Re-run -Full or install Ollama manually.'
} else {
    Write-Info "Skipping Ollama/model (pass -Full to install). NOVA still works with cloud APIs via config."
}

# ---------------------------------------------------------------------------
# 8. Verify + finish
# ---------------------------------------------------------------------------
Write-Info 'Verifying installation...'
$env:Path = "$binDir;$env:Path"
$check = Native $shimPath @('--version')
$ver = ($check.Out | Out-String).Trim()
if ($check.Code -eq 0 -and $ver) { Write-Ok "nova -> $ver" } else { Write-Warn2 "nova launcher present but verification returned code $($check.Code). Open a new PowerShell and run 'nova --version'." }

Write-Host ''
Write-Host '  +--------------------------------------+' -ForegroundColor Green
Write-Host '  |   NOVA AI bootstrap complete          |' -ForegroundColor Green
Write-Host '  +--------------------------------------+' -ForegroundColor Green
Write-Host ''
Write-Host "  Project:   $RepoRoot"
Write-Host "  Launcher:  $shimPath"
Write-Host ''
Write-Host '  Open a NEW PowerShell and run:' -ForegroundColor Yellow
if ($ollamaExe) { Write-Host '     nova doctor' } else { Write-Host "     nova ask \"hello\" --model <a-pulled-model>" }
Write-Host '     nova ask "your question"'
Write-Host ''
Write-Host '  To deploy on another PC: copy this whole project folder there and'
Write-Host '  run this script again (add -Full to also set up Ollama + a model).'
Write-Host ''

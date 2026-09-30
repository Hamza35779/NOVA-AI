# NOVA AI on native Windows

Phase-1 of the native-Windows-support RFC (#298). Mirrors the Linux
(`deploy/systemd/`) and macOS (`deploy/launchd/`) deployments — but for
PowerShell, without WSL2 or Docker.

There are now **two Windows install paths**:

- **Desktop installer** — download `NOVA.AI_<version>_x64-setup.exe`
  from the [Releases page](https://github.com/Hamza35779/NOVA-AI/releases) and run it.
  This is the Tauri desktop app, built by `desktop.yml` on every stable tag.
- **Portable backend (no Python needed)** — download `nova-ai-windows-x64.zip`
  from the same release, extract, and run `nova-ai-windows-x64.exe` inside.
  This is the self-contained PyInstaller backend (`nova-ai-windows-x64.spec`).
- **Classic setup EXE** — `NOVA-AI-Setup-<version>.exe` wraps the same PyInstaller
  payload with the Inno Setup project in `nova-ai-setup.iss`; release.yml builds it
  on every stable tag since the 1.2.7-era CI reinstatement (it was last built by
  hand for v1.2.4 before that).
- **Source install (this document)** — the `install.ps1` one-liner below clones the
  repo and sets up a uv-managed Python environment. Use it when you want the CLI
  (`nova ...`), source access, or the auto-start scheduled task.

## One-liner install

In an elevated-or-regular PowerShell:

```powershell
irm https://raw.githubusercontent.com/Hamza35779/NOVA-AI/main/deploy/windows/install.ps1 | iex
```

What it does:

1. Refuses non-Windows hosts and Windows < 10 1809.
2. Checks Python 3.10 – 3.13 (3.14 has no numpy wheels yet — see #432).
3. Checks `git` on PATH.
4. Installs `uv` (https://astral.sh/uv) if absent.
5. Clones the NOVA AI repository to `%LOCALAPPDATA%\NOVA AI`
   (override with `$env:NOVA_AI_HOME`).
6. Runs `uv sync --extra desktop` so the FastAPI server and speech backend are
   importable.
7. Optionally prompts to register a scheduled task that auto-starts the
   server at logon.

Flags (when invoked directly rather than via `irm | iex`):

| Flag | Effect |
|------|--------|
| `-Service` | Register the scheduled task without prompting |
| `-SkipService` | Don't prompt; don't register |
| `-Force` | Re-run all steps even if already done |

`irm | iex` can't pass `param()` args into a piped script string, so
the same knobs are honored via env vars when the corresponding flag is
absent:

```powershell
$env:NOVA_AI_SKIP_SERVICE = '1'
irm https://raw.githubusercontent.com/Hamza35779/NOVA-AI/main/deploy/windows/install.ps1 | iex
```

The available env vars: `NOVA_AI_SKIP_SERVICE`, `NOVA_AI_SERVICE`,
`NOVA_AI_FORCE`. If you need richer control, save the script first
(`irm ... -OutFile install.ps1; .\install.ps1 -Force`).

## Deploy-anywhere bootstrap (`bootstrap-nova.ps1`)

`install.ps1` above still *requires* Python and `git` on PATH (it fetches
them via winget). For a **clean machine with nothing pre-installed**, use
`deploy/windows/bootstrap-nova.ps1`. It needs only PowerShell + internet:
`uv` downloads and manages its own CPython, so there is no dependency on a
system "Store alias" Python or on winget.

Copy the whole `NOVA AI` project folder onto the target PC, then from inside
it run:

```powershell
# Core CLI + API server (recommended starter):
powershell -ExecutionPolicy Bypass -File deploy\windows\bootstrap-nova.ps1 -Extras server

# Also installs + starts Ollama and pulls a starter model (~1.8 GB):
powershell -ExecutionPolicy Bypass -File deploy\windows\bootstrap-nova.ps1 -Full
```

What it does (all idempotent / re-runnable):

1. Installs `uv` (https://astral.sh/uv) if it is not on PATH.
2. Installs a **uv-managed CPython** (default 3.13) if one is absent.
3. Locates the project folder (this script's repo root, `-RepoRoot`, or
   clones if `git` happens to be available).
4. Runs `uv sync --extra <Extras>` to build `.venv` with all runtime deps.
5. Installs a robust `nova.cmd` launcher into `%USERPROFILE%\.local\bin`
   (already on PATH). The launcher runs `.venv\Scripts\nova.exe` **directly**
   — so `nova` needs no `uv`/PATH lookup at runtime — and only falls back to
   `uv run --project` if the venv is ever missing.
6. With `-Full`, installs/starts Ollama and pulls `-Model` (default `qwen2.5:0.5b`).
7. Verifies with `nova --version`.

Flags: `-Full`, `-SkipDeps`, `-Force`, `-Model <tag>`, `-Extras <list>`,
`-PythonVersion <v>`, `-RepoRoot <dir>`.

> After it finishes, open a **new** PowerShell so the PATH change takes
> effect, then run `nova doctor` and `nova ask "..."`.

## Fully OFFLINE deployment (air-gapped PCs)

Two scripts bundle NOVA AI so it installs on a target PC with **zero
internet**:

1. On an online PC, build a self-contained bundle:
   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\windows\make-offline-bundle.ps1 -Extras server
   # add -Zip for a single archive, or -Gguf C:\models\<file>.gguf for an offline model
   ```
   It produces `..\NOVA-AI-offline\` containing the `uv` binary, a
   uv-managed CPython, a pre-populated wheel **cache**, the source, and
   `install-offline.ps1`.
2. Copy that folder to the offline PC and run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File install-offline.ps1
   ```
   It drives `uv sync --frozen --offline` against the shipped cache, so
   nothing is downloaded. A complete bundle installs; an incomplete one
   fails loudly instead of phoning home.

**Offline inference:** local chat still needs a model engine with no network.
Either bundle a GGUF (`make-offline-bundle.ps1 -Gguf <file>` — its wheels must
resolve during the online build) or pre-install Ollama on the target and
`ollama pull <model>` once while it still has connectivity.

## Manual scheduled-task setup

If you skipped the prompt during install, you can register / inspect /
remove the task with `nova-service.ps1`:

```powershell
$srv = "$env:LOCALAPPDATA\NOVA AI\src\deploy\windows\nova-service.ps1"

# install (idempotent — replaces existing)
powershell -ExecutionPolicy Bypass -File $srv install

# status
powershell -ExecutionPolicy Bypass -File $srv status

# remove
powershell -ExecutionPolicy Bypass -File $srv uninstall
```

The task runs as the current user with `LogonType=Interactive` and
`RunLevel=Limited`. It restarts up to 3 times on failure (1-minute
gap), has no execution-time limit, and starts when available (catches
up if missed).

## Loopback vs LAN-exposed

By default the scheduled task binds `127.0.0.1` — reachable only from
this machine, no API key required. This matches launchd parity (see
`deploy/launchd/com.nova-ai.plist`).

To expose on your LAN:

```powershell
# 1. Generate an API key. The server REFUSES to bind 0.0.0.0 without one.
$env:NOVA_AI_API_KEY = (uv run nova auth create-key)

# 2. Re-register the task with -ListenHost 0.0.0.0.
powershell -ExecutionPolicy Bypass -File $srv install -ListenHost 0.0.0.0
```

`nova-service.ps1 install` refuses `-ListenHost 0.0.0.0` if
`$env:NOVA_AI_API_KEY` is unset — same guard as the systemd unit's
`EnvironmentFile=/etc/nova_ai/env`.

## Parity table

| Concern | systemd | launchd | Windows |
|---------|---------|---------|---------|
| Service definition | `deploy/systemd/nova_ai.service` | `deploy/launchd/com.nova-ai.plist` | `deploy/windows/nova-service.ps1` (cmdlet-driven) |
| Default bind | `0.0.0.0` (with API key) | `127.0.0.1` (no API key) | `127.0.0.1` (no API key) |
| Restart on failure | `Restart=on-failure RestartSec=5` | `KeepAlive=true` | `RestartCount=3 RestartInterval=PT1M` |
| Auto-start | `multi-user.target` | `RunAtLoad=true` | `AtLogOn` trigger |

## Updating

To pull the latest:

```powershell
cd "$env:LOCALAPPDATA\NOVA AI\src"
git pull --ff-only
uv sync --extra desktop
```

Or re-run the installer with `-Force`:

```powershell
irm https://raw.githubusercontent.com/Hamza35779/NOVA-AI/main/deploy/windows/install.ps1 | iex
# (then re-run with the file directly, passing -Force)
```

## Uninstall

```powershell
powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\NOVA AI\src\deploy\windows\nova-service.ps1" uninstall
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\NOVA AI"
```

Uninstalling does NOT remove `uv` (it's a separate tool — you may have
other Python projects using it).

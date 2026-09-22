# Deploy

Production deployment assets. Each target below includes its own prerequisites.

## Overview

| Target | Path | Notes |
|---|---|---|
| Docker | `docker/` | Requires `NOVA_AI_API_KEY`: `cp deploy/docker/.env.example .env` then `docker compose -f deploy/docker/docker-compose.yml --env-file .env up` |
| Windows | `windows/` | EXE installer assets; version single-sourced from `frontend/package.json` |
| systemd | `systemd/` | Service + timer/logrotate examples |
| launchd | `launchd/` | macOS agent plist |
| PostHog | `posthog/` | Telemetry sink (opt-in) |

## Docker

**Prerequisites:** Docker 24+ with Compose v2. A GPU is optional.

```bash
cd deploy/docker

# 1. Create the env file — the container binds 0.0.0.0, so the server refuses
#    to start without an API key.
cp .env.example .env
# Generate a key (anywhere the CLI is installed):
#   nova auth create-key
# …and paste it into NOVA_AI_API_KEY in .env

# 2. CPU-only stack (nova + ollama)
docker compose -f docker-compose.yml --env-file .env up -d

# 2b. With an NVIDIA GPU
docker compose -f docker-compose.yml -f docker-compose.gpu.nvidia.yml --env-file .env up -d

# 2c. With an AMD GPU (ROCm)
docker compose -f docker-compose.yml -f docker-compose.gpu.rocm.yml --env-file .env up -d
```

Compose builds `nova` from `deploy/docker/Dockerfile*` and starts an `ollama/ollama` sidecar. Clients authenticate with `Authorization: Bearer <key>`.

## Windows

- **Setup installer (no Python needed):** download `NOVA-AI-Setup-<version>.exe` from the [Releases page](https://github.com/Hamza35779/NOVA-AI/releases).
- **PowerShell deployment (source + uv):** see [`windows/README.md`](windows/README.md) for the one-liner, flags, scheduled-task management, and LAN-exposure guardrails.
- Building the installer assets locally requires the Inno Setup project in `windows/nova-ai-setup.iss` and the PyInstaller spec at the repo root (`nova-ai-windows-x64.spec`).

## systemd (Linux server)

**Prerequisites:** a Linux host with systemd, NOVA AI installed (e.g. under `/opt/nova-ai` or `$HOME`), and — if binding to a non-loopback interface — a generated API key in the unit's `EnvironmentFile`.

Copy `systemd/nova_ai.service` (plus the timer/logrotate examples as needed) to `/etc/systemd/`, adjust `WorkingDirectory`/`ExecStart`/`User` to your install path, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now nova_ai.service
```

Default bind follows the parity table in [`windows/README.md`](windows/README.md): `0.0.0.0` **with** an API key. Set it in `/etc/nova_ai/env` (the unit's `EnvironmentFile`).

## launchd (macOS)

**Prerequisites:** macOS 12+, NOVA AI installed (source install or pip), and `launchctl`.

Copy `launchd/com.nova-ai.plist` to `~/Library/LaunchAgents/`, fix the paths inside to your install location, then:

```bash
launchctl load ~/Library/LaunchAgents/com.nova-ai.plist
```

Binds `127.0.0.1` by default — no API key needed for local-only use.

## PostHog (opt-in telemetry)

`posthog/posthog-hetzner-prep.sh` prepares a self-hosted PostHog instance on Hetzner for the opt-in telemetry sink. Telemetry is **opt-in**; if you enable it, only the aggregated usage events described in the docs leave the machine — never conversation content.

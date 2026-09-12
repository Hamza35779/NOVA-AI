# Deploy

| Target | Path | Notes |
|---|---|---|
| Docker | `docker/` | Requires `NOVA_AI_API_KEY`: `cp deploy/docker/.env.example .env` then `docker compose -f deploy/docker/docker-compose.yml --env-file .env up` |
| Windows | `windows/` | EXE installer assets; version single-sourced from `frontend/package.json` |
| systemd | `systemd/` | Service + timer/logrotate examples |
| launchd | `launchd/` | macOS agent plist |
| PostHog | `posthog/` | Telemetry sink (opt-in) |

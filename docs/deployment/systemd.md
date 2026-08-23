# systemd Service (Linux)

NOVA AI includes a systemd unit file for running the API server as a managed background service on Linux. This provides automatic startup on boot, crash recovery, and integration with standard Linux service management tools.

## Prerequisites

Before installing the service, ensure that:

1. NOVA AI is installed in a virtual environment at `/opt/nova_ai/.venv` (or adjust paths accordingly).
2. A dedicated `nova_ai` system user exists (recommended for security).
3. An inference engine (such as Ollama) is running and accessible.

Create the user and installation directory:

```bash
sudo useradd --system --create-home --home-dir /opt/nova_ai nova_ai
sudo -u nova_ai python3 -m venv /opt/nova_ai/.venv
sudo -u nova_ai git clone https://github.com/Hamza35779/NOVA-AI.git /opt/nova_ai/NOVA AI
cd /opt/nova_ai/NOVA AI && sudo -u nova_ai uv sync --extra server
```

## Installing the Service

The unit binds `0.0.0.0`, so an **API key is required** — and the unit
declares `EnvironmentFile=/etc/nova_ai/env` (no `-` prefix), so it will
**fail to start** until that file exists with a key. Create it first:

```bash
sudo mkdir -p /etc/nova_ai
echo "NOVA_AI_API_KEY=$(nova auth generate-key)" | sudo tee /etc/nova_ai/env
sudo chmod 600 /etc/nova_ai/env
```

Then copy the unit file, reload the daemon, and enable the service:

```bash
sudo cp deploy/systemd/nova_ai.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable nova_ai
sudo systemctl start nova_ai
```

Clients must send `Authorization: Bearer <key>` on `/v1/*` and `/api/*`
requests. (If you instead bind to `127.0.0.1`, the key is optional and you
can drop the `EnvironmentFile` line.)

Verify it is running:

```bash
sudo systemctl status nova_ai
```

## Service File Reference

The provided unit file at `deploy/systemd/nova_ai.service`:

```ini
[Unit]
Description=NOVA AI API Server
After=network.target

[Service]
Type=simple
User=nova_ai
WorkingDirectory=/opt/nova_ai
ExecStart=/opt/nova_ai/.venv/bin/nova serve --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
Environment=HOME=/opt/nova_ai

[Install]
WantedBy=multi-user.target
```

### `[Unit]` Section

| Directive     | Value              | Description                                                                 |
|---------------|--------------------|-----------------------------------------------------------------------------|
| `Description` | `NOVA AI API Server` | Human-readable name shown in `systemctl status` and logs.              |
| `After`       | `network.target`   | Delays startup until the network stack is available, since the server binds to a network socket and may need to reach a remote engine. |

### `[Service]` Section

| Directive          | Value                                                              | Description                                                                                     |
|--------------------|--------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| `Type`             | `simple`                                                           | The process started by `ExecStart` is the main service process. systemd considers the service started immediately. |
| `User`             | `nova_ai`                                                       | Runs the server as the `nova_ai` user rather than root, limiting the blast radius of any security issue. |
| `WorkingDirectory` | `/opt/nova_ai`                                                  | Sets the working directory for the process. This is where NOVA AI looks for local files and writes data. |
| `ExecStart`        | `/opt/nova_ai/.venv/bin/nova serve --host 0.0.0.0 --port 8000` | The command to start the server. Uses the full path to the `nova` binary inside the virtual environment. |
| `Restart`          | `on-failure`                                                       | Automatically restarts the service if it exits with a non-zero exit code. Does not restart on clean shutdown (`systemctl stop`). |
| `RestartSec`       | `5`                                                                | Waits 5 seconds before attempting a restart, preventing rapid restart loops if the service crashes immediately on startup. |
| `Environment`      | `HOME=/opt/nova_ai`                                             | Sets the `HOME` environment variable so NOVA AI finds its configuration at `~/.nova_ai/config.toml` (resolving to `/opt/nova_ai/.nova_ai/config.toml`). |

### `[Install]` Section

| Directive    | Value               | Description                                                                                 |
|--------------|---------------------|---------------------------------------------------------------------------------------------|
| `WantedBy`   | `multi-user.target` | The service starts when the system reaches multi-user mode (standard boot target for servers). `systemctl enable` creates a symlink under this target. |

## Configuration Options

### Changing the Bind Address and Port

Edit the `ExecStart` line to change the host or port:

```ini
ExecStart=/opt/nova_ai/.venv/bin/nova serve --host 127.0.0.1 --port 9000
```

!!! tip
    Binding to `127.0.0.1` restricts access to localhost only. Use this when running behind a reverse proxy like Nginx or Caddy.

### Setting the Engine and Model

Pass additional flags to `nova serve`:

```ini
ExecStart=/opt/nova_ai/.venv/bin/nova serve --host 0.0.0.0 --port 8000 --engine ollama --model qwen3:8b
```

### Adding Environment Variables

Add multiple `Environment` directives or use `EnvironmentFile` for complex configurations:

```ini
[Service]
Environment=HOME=/opt/nova_ai
Environment=NOVA_AI_ENGINE_DEFAULT=vllm
Environment=NOVA_AI_OLLAMA_HOST=http://localhost:11434
```

Or load from a file:

```ini
[Service]
EnvironmentFile=/opt/nova_ai/.env
```

### Changing the User

If you prefer a different service user, update both the `User` directive and the paths:

```ini
[Service]
User=myuser
WorkingDirectory=/home/myuser/nova_ai
ExecStart=/home/myuser/nova_ai/.venv/bin/nova serve --host 0.0.0.0 --port 8000
Environment=HOME=/home/myuser/nova_ai
```

### Using a Configuration File

Ensure the configuration file exists at the path where `HOME` points:

```bash
sudo -u nova_ai mkdir -p /opt/nova_ai/.nova_ai
sudo -u nova_ai cp config.toml /opt/nova_ai/.nova_ai/config.toml
```

The server reads `~/.nova_ai/config.toml` on startup, where `~` resolves from the `HOME` environment variable.

## Viewing Logs

NOVA AI logs are captured by journald. View them with `journalctl`:

```bash
# View all logs for the service
sudo journalctl -u nova_ai

# Follow logs in real time
sudo journalctl -u nova_ai -f

# View logs since the last boot
sudo journalctl -u nova_ai -b

# View logs from the last hour
sudo journalctl -u nova_ai --since "1 hour ago"

# View only error-level messages
sudo journalctl -u nova_ai -p err
```

## Managing the Service

### Start, Stop, and Restart

```bash
# Start the service
sudo systemctl start nova_ai

# Stop the service
sudo systemctl stop nova_ai

# Restart the service (stop + start)
sudo systemctl restart nova_ai

# Reload configuration without full restart (sends SIGHUP)
sudo systemctl reload-or-restart nova_ai
```

### Check Status

```bash
sudo systemctl status nova_ai
```

Example output:

```
● nova_ai.service - NOVA AI API Server
     Loaded: loaded (/etc/systemd/system/nova_ai.service; enabled; preset: enabled)
     Active: active (running) since Fri 2026-02-21 10:00:00 UTC; 2h ago
   Main PID: 12345 (nova)
      Tasks: 4 (limit: 4915)
     Memory: 256.0M
        CPU: 1min 23s
     CGroup: /system.slice/nova_ai.service
             └─12345 /opt/nova_ai/.venv/bin/python /opt/nova_ai/.venv/bin/nova serve --host 0.0.0.0 --port 8000
```

### Enable and Disable on Boot

```bash
# Enable automatic start on boot
sudo systemctl enable nova_ai

# Disable automatic start on boot
sudo systemctl disable nova_ai
```

### Apply Changes After Editing the Unit File

After modifying `/etc/systemd/system/nova_ai.service`, reload the systemd daemon and restart the service:

```bash
sudo systemctl daemon-reload
sudo systemctl restart nova_ai
```

## Running Alongside Ollama

If Ollama is also managed via systemd, you can add an ordering dependency so the NOVA AI service waits for Ollama to start:

```ini
[Unit]
Description=NOVA AI API Server
After=network.target ollama.service
Requires=ollama.service
```

| Directive  | Description                                                              |
|------------|--------------------------------------------------------------------------|
| `After`    | Ensures NOVA AI starts after Ollama.                                  |
| `Requires` | If Ollama fails to start, NOVA AI will not start either.              |

!!! note
    Use `Wants` instead of `Requires` if you want NOVA AI to start even when Ollama is unavailable (for example, if you plan to start Ollama manually later).

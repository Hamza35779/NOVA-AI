# CLI Reference

NOVA AI provides a command-line interface through the `nova` command. Built on [Click](https://click.palletsprojects.com/), it offers subcommands for querying models, managing memory, running benchmarks, and serving an OpenAI-compatible API.

## Global Options

```bash
nova --version   # Print the NOVA AI version
nova --help      # Show top-level help with all subcommands
```

## `nova init`

Detect local hardware (CPU, GPU, RAM) and generate a configuration file at `~/.nova_ai/config.toml`.

```bash
nova init           # Interactive — refuses to overwrite existing config
nova init --force   # Overwrite existing config without prompting
```

| Option    | Description                                   |
|-----------|-----------------------------------------------|
| `--force` | Overwrite existing configuration without prompting |

The `init` command auto-detects:

- **Platform** (Linux, macOS, Windows)
- **CPU** brand and core count
- **RAM** in GB
- **GPU** vendor, model, VRAM, and count (via `nvidia-smi`, `rocm-smi`, or `system_profiler`)

Based on the detected hardware, it recommends an appropriate inference engine and writes a pre-configured TOML file.

**Example output:**

```
Detecting hardware...
  Platform : linux
  CPU      : AMD Ryzen 9 7950X (32 cores)
  RAM      : 64 GB
  GPU      : NVIDIA RTX 4090 (24.0 GB VRAM, x1)

Config written successfully.
```

---

## `nova ask`

Send a query to the inference engine (directly or through an agent) and print the response.

```bash
nova ask "What is the capital of France?"
```

### Options

| Option                        | Type    | Default    | Description                                           |
|-------------------------------|---------|------------|-------------------------------------------------------|
| `-m`, `--model MODEL`         | string  | auto       | Model to use for inference                             |
| `-e`, `--engine ENGINE`       | string  | auto       | Engine backend (ollama, vllm, llamacpp, etc.)          |
| `-t`, `--temperature TEMP`    | float   | `0.7`      | Sampling temperature                                   |
| `--max-tokens N`              | int     | `1024`     | Maximum tokens to generate                             |
| `--json`                      | flag    | off        | Output raw JSON result instead of plain text           |
| `--no-stream`                 | flag    | off        | Disable streaming (synchronous mode)                   |
| `--no-context`                | flag    | off        | Disable memory context injection                       |
| `-a`, `--agent AGENT`         | string  | none       | Agent to use (`simple`, `orchestrator`)                |
| `--tools TOOLS`               | string  | none       | Comma-separated tool names to enable                   |
| `-i`, `--image PATH`          | path    | none       | Image file for a vision model (e.g. `gemma3:4b`); repeatable |
| `-S`, `--screen`              | flag    | off        | Capture the current screen and send it to the vision model  |

### Direct Mode vs Agent Mode

**Direct mode** (default) sends the query straight to the inference engine:

```bash
nova ask "Explain quantum computing"
```

**Agent mode** routes the query through an agent that can use tools and manage multi-turn interactions:

```bash
nova ask --agent orchestrator "What is 2+2?"
nova ask --agent orchestrator --tools calculator,think "Calculate sqrt(144) + 3^2"
nova ask --agent simple "Hello"
```

### Usage Examples

```bash
# Basic query
nova ask "What is machine learning?"

# Specify a model
nova ask -m qwen3:8b "Summarize this concept"

# Use the orchestrator agent with tools
nova ask --agent orchestrator --tools calculator "What is 15% of 340?"

# Get JSON output
nova ask --json "Hello"

# Disable memory context injection
nova ask --no-context "Tell me about Python"

# Set maximum token generation
nova ask --max-tokens 2048 "Write a detailed essay about AI"
```

### Vision Input

Vision-capable models (such as `gemma3:4b`) can read images alongside your
text prompt. Attach one or more image files with `-i`/`--image`, or capture
the current screen with `-S`/`--screen`:

```bash
# Ask about a local image
nova ask -i screenshot.png "What is shown in this image?"

# Send multiple images (the flag is repeatable)
nova ask -i chart-a.png -i chart-b.png "Compare these two charts"

# Capture the current screen and ask about it
nova ask --screen "Summarize what's on my screen"
```

Vision runs in **direct mode** only. If you also pass `--agent`, the image is
ignored and a note is printed — re-run with `--agent ""` to force direct mode.

The Ollama context window can be tuned for large images or long prompts with
the `NOVA_NUM_CTX` environment variable (default `16384`):

```bash
NOVA_NUM_CTX=8192 nova ask --screen "What's on my screen?"
```

!!! note "Keep vision on-device"
    Images are sensitive. NOVA AI prints a privacy warning before sending
    an image to a non-local engine, so a screenshot never leaves your machine
    unnoticed. Use a local engine (e.g. `ollama` with `gemma3:4b`) to keep
    vision fully local.

### JSON Output Format

When using `--json` in **direct mode**, the output includes:

```json
{
  "content": "The response text...",
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 85,
    "total_tokens": 97
  }
}
```

When using `--json` in **agent mode**, the output includes:

```json
{
  "content": "The response text...",
  "turns": 3,
  "tool_results": [
    {
      "tool_name": "calculator",
      "content": "51.0",
      "success": true
    }
  ]
}
```

---

## `nova model`

Manage and inspect language models available on running engines.

### `nova model list`

List all models available from running inference engines, displayed as a Rich table with model parameters, context length, and VRAM requirements.

```bash
nova model list
```

**Example output:**

```
           Available Models
┌─────────┬────────────────┬────────┬─────────┬──────┐
│ Engine  │ Model          │ Params │ Context │ VRAM │
├─────────┼────────────────┼────────┼─────────┼──────┤
│ ollama  │ qwen3:8b       │ 8B     │ 32,768  │ 6GB  │
│ ollama  │ llama3.2:3b    │ 3B     │ 8,192   │ 3GB  │
└─────────┴────────────────┴────────┴─────────┴──────┘
```

### `nova model info <model>`

Show detailed information about a specific model.

```bash
nova model info qwen3:8b
```

**Example output:**

```
┌─ Qwen 3 8B ──────────────────────────────┐
│ Model ID:     qwen3:8b                    │
│ Name:         Qwen 3 8B                   │
│ Parameters:   8B                          │
│ Context:      32,768                      │
│ Quantization: none                        │
│ Min VRAM:     6GB                         │
│ Engines:      ollama, vllm                │
│ Provider:     Alibaba                     │
│ API Key:      not required                │
└───────────────────────────────────────────┘
```

### `nova model pull <model>`

Download a model via Ollama. Shows a progress bar during download.

```bash
nova model pull qwen3:8b
```

!!! note
    The `pull` command requires a running Ollama instance. It connects to the Ollama API at the host configured in your `config.toml`.

---

## `nova pearl`

Access Pearl's native node, wallet, and RPC tools from the NOVA AI CLI.

```bash
nova pearl doctor
nova pearl node -- <pearld args>
nova pearl wallet -- <oyster args>
nova pearl ctl -- <prlctl args>
nova pearl address
```

All Pearl wrapper commands use the `nova pearl <command>` shape. The
pass-through commands map to Pearl's native binaries:

| NOVA AI command | Pearl binary | Use |
|--------------------|--------------|-----|
| `nova pearl doctor` | n/a | Check whether `pearld`, `oyster`, and `prlctl` are discoverable |
| `nova pearl node` | `pearld` | Run the Pearl full node |
| `nova pearl wallet` | `oyster` | Run the Oyster wallet daemon |
| `nova pearl ctl` | `prlctl` | Query Pearl node or wallet RPC |
| `nova pearl address` | `prlctl --wallet getnewaddress` | Generate a wallet address from Oyster |

Use `PEARL_HOME=/path/to/pearl` or `--pearl-home /path/to/pearl` if Pearl's
`bin/` directory is not on `PATH`. See the [Pearl CLI guide](pearl.md) for
examples.

---

## `nova memory`

Manage the document memory store for retrieval-augmented generation.

### `nova memory index <path>`

Index documents from a file or directory into the memory store.

```bash
nova memory index ./docs/
nova memory index ./notes.md
nova memory index ./data/ --chunk-size 256 --chunk-overlap 32
nova memory index ./docs/ --backend sqlite
```

| Option                      | Type   | Default | Description                          |
|-----------------------------|--------|---------|--------------------------------------|
| `--backend`, `-b`           | string | config  | Override the default memory backend  |
| `--chunk-size`              | int    | `512`   | Chunk size in tokens                 |
| `--chunk-overlap`           | int    | `64`    | Overlap between chunks in tokens     |

The ingestion pipeline supports text, markdown, code files, and PDF (with `pdfplumber` installed). Binary files and hidden directories are automatically skipped.

### `nova memory search <query>`

Search the memory store for relevant document chunks.

```bash
nova memory search "machine learning basics"
nova memory search -k 10 "neural networks"
nova memory search --backend faiss "embeddings"
```

| Option             | Type   | Default | Description                          |
|--------------------|--------|---------|--------------------------------------|
| `--top-k`, `-k`    | int    | `5`     | Number of results to return          |
| `--backend`, `-b`  | string | config  | Override the default memory backend  |

Results are displayed in a table with rank, score, source file, and a content preview.

### `nova memory stats`

Show memory store statistics including document count and database size.

```bash
nova memory stats
nova memory stats --backend sqlite
```

| Option             | Type   | Default | Description                          |
|--------------------|--------|---------|--------------------------------------|
| `--backend`, `-b`  | string | config  | Override the default memory backend  |

---

## `nova telemetry`

Query and manage inference telemetry data stored in SQLite.

### `nova telemetry stats`

Show aggregated telemetry statistics including total calls, tokens, cost, and latency, broken down by model and engine.

```bash
nova telemetry stats
nova telemetry stats -n 5    # Show top 5 models
```

| Option          | Type | Default | Description                   |
|-----------------|------|---------|-------------------------------|
| `-n`, `--top`   | int  | `10`    | Number of top models to show  |

### `nova telemetry export`

Export raw telemetry records in JSON or CSV format.

```bash
nova telemetry export                          # JSON to stdout
nova telemetry export --format csv             # CSV to stdout
nova telemetry export --format json -o data.json  # JSON to file
nova telemetry export -f csv -o metrics.csv    # CSV to file
```

| Option                | Type   | Default  | Description                     |
|-----------------------|--------|----------|---------------------------------|
| `-f`, `--format`      | choice | `json`   | Output format: `json` or `csv`  |
| `-o`, `--output`      | path   | stdout   | Output file path                |

### `nova telemetry clear`

Delete all telemetry records from the database.

```bash
nova telemetry clear         # Interactive confirmation
nova telemetry clear --yes   # Skip confirmation
```

| Option         | Type | Default | Description                   |
|----------------|------|---------|-------------------------------|
| `-y`, `--yes`  | flag | off     | Skip confirmation prompt      |

!!! warning
    This permanently deletes all stored telemetry data. Use `--yes` to skip the confirmation prompt in automated scripts.

---

## `nova bench`

Run inference benchmarks against a running engine.

### `nova bench run`

Execute benchmarks and report results.

```bash
nova bench run                               # Run all benchmarks, 10 samples
nova bench run -n 20                         # 20 samples per benchmark
nova bench run -b latency                    # Only the latency benchmark
nova bench run -b throughput -n 50 --json    # Throughput, 50 samples, JSON output
nova bench run -o results.jsonl              # Write JSONL results to file
nova bench run -m qwen3:8b -e ollama         # Specific model and engine
```

| Option                     | Type   | Default | Description                              |
|----------------------------|--------|---------|------------------------------------------|
| `-m`, `--model MODEL`      | string | auto    | Model to benchmark                       |
| `-e`, `--engine ENGINE`    | string | auto    | Engine backend                           |
| `-n`, `--samples N`        | int    | `10`    | Number of samples per benchmark          |
| `-b`, `--benchmark NAME`   | string | all     | Specific benchmark to run                |
| `-o`, `--output PATH`      | path   | none    | Write JSONL results to file              |
| `--json`                   | flag   | off     | Output JSON summary to stdout            |

Available benchmarks:

- **latency** -- Measures per-call inference latency (mean, p50, p95, min, max)
- **throughput** -- Measures tokens-per-second throughput

---

## `nova channel`

Manage messaging channels for multi-platform communication. Channels connect directly to platform APIs (Telegram, Discord, Slack, etc.) -- no gateway required.

### `nova channel list`

List registered channel backends and their connection status.

```bash
nova channel list
```

### `nova channel send`

Send a message to a specific channel.

```bash
nova channel send slack "Hello from Nova!"
nova channel send discord "Build complete"
```

| Argument    | Type   | Description                          |
|-------------|--------|--------------------------------------|
| `TARGET`    | string | Channel name to send to              |
| `MESSAGE`   | string | Message content                      |

### `nova channel status`

Show connection status for configured channels.

```bash
nova channel status
```

!!! note "Channel Dependencies"
    Each channel requires its platform-specific credentials (bot tokens, API keys) configured in the `[channel.<platform>]` section of your config. See [Configuration](../getting-started/configuration.md) for details.

---

## `nova serve`

Start an OpenAI-compatible API server.

```bash
nova serve                                 # Default host/port from config
nova serve --port 8000                     # Custom port
nova serve --host 0.0.0.0 --port 9000      # Bind to all interfaces
nova serve --model qwen3:8b                # Specify default model
nova serve --agent orchestrator            # Route requests through an agent
```

| Option                   | Type   | Default | Description                              |
|--------------------------|--------|---------|------------------------------------------|
| `--host HOST`            | string | config  | Bind address                             |
| `--port PORT`            | int    | config  | Port number                              |
| `-e`, `--engine ENGINE`  | string | auto    | Engine backend                           |
| `-m`, `--model MODEL`    | string | config  | Default model for inference              |
| `-a`, `--agent AGENT`    | string | none    | Agent for non-streaming requests         |

!!! note "Server Dependencies"
    The `serve` command requires the server extra:

    ```bash
    uv sync --extra server
    ```

    This installs FastAPI, uvicorn, and related dependencies.

### API Endpoints

The server exposes the following OpenAI-compatible endpoints:

| Method | Path                     | Description                    |
|--------|--------------------------|--------------------------------|
| POST   | `/v1/chat/completions`   | Chat completions (streaming & non-streaming) |
| GET    | `/v1/models`             | List available models          |
| GET    | `/health`                | Health check                   |
| GET    | `/v1/channels`           | List available messaging channels    |
| POST   | `/v1/channels/send`      | Send a message to a channel          |
| GET    | `/v1/channels/status`    | Channel bridge connection status     |

**Example with curl:**

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3:8b",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

When an agent is configured (e.g., `--agent orchestrator`), non-streaming requests are routed through the agent with access to all registered tools. For tool-capable agents (`orchestrator`, `react`, `openhands`), all registered tools are automatically loaded and made available.

---

## LLM-guided spec search (no CLI yet)

LLM-guided spec search (the frontier-driven harness-learning subsystem)
is exposed as a Python library only — there is currently no top-level
`nova` subcommand for it. Construct a `SpecSearchOrchestrator`
directly from `nova_ai.learning.spec_search.orchestrator` and call
`.run(trigger)` with a trigger from
`nova_ai.learning.spec_search.triggers`. See
[`docs/user-guide/llm-guided-spec-search.md`](llm-guided-spec-search.md)
for the architecture and the building blocks
(`splits.py`, external corpora, `external_adapter`).

---

## `nova train`

Self-training: fine-tune a local model from your own usage traces. See [Self-Training](../learning/self-training.md) for the full guide and safety model.

### `nova train run`

Mine traces, train a LoRA adapter, and deploy per `[learning.training]` config.

```bash
nova train run                    # Start in the background
nova train run --foreground       # Block and stream progress
nova train run --base-model Qwen/Qwen3-1.7B   # Override the base model
```

### `nova train status`

Show the latest (or running) training run: status, pairs used, loss, adapter path, deploy results.

### `nova train list`

List recent training runs with trigger, status, and benchmark delta.

### `nova train deploy <run-id>`

Promote and deploy a `pending_review` adapter (the manual review step).

```bash
nova train deploy train_20260901_030000_a1b2c3 --target adapter
nova train deploy train_20260901_030000_a1b2c3 --target ollama --target adapter
```

### `nova train export-traces`

Export mined SFT pairs to JSONL for external training runs.

```bash
nova train export-traces                      # pairs.jsonl in cwd
nova train export-traces -o data/pairs.jsonl --min-quality 0.8
```

---

## `nova prove`

The Model Proving Ground: A/B-test a candidate model against your incumbent on benchmarks synthesized from *your own* traces, per query class. See [Model Proving Ground](../learning/proving-ground.md) for the full guide and safety model.

### `nova prove run <candidate>`

Run the head-to-head gauntlet (background by default).

```bash
nova prove run qwen3:8b --incumbent qwen2.5:7b --foreground   # stream the scorecard
nova prove run qwen3:8b --adopt                               # adopt winners immediately
```

### `nova prove status` / `nova prove list`

Latest run with its per-class scorecard; run history.

### `nova prove roster`

Show the current per-class adoption map (`policy_map.json`).

### `nova prove adopt <run-id> [--class code,math]`

Adopt a completed run's winners into the routing map (manual review step; margin-gated).

### `nova prove revert <class>`

Remove a query class from the adoption map (rollback).

### `nova prove watch [--prove]`

Check for newly pulled models; with `--prove`, run the gauntlet for each.

---

## `nova oracle`

The Fleet Oracle: opt-in anonymized performance reports pooled via a git dataset, queried locally. See [Fleet Oracle](../learning/fleet-oracle.md) for the privacy model (a fixed field list — nothing else ever leaves the machine).

### `nova oracle export [-o PATH]`

Build the anonymized report from local telemetry and preview it (or write it to a file). This is the exact payload sharing would publish.

### `nova oracle push`

Push the report to `learning.fleet.dataset_repo`. Refuses unless `learning.fleet.share_reports = true` (default off).

### `nova oracle ask "QUESTION"`

Answer from the pooled dataset locally, e.g. `nova oracle ask "best 8B model for code on a 4090?"` — keyword-bucketed, no LLM, table shows the machines behind the answer.

### `nova oracle status`

Fleet config, sharing state, and the local dataset copy size.

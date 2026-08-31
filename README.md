<div align="center">
<img width="400" height="200" alt="NovaAI_Horizontal_Logo" src="https://github.com/user-attachments/assets/3cd5dc54-5e23-4ddc-a508-11b8a85b063f" />



  <p><i>Personal AI, On Personal Devices.</i></p>

  <p>
    <img src="https://img.shields.io/badge/python-%3E%3D3.10-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="License">
  </p>
</div>

---

<div align="center">
  <img alt="NOVA AI demo reel" src="assets/nova_ai_demo_reel.webp" width="75%">
</div>

---

> **[Complete Setup & User Guide](SETUP_AND_USAGE_GUIDE.md)**
>
> **[Documentation](https://hamza35779.github.io/NOVA-AI/)**
>
> **[Roadmap](https://hamza35779.github.io/NOVA-AI/development/roadmap/)**

## Why NOVA AI?

Personal AI agents are exploding in popularity, but nearly all of them still route intelligence through cloud APIs. Your "personal" AI continues to depend on someone else's server. Local language models already handle most single-turn chat and reasoning queries, and their capability per watt keeps improving year over year. What has been missing is the software stack to make local-first personal AI practical.

NOVA AI is that stack. It is a framework for local-first personal AI, built around three core ideas: shared primitives for building on-device agents; evaluations that treat energy, FLOPs, latency, and dollar cost as first-class constraints alongside accuracy; and a learning loop that improves models using local trace data. The goal is simple: make it possible to build personal AI agents that run locally by default, calling the cloud only when truly necessary. NOVA AI aims to be both a research platform and a production foundation for local AI, in the spirit of PyTorch.

## Installation & Quick Start

Pick your platform and start in seconds:

| Platform | Quick Launch | Installation One-liner |
|---|---|---|
| **Windows (1-Click)** | Double-click `start.bat` | `irm https://hamza35779.github.io/NOVA-AI/install.ps1 \| iex` or run `install.bat` |
| **Linux · macOS** | `./start.sh` | `curl -fsSL https://hamza35779.github.io/NOVA-AI/install.sh \| bash` |
| **Docker** | `docker compose -f deploy/docker/docker-compose.yml up` | Containerized setup with local Ollama engine |
| **Desktop GUI** | Download `.exe` / `.dmg` / `.AppImage` | [Latest Release](https://github.com/Hamza35779/NOVA-AI/releases) |

### Start Working with NOVA AI

```bash
# Interactive Chat
nova chat

# Hands-free Voice Conversation
nova voice --push-to-talk

# Smart Model Router (Auto-selects optimal model)
nova router status
nova router test "Analyze quantum algorithms"

# Active Memory Wiki
nova memory-wiki show profile
nova memory-wiki search "preferences"

# Interactive Canvas (Open HTML/SVG/Chart visualizations)
nova canvas list

# Presets & System Diagnostics
nova init --preset morning-digest-minimal
nova doctor
```

> Prefix `nova ...` with `uv run`, or `source .venv/bin/activate` first.

| Preset | What it does |
|---|---|
| `morning-digest-mac` / `morning-digest-linux` / `morning-digest-minimal` | Spoken daily briefing from email, calendar, health, news |
| `deep-research` | Multi-hop research across indexed docs with citations |
| `code-assistant` | Agent with code execution, file I/O, and shell access |
| `scheduled-monitor` | Stateful agent on a schedule with memory |
| `chat-simple` | Lightweight conversation, no tools |

Example:

```bash
nova init --preset morning-digest-mac
nova connect gdrive          # one OAuth covers Gmail / Calendar / Tasks
nova digest --fresh          # generate and play your first briefing
```

Per-preset deep dives: [morning digest](https://hamza35779.github.io/NOVA-AI/user-guide/morning-digest/) · [deep research](https://hamza35779.github.io/NOVA-AI/user-guide/deep-research/) · [code assistant](https://hamza35779.github.io/NOVA-AI/user-guide/code-assistant/) · [scheduled monitor](https://hamza35779.github.io/NOVA-AI/user-guide/scheduled-monitor/) · [chat simple](https://hamza35779.github.io/NOVA-AI/user-guide/chat-simple/) · or the full [quickstart guide](https://hamza35779.github.io/NOVA-AI/getting-started/quickstart/).

### Skills

Skills teach agents how to better use tools and improve their reasoning. Every skill is a tool — agents discover them from a catalog and invoke them on demand.

```bash
# Install skills from public sources
nova skill install hermes:arxiv
nova skill sync hermes --category research

# Use skills with any agent
nova ask "Use the code-explainer skill to explain this Python code: for i in range(5): print(i*2)"

# Optimize skills from your trace history
nova optimize skills --policy dspy

# Benchmark the impact
nova bench skills --max-samples 5 --seeds 42
```

Import from [Hermes Agent](https://github.com/NousResearch/hermes-agent) (~150 skills), [OpenClaw](https://github.com/openclaw/skills) (~13,700 community skills), or any GitHub repo. Skills follow the [agentskills.io](https://agentskills.io/specification) open standard.

See the [Skills User Guide](https://hamza35779.github.io/NOVA-AI/user-guide/skills/) and [Skills Tutorial](https://hamza35779.github.io/NOVA-AI/tutorials/skills-workflow/) for details.

### Built-in Agents

NOVA AI ships with eight built-in agents across three execution modes (on-demand, scheduled, continuous):

| Agent | Type | What it does |
|-------|------|-------------|
| `morning_digest` | Scheduled | Daily briefing from email, calendar, health, news — with TTS audio |
| `deep_research` | On-demand | Multi-hop research with citations across web and local docs |
| `monitor_operative` | Continuous | Long-horizon monitoring with memory, compression, and retrieval |
| `orchestrator` | On-demand | Multi-turn reasoning with automatic tool selection |
| `native_react` | On-demand | ReAct (Thought-Action-Observation) loop agent |
| `operative` | Continuous | Persistent autonomous agent with state management |
| `native_openhands` | On-demand | CodeAct — generates and executes Python code |
| `simple` | On-demand | Single-turn chat, no tools |

---

## Complete CLI Commands Reference

NOVA AI features a comprehensive CLI suite (`nova` or `python -m nova_ai.cli` or standalone `nova-ai.exe`):

### 1. 💬 Chat, Voice & Perception
| Command | Description | Example |
|---|---|---|
| `nova chat` | Launch an interactive multi-turn REPL chat session | `nova chat --model llama3` |
| `nova ask "<query>"` | Send a single query directly to the model/agent | `nova ask "Summarize this repo"` |
| `nova voice` | Real-time hands-free voice conversation mode | `nova voice --push-to-talk` |
| `nova screen capture` | Capture active window/screen and run OCR text extraction | `nova screen capture --output screen.png` |
| `nova screen ask "<query>"` | Ask questions about what's currently on your screen | `nova screen ask "Explain this error"` |

### 2. 🚀 Server & Background Daemons
| Command | Description | Example |
|---|---|---|
| `nova serve` | Start the local OpenAI-compatible REST & WebSocket API server | `nova serve --port 8000` |
| `nova start` | Start the NOVA AI server as a background daemon process | `nova start` |
| `nova status` | Check status of the running background daemon | `nova status` |
| `nova restart` | Restart the running server daemon | `nova restart` |
| `nova stop` | Terminate the server background daemon | `nova stop` |
| `nova tunnel` | Expose local API securely to the internet via Cloudflare Tunnel | `nova tunnel start` |

### 3. 🧠 Models & Smart Routing
| Command | Description | Example |
|---|---|---|
| `nova model list` | List all discovered local and cloud AI models | `nova model list` |
| `nova model pull <name>` | Download a local GGUF/Ollama model directly | `nova model pull llama3` |
| `nova host <model>` | Serve and host a local model with hardware acceleration | `nova host qwen2.5:7b` |
| `nova router status` | View the Smart Router complexity tiers & statistics | `nova router status` |
| `nova router test "<query>"` | Test dynamic query complexity classification | `nova router test "Design a microservice"` |

### 4. 🛠️ Autonomous Tools & Integrations
| Command | Description | Example |
|---|---|---|
| `nova tool list` | List all registered built-in and dynamic tools | `nova tool list` |
| `nova integrations list` | View software connectors (Packet Tracer, Office, Canvas, Git) | `nova integrations list` |
| `nova integrations enable <id>`| Enable a specific software bridge | `nova integrations enable cisco_packet_tracer` |
| `nova canvas list` | List interactive Canvas charts, HTML, and SVG artifacts | `nova canvas list` |
| `nova scheduler list` | View and manage scheduled tasks and cron jobs | `nova scheduler list` |
| `nova add <mcp-server>` | Connect external Model Context Protocol (MCP) servers | `nova add filesystem` |

### 5. 📚 Long-Term Memory & Deep Research
| Command | Description | Example |
|---|---|---|
| `nova memory status` | Inspect SQLite vector store and indexed chunk counts | `nova memory status` |
| `nova memory search "<q>"` | Semantic search over indexed personal knowledge base | `nova memory search "project plan"` |
| `nova memory-wiki show <topic>`| Display structured markdown knowledge-base articles | `nova memory-wiki show profile` |
| `nova research "<topic>"` | Multi-hop autonomous deep research with cited sources | `nova research "Latest advancements in LLM reasoning"` |

### 6. ⚙️ Diagnostics, Config & Benchmarking
| Command | Description | Example |
|---|---|---|
| `nova doctor` | Run full hardware, GPU, and engine health diagnostics | `nova doctor` |
| `nova init` | Auto-detect GPU hardware and create `~/.nova_ai/config.toml` | `nova init --preset deep-research` |
| `nova config show` | Print loaded configuration hierarchy and settings | `nova config show` |
| `nova config set <k> <v>` | Modify a configuration property in TOML | `nova config set engine.default ollama` |
| `nova bench` | Measure inference latency, tokens/sec, and energy consumption | `nova bench --models llama3` |
| `nova self-update` | Upgrade NOVA AI to the latest release | `nova self-update` |

---

See the [User Guide](https://hamza35779.github.io/NOVA-AI/user-guide/morning-digest/) and [Tutorials](https://hamza35779.github.io/NOVA-AI/tutorials/) for detailed setup instructions.

Full documentation — including Docker deployment, cloud engines, development setup, and tutorials — at **[hamza35779.github.io/NOVA-AI](https://hamza35779.github.io/NOVA-AI/)**.

## Community

- **GitHub:** [github.com/Hamza35779/NOVA-AI](https://github.com/Hamza35779/NOVA-AI)
- **Issues:** [github.com/Hamza35779/NOVA-AI/issues](https://github.com/Hamza35779/NOVA-AI/issues)

## Contributing

We welcome contributions! See the [Contributing Guide](CONTRIBUTING.md) for incentives, contribution types, and the PR process.

Quick start for contributors:

```bash
git clone https://github.com/Hamza35779/NOVA-AI.git
cd NOVA AI
uv sync --extra dev
uv run pre-commit install
uv run pytest tests/ -v
```

Browse the [Roadmap](https://hamza35779.github.io/NOVA-AI/development/roadmap/) for areas where help is needed. Comment **"take"** on any issue to get auto-assigned.

## License

[Apache 2.0](LICENSE)

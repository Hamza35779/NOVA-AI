# NOVA AI — Project Proposal

> **Personal AI, On Personal Devices.**

**Version:** 1.2.4
**License:** Apache 2.0
**Repository:** [github.com/Hamza35779/NOVA-AI](https://github.com/Hamza35779/NOVA-AI)
**Documentation:** [hamza35779.github.io/NOVA-AI](https://hamza35779.github.io/NOVA-AI/)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Proposed Solution](#3-proposed-solution)
4. [Technical Architecture](#4-technical-architecture)
5. [Key Features](#5-key-features)
6. [Use Cases](#6-use-cases)
7. [Competitive Analysis](#7-competitive-analysis)
8. [Technical Specifications](#8-technical-specifications)
9. [Roadmap](#9-roadmap)
10. [Conclusion](#10-conclusion)

---

## 1. Executive Summary

NOVA AI is a **local-first personal AI agent framework** built in Python, Rust (PyO3), and TypeScript. It provides a modular, extensible stack for building AI agents that run on personal devices by default, calling cloud APIs only when necessary.

The framework is organized around **five core primitives** — Intelligence, Engine, Agentic Logic, Memory, and Learning — connected through trace-driven feedback loops. It ships with 8+ agent types, 58+ built-in tools, 5 memory backends, multiple inference engine backends, and a comprehensive CLI with a web-based workstation UI.

**Key differentiators:**
- Local-first by default (Ollama, vLLM, llama.cpp) with optional cloud fallback
- Trace-driven learning that improves model routing and agent performance over time
- 58+ tools including web browsing, code execution, file I/O, and knowledge retrieval
- Full MCP (Model Context Protocol) integration for external tool servers
- Self-contained Windows installer — no uv, git, or Python required for end users
- Global-hotkey Quick Capture popup (Windows `Alt+Space`, macOS `Cmd+Shift+Space`)
- Self-healing build diagnostics (`nova dev-watch`) with a live Dashboard feed

---

## 2. Problem Statement

### The Cloud Dependency Problem

Personal AI agents are exploding in popularity, but nearly all of them still route intelligence through cloud APIs. Your "personal" AI continues to depend on someone else's server. This creates three critical problems:

| Problem | Impact |
|---------|--------|
| **Privacy** | All queries, documents, and conversations leave the user's device |
| **Cost** | Cloud inference costs scale linearly with usage — $0.01–$0.10+ per query |
| **Latency** | Network round-trips add 200–2000ms per inference call |
| **Availability** | No offline capability; service outages render the agent useless |
| **Sovereignty** | Users have no control over data retention, model changes, or pricing |

### What's Been Missing

Local language models already handle most single-turn chat and reasoning queries, and their capability per watt keeps improving year over year. What has been missing is the **software stack** to make local-first personal AI practical — a framework that handles model routing, tool use, memory, scheduling, and learning without requiring cloud dependency.

**NOVA AI is that stack.**

---

## 3. Proposed Solution

### Vision

Build a production-grade framework for local-first personal AI that is both a research platform and a production foundation — in the spirit of PyTorch for on-device intelligence.

### Five-Primitive Architecture

NOVA AI's architecture is organized around five core abstractions that work together through trace-driven feedback:

```
┌─────────────────────────────────────────────────────┐
│                    LEARNING                          │
│         (Trace-driven routing & rewards)             │
├──────────┬──────────┬──────────┬────────────────────┤
│INTELLIGENCE│  ENGINE  │ AGENTS  │      MEMORY        │
│ Model     │ Inference│ Pluggable│  Persistent        │
│ Catalog   │ Backends │ Agents   │  Searchable Storage │
└──────────┴──────────┴──────────┴────────────────────┘
         │              │              │
         └──────────────┼──────────────┘
                        │
                   [EventBus]
              (Trace Collection)
```

#### 1. Intelligence — Model Definition & Catalog

Maintains a catalog of known models with metadata (parameter count, context length, VRAM requirements, supported engines). Models discovered at runtime from running engines are automatically merged into the `ModelRegistry`.

#### 2. Engine — Inference Runtime

All backends implement the `InferenceEngine` ABC with a uniform interface: `generate()`, `stream()`, `list_models()`, and `health()`.

| Backend | Type | Use Case |
|---------|------|----------|
| Ollama | Local | Default local engine, broad model support |
| vLLM | Local | High-throughput serving with PagedAttention |
| SGLang | Local | Structured generation with constrained decoding |
| llama.cpp | Local | GGUF quantized models, CPU/GPU hybrid |
| Cloud (OpenAI, Anthropic, Google) | Cloud | Fallback for complex queries |

#### 3. Agentic Logic — Pluggable Agents

Eight agent types across three execution modes (on-demand, scheduled, continuous):

| Agent | Mode | Description |
|-------|------|-------------|
| `simple` | On-demand | Single-turn Q&A, no tools |
| `orchestrator` | On-demand | Multi-turn tool-calling loop (default) |
| `native_react` | On-demand | Thought-Action-Observation reasoning loop |
| `native_openhands` | On-demand | CodeAct — generates and executes Python |
| `deep_research` | On-demand | Multi-hop retrieval with cited reports |
| `operative` | Continuous | Persistent autonomous agent with state |
| `monitor_operative` | Continuous | Long-horizon monitoring with memory |
| `proactive_agent` | Scheduled | Autonomous routine task handling |

#### 4. Memory — Persistent Searchable Storage

Five backends for document ingestion, chunking, embedding, and retrieval:

| Backend | Description |
|---------|-------------|
| SQLite/FTS5 | Zero-dependency default |
| FAISS | Dense vector retrieval |
| ColBERTv2 | Late interaction retrieval |
| BM25 | Classic term-frequency |
| Hybrid | Reciprocal Rank Fusion of sparse + dense |

#### 5. Learning — Trace-Driven Feedback

Every agent interaction produces a `Trace` capturing the full sequence of steps. The `TraceAnalyzer` computes statistics, and the `TraceDrivenPolicy` uses these to learn which model/agent/tool combinations produce the best outcomes.

---

## 4. Technical Architecture

### Registry Pattern

All extensible components use a decorator-based registry for runtime discovery:

```python
@EngineRegistry.register("ollama")
class OllamaEngine(InferenceEngine):
    ...
```

Typed registries exist for: Models, Engines, Memory backends, Agents, Tools, Router policies, Benchmarks, and Channels.

### Tool Ecosystem (58+ Tools)

| Category | Tools |
|----------|-------|
| **Web** | `web_search`, `browser_navigate`, `browser_click`, `browser_extract`, `browser_screenshot`, `http_request`, `web_readability` |
| **Code** | `code_interpreter`, `code_interpreter_docker`, `shell_exec`, `repl`, `code_scaffolder` |
| **Files** | `file_read`, `file_write`, `apply_patch`, `git_tool`, `git_manager`, `file_converter` |
| **Knowledge** | `knowledge_search`, `retrieval`, `scan_chunks`, `memory_manage`, `memory_wiki_tools` |
| **Media** | `image_tool`, `audio_tool`, `text_to_speech`, `screen_capture`, `screen_monitor` |
| **System** | `system_monitor`, `scheduler_tool`, `canvas_tool`, `clipboard_ai` |
| **Data** | `data_analyzer`, `db_query`, `pdf_tool`, `doc_generator` |
| **Integration** | `mcp_adapter`, `docker_shell_exec`, `cisco_packet_tracer`, `api_tester` |

### MCP Integration

Full Model Context Protocol (MCP) client/server implementation:
- `MCPClient` connects to external MCP servers via transports
- `MCPToolAdapter` wraps external tools as native `BaseTool` instances
- MCP-discovered tools are seamlessly integrated into agents

### Workflow Engine

DAG-based workflow execution with:
- Sequential, parallel, and conditional nodes
- Loop nodes with degenerate-loop detection
- Programmatic and config-based workflow construction

### Security & Safety

- **Loop Guard**: SHA-256 hash tracking, ping-pong detection, per-tool budgets
- **Capability Policy / RBAC**: Tools declare `required_capabilities`; agents need matching permissions
- **Confirmation System**: Sensitive tools require user confirmation
- **Boundary Guard**: Scans external tool arguments for security
- **Taint Checking**: Tracks data provenance through tool pipelines
- **SSRF Protection**: Web tools check for server-side request forgery
- **Budget Enforcement**: Per-agent cost/token limits with automatic pause

---

## 5. Key Features

### Smart Model Router

Query complexity routing with `model="auto"`:
- Simple queries stay on the fastest local engine
- Complex queries (score ≥ 0.55) escalate to cloud models
- Cloud-unreachable queries fall back to local
- Per-query cost tracking in traces and telemetry

### Skills System

Skills teach agents how to better use tools. Every skill is a tool — agents discover them from a catalog and invoke them on demand.
- Import from Hermes Agent (~150 skills), OpenClaw (~13,700 community skills)
- Auto-synthesize skills from repeated tool patterns (SkillForge)
- Benchmark skill impact with `nova bench skills`

### Morning Digest

Spoken daily briefings from email, calendar, health, and news with TTS audio. Configurable presets for macOS, Linux, and minimal setups. A desktop notification fires the moment a digest is stored — one hook covering the scheduler, CLI, and server delivery paths — and `nova digest` plays the audio natively on Windows.

### Quick Capture Popup

A Raycast-style chat popup summonable from anywhere: `Alt+Space` on Windows, `Cmd+Shift+Space` on macOS. Frameless, always-on-top, streaming responses backed by the local API; the conversation syncs back into the main workstation automatically.

### Dev-Watch Self-Healing Diagnostics

`nova dev-watch -c "pytest -q"` runs a build or test command, classifies failures (timeout / exit code / embedded tracebacks), and consults the self-healing ReAct agent for a fix — as a suggestion or applied in place. Runs are reported to `/api/devwatch/runs` and surfaced live on the Dashboard's Build Diagnostics panel.

### Deep Research

Multi-hop retrieval agent that searches personal data across sources (email, Slack, documents), cross-references results, and produces narrative answers with inline source citations.

### Desktop Application

Tauri-based desktop app with:
- Native window with real-time status
- Ollama integration for local model management
- Model Hub with curated catalog and background installation
- Auto-update via GitHub releases
- Global-hotkey Quick Capture popup (Alt+Space) sharing conversation state with the main window

### Multi-Channel Support

Built-in channels for: Telegram, Discord, Slack, WhatsApp, Line, Viber, Messenger, Reddit, Mastodon, XMPP, Rocket.Chat, Zulip, Twitter/X, Twitch, Nostr, Twilio, Gmail.

---

## 6. Use Cases

### 1. Personal Morning Briefing
```
nova init --preset morning-digest-mac
nova connect gdrive
nova digest --fresh
```
Automated daily briefing combining email, calendar, health data, and news — delivered as spoken audio.

### 2. Deep Research Assistant
```
nova research "Latest advancements in LLM reasoning"
```
Multi-hop research across indexed documents and web sources with cited reports.

### 3. Code Assistant
```
nova init --preset code-assistant
nova chat
```
Agent with code execution, file I/O, and shell access for development tasks.

### 4. Scheduled Monitoring
```
nova init --preset scheduled-monitor
```
Stateful agent on a schedule with memory for continuous monitoring tasks.

### 5. Channel Bot
```
nova agents create --template telegram-bot --channel telegram
```
AI-powered bot for messaging platforms with multi-turn conversation support.

---

## 7. Competitive Analysis

| Feature | NOVA AI | AutoGPT | LangChain | OpenHands | Local LLM Stack |
|---------|---------|---------|-----------|-----------|-----------------|
| Local-first default | ✅ | ❌ | ❌ | ❌ | ✅ |
| Multi-engine support | ✅ (5+) | ❌ | ✅ | ❌ | ❌ |
| Agent types | 8+ | 1 | Composable | 1 | 0 |
| Built-in tools | 58+ | ~10 | ~50 | ~5 | 0 |
| Memory backends | 5 | 1 | ✅ | ❌ | 0 |
| Trace-driven learning | ✅ | ❌ | ❌ | ❌ | ❌ |
| MCP integration | ✅ | ❌ | ✅ | ❌ | ❌ |
| Scheduled agents | ✅ | ❌ | ❌ | ❌ | ❌ |
| Multi-channel | 15+ | ❌ | ❌ | ❌ | ❌ |
| Self-contained installer | ✅ | ❌ | ❌ | ❌ | ❌ |
| Open source | ✅ (Apache 2.0) | ✅ | ✅ | ✅ | Varies |

---

## 8. Technical Specifications

### Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.10–3.13 |
| **Performance** | Rust (PyO3) — loop guard, memory operations |
| **Frontend** | TypeScript (Vite + React) |
| **Desktop** | Tauri 2.x |
| **Server** | FastAPI + Uvicorn |
| **Database** | SQLite (traces, telemetry, memory, scheduler) |
| **Build** | Hatchling + hatch-vcs, PyInstaller |
| **CI/CD** | GitHub Actions |
| **License** | Apache 2.0 |

### System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **OS** | Windows 10 1809+, macOS 10.15+, Ubuntu 22.04+ | Latest stable |
| **RAM** | 8 GB | 16 GB+ |
| **Storage** | 2 GB (app) + model storage | SSD recommended |
| **GPU** | None (CPU inference) | NVIDIA/AMD for local models |
| **Python** | 3.10–3.13 | 3.12+ |

### Installation

| Platform | Method |
|----------|--------|
| Windows | `irm https://hamza35779.github.io/NOVA-AI/install.ps1 \| iex` or `.exe` installer |
| Linux/macOS | `curl -fsSL https://hamza35779.github.io/NOVA-AI/install.sh \| bash` |
| Docker | `docker compose -f deploy/docker/docker-compose.yml up` |
| Desktop | Download `.exe` / `.dmg` / `.AppImage` from releases |
| PyPI | `pip install nova-ai-pro` |

---

## 9. Roadmap

### Current Status (v1.2.4)

- ✅ Five-primitive architecture implemented
- ✅ 8+ agent types registered (incl. `self_healing_react`)
- ✅ 58+ built-in tools
- ✅ 5 memory backends
- ✅ Smart model router with complexity scoring
- ✅ MCP client/server integration
- ✅ Desktop app (Tauri) with auto-update
- ✅ Self-contained Windows installer
- ✅ Quick Capture global-hotkey popup (Windows + macOS)
- ✅ `nova dev-watch` self-healing build diagnostics + Dashboard feed
- ✅ Desktop notifications for digest delivery; Windows audio playback
- ✅ Multi-channel support (15+ platforms)
- ✅ Trace-driven learning system
- ✅ Skill synthesis pipeline (SkillForge)
- ✅ SFT/GRPO/DPO training pipelines

### Planned

- [ ] Enhanced hybrid local+cloud agent paradigms
- [ ] Improved skill validation and adoption metrics
- [ ] Additional channel integrations
- [ ] Mobile companion app
- [ ] Enterprise deployment features
- [ ] Advanced energy monitoring and optimization

---

## 10. Conclusion

NOVA AI addresses the fundamental gap in personal AI: a production-grade, local-first framework that makes on-device AI agents practical. By combining modular architecture, trace-driven learning, and a comprehensive tool ecosystem, it enables developers and users to build and run AI agents that respect privacy, minimize cost, and work offline.

The framework is open source (Apache 2.0), actively maintained, and designed for extensibility. We welcome contributions from the community.

---

**Contact:**
- GitHub: [github.com/Hamza35779/NOVA-AI](https://github.com/Hamza35779/NOVA-AI)
- Issues: [github.com/Hamza35779/NOVA-AI/issues](https://github.com/Hamza35779/NOVA-AI/issues)
- Documentation: [hamza35779.github.io/NOVA-AI](https://hamza35779.github.io/NOVA-AI/)

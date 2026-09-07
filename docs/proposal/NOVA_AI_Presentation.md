---
marp: true
theme: default
paginate: true
backgroundColor: #0F0B1E
color: #E0E0E0
style: |
  section {
    font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
    background-color: #0F0B1E;
    color: #E0E0E0;
  }
  h1 { color: #7C4DFF; }
  h2 { color: #B388FF; }
  h3 { color: #E040FB; }
  a { color: #40C4FF; }
  strong { color: #E040FB; }
  code { background: #1A1A2E; color: #B388FF; }
  table { font-size: 0.85em; }
  blockquote { border-left: 4px solid #7C4DFF; padding-left: 1em; color: #B0B0B0; }
---

<!-- _class: lead -->

# NOVA AI

## Personal AI, On Personal Devices.

**Modular AI Agent Framework · Local-First · Open Source**

GitHub: [Hamza35779/NOVA-AI](https://github.com/Hamza35779/NOVA-AI)
Docs: [hamza35779.github.io/NOVA-AI](https://hamza35779.github.io/NOVA-AI/)

---

# The Problem

## Cloud-Dependent "Personal" AI

Your AI assistant sends **every query, document, and conversation** to someone else's server.

| Problem | Impact |
|---------|--------|
| **Privacy** | All data leaves your device |
| **Cost** | $0.01–$0.10+ per query, scaling linearly |
| **Latency** | 200–2000ms network round-trips |
| **Availability** | No offline; outages = no AI |
| **Sovereignty** | No control over data, models, or pricing |

> Local models already handle most tasks. What's missing is the **software stack** to make local-first AI practical.

---

# Our Vision

## Local-First Personal AI

**NOVA AI** is a framework for building AI agents that:

- 🏠 **Run locally by default** — Ollama, vLLM, llama.cpp
- ☁️ **Call cloud only when necessary** — smart routing
- 🔒 **Keep data on your device** — privacy by design
- 📚 **Learn from your traces** — improves over time
- 🛠️ **Use tools autonomously** — 58+ built-in tools

> Built in Python + Rust (PyO3) + TypeScript · Apache 2.0 · Open Source

---

# Architecture Overview

## Five Core Primitives

```
┌─────────────────────────────────────────────────────┐
│                    LEARNING                          │
│         (Trace-driven routing & rewards)             │
├──────────┬──────────┬──────────┬────────────────────┤
│INTELLIGENCE│  ENGINE  │ AGENTS  │      MEMORY        │
│ Model     │ Inference│ Pluggable│  Persistent        │
│ Catalog   │ Backends │ Agents   │  Searchable Storage │
└──────────┴──────────┴──────────┴────────────────────┘
```

- **Intelligence** — Model catalog with runtime discovery
- **Engine** — Inference backends (Ollama, vLLM, Cloud, etc.)
- **Agents** — 8+ pluggable agent types
- **Memory** — 5 searchable storage backends
- **Learning** — Trace-driven feedback loop

---

# Engine Backends

## Pluggable Inference Runtime

All backends implement `InferenceEngine` ABC: `generate()`, `stream()`, `list_models()`, `health()`

| Backend | Type | Highlights |
|---------|------|-----------|
| **Ollama** | Local | Default, broad model support |
| **vLLM** | Local | PagedAttention, high throughput |
| **SGLang** | Local | Structured generation |
| **llama.cpp** | Local | GGUF quantized, CPU/GPU hybrid |
| **Cloud** | Cloud | OpenAI, Anthropic, Google |

**Smart Router**: `model="auto"` scores query complexity → simple = local, complex = cloud

---

# Agent Types

## 8+ Agents, 3 Execution Modes

| Agent | Mode | What It Does |
|-------|------|-------------|
| `simple` | On-demand | Single-turn Q&A, no tools |
| `orchestrator` | On-demand | Multi-turn tool-calling loop (**default**) |
| `native_react` | On-demand | Thought → Action → Observation loop |
| `native_openhands` | On-demand | CodeAct — writes and executes Python |
| `deep_research` | On-demand | Multi-hop research with citations |
| `operative` | Continuous | Persistent agent with state management |
| `monitor_operative` | Continuous | Long-horizon monitoring |
| `proactive_agent` | Scheduled | Autonomous routine task handling |

---

# Tool Ecosystem

## 58+ Built-in Tools

| Category | Tools |
|----------|-------|
| 🌐 **Web** | `web_search`, `browser_navigate`, `browser_click`, `browser_extract`, `http_request` |
| 💻 **Code** | `code_interpreter`, `code_interpreter_docker`, `shell_exec`, `repl` |
| 📁 **Files** | `file_read`, `file_write`, `apply_patch`, `git_tool`, `git_manager` |
| 🧠 **Knowledge** | `knowledge_search`, `retrieval`, `scan_chunks`, `memory_manage` |
| 🎨 **Media** | `image_tool`, `audio_tool`, `text_to_speech`, `screen_capture` |
| ⚙️ **System** | `system_monitor`, `scheduler_tool`, `canvas_tool`, `clipboard_ai` |

---

# Memory & Knowledge

## 5 Searchable Storage Backends

| Backend | Description | Best For |
|---------|-------------|----------|
| **SQLite/FTS5** | Zero-dependency default | Quick start |
| **FAISS** | Dense vector retrieval | Semantic search |
| **ColBERTv2** | Late interaction | High-precision retrieval |
| **BM25** | Term-frequency | Keyword search |
| **Hybrid** | Reciprocal Rank Fusion | Best of both worlds |

**Pipeline**: Document ingestion → Chunking → Embedding → Storage → Context injection

Agents automatically retrieve relevant context from your knowledge base.

---

# Learning & Traces

## Trace-Driven Feedback Loop

```
Agent runs query → Produces Trace → TraceAnalyzer computes stats
                                          ↓
Better routing ← TraceDrivenPolicy learns ← Metrics (latency, cost, quality)
```

- Every interaction produces a **Trace** (steps, tools, timing, cost)
- **HeuristicRouter** scores query complexity for smart routing
- **TraceDrivenPolicy** learns optimal model/agent/tool combinations
- **SkillForge** auto-synthesizes skills from repeated tool patterns
- Training pipelines: **SFT**, **GRPO**, **DPO**, **LoRA**

---

# Use Cases

## What You Can Build

### 🌅 Morning Digest
```
nova init --preset morning-digest-mac
nova connect gdrive
nova digest --fresh
```
Spoken daily briefing from email, calendar, health, and news.

### 🔬 Deep Research
```
nova research "Latest advancements in LLM reasoning"
```
Multi-hop research with cited reports across web and local docs.

### 💻 Code Assistant
```
nova init --preset code-assistant
nova chat
```
Agent with code execution, file I/O, and shell access.

---

# CLI & Installation

## Start in Seconds

| Platform | Quick Start |
|----------|------------|
| **Windows** | Double-click `start.bat` or run installer `.exe` |
| **Linux/macOS** | `curl -fsSL https://hamza35779.github.io/NOVA-AI/install.sh \| bash` |
| **Docker** | `docker compose -f deploy/docker/docker-compose.yml up` |
| **Desktop** | Download `.exe` / `.dmg` / `.AppImage` |
| **PyPI** | `pip install nova-ai-pro` |

### Key Commands

```bash
nova chat                    # Interactive chat
nova voice --push-to-talk    # Voice conversation
nova serve                   # Start API server (OpenAI-compatible)
nova doctor                  # System diagnostics
nova agents list             # List managed agents
```

---

# MCP & Extensibility

## Model Context Protocol Integration

- Full **MCP client/server** implementation
- Connect external tool servers: `nova add filesystem`
- MCP-discovered tools are **seamlessly integrated** into agents
- Supports any MCP-compatible server

### Registry Pattern

Every component is pluggable:

```python
@EngineRegistry.register("my-engine")
class MyEngine(InferenceEngine):
    ...
```

Add new engines, agents, tools, channels, or memory backends by implementing the ABC and decorating with `@Registry.register()`.

---

# Competitive Advantage

## Why NOVA AI?

| Feature | NOVA AI | AutoGPT | LangChain | OpenHands |
|---------|---------|---------|-----------|-----------|
| Local-first default | ✅ | ❌ | ❌ | ❌ |
| Multi-engine support | ✅ (5+) | ❌ | ✅ | ❌ |
| Agent types | 8+ | 1 | Composable | 1 |
| Built-in tools | 58+ | ~10 | ~5 | ~5 |
| Trace-driven learning | ✅ | ❌ | ❌ | ❌ |
| Scheduled agents | ✅ | ❌ | ❌ | ❌ |
| Multi-channel | 15+ | ❌ | ❌ | ❌ |
| Self-contained installer | ✅ | ❌ | ❌ | ❌ |

---

# Roadmap

## Current Status (v1.2.4)

✅ Five-primitive architecture · ✅ 8+ agent types · ✅ 58+ tools
✅ 5 memory backends · ✅ Smart router · ✅ MCP integration
✅ Desktop app · ✅ Windows installer · ✅ 15+ channels
✅ Trace-driven learning · ✅ Skill synthesis · ✅ Training pipelines

## Planned

- Enhanced hybrid local+cloud paradigms
- Improved skill validation and adoption
- Additional channel integrations
- Mobile companion app
- Enterprise deployment features
- Advanced energy monitoring

---

<!-- _class: lead -->

# Get Started

## Personal AI, On Personal Devices.

```bash
# Install
curl -fsSL https://hamza35779.github.io/NOVA-AI/install.sh | bash

# Or for Windows
irm https://hamza35779.github.io/NOVA-AI/install.ps1 | iex
```

**GitHub:** [Hamza35779/NOVA-AI](https://github.com/Hamza35779/NOVA-AI)
**Docs:** [hamza35779.github.io/NOVA-AI](https://hamza35779.github.io/NOVA-AI/)
**License:** Apache 2.0

*Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md)*

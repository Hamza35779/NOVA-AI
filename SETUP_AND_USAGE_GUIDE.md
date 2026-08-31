# NOVA AI — Complete Setup & User Guide

Welcome to **NOVA AI**, a modular, high-performance AI assistant workstation. NOVA AI gives you complete freedom to run local AI models privately on your computer without external dependencies, connect to Ollama, or use cloud models like GPT-4o, Claude 3.5, and Gemini.

---

## 📋 Table of Contents

1. [System Requirements](#1-system-requirements)
2. [Installation Methods](#2-installation-methods)
   - [Method A: Standalone Windows Executable (No Python Required)](#method-a-standalone-windows-executable-easiest)
   - [Method B: Python Package via Pip](#method-b-python-package-via-pip)
   - [Method C: Developer Source Install](#method-c-developer-source-install)
3. [Starting NOVA AI](#3-starting-nova-ai)
4. [Managing & Running Models](#4-managing--running-models)
   - [Option 1: In-Process GGUF Models (100% Free, No Ollama)](#option-1-in-process-gguf-models-100-free-no-ollama)
   - [Option 2: Ollama Local Models](#option-2-ollama-local-models)
   - [Option 3: Cloud Models (OpenAI, Anthropic, Gemini, Groq)](#option-3-cloud-models)
5. [Core Features & Usage Modes](#5-core-features--usage-modes)
   - [Web Workstation UI](#web-workstation-ui)
   - [Command-Line Interface (CLI)](#command-line-interface-cli)
   - [Voice Mode & Wake-Word Detection](#voice-mode--wake-word-detection)
   - [Task Planner & Workflow Execution](#task-planner--workflow-execution)
   - [Interactive Canvas Artifacts](#interactive-canvas-artifacts)
   - [Deep Research & Web Search](#deep-research--web-search)
   - [Memory Wiki Knowledge Base](#memory-wiki-knowledge-base)
6. [Troubleshooting & Common Questions](#6-troubleshooting--common-questions)

---

## 1. System Requirements

| Specification | Minimum | Recommended |
|---|---|---|
| **OS** | Windows 10/11 (64-bit), macOS 12+, Linux | Windows 11 (64-bit) / macOS / Ubuntu |
| **RAM** | 4 GB | 16 GB+ |
| **Storage** | 1 GB (App only) | 10 GB+ (for local model weights) |
| **GPU** *(Optional)* | Integrated graphics / CPU only | NVIDIA GPU with CUDA or Apple Silicon (Metal) |

---

## 2. Installation Methods

Choose the method that best fits your environment:

### Method A: Standalone Windows Executable (Easiest)
*No Python, Node.js, or external runtimes required.*

1. Download `nova-ai-windows-x64.zip` or `nova-ai-windows-x64.exe` from the [Releases page](https://github.com/Hamza35779/NOVA-AI/releases) or your `dist/` directory.
2. Extract the `.zip` archive to a folder of your choice (e.g. `C:\Program Files\NOVA AI` or `D:\NOVA AI`).
3. Double-click `nova-ai.exe` or launch it via PowerShell / Command Prompt:
   ```powershell
   .\nova-ai.exe serve
   ```
4. Open your browser to: **`http://localhost:8000`**

---

### Method B: Python Package via Pip
*Recommended for Python users and cross-platform environments.*

1. Make sure Python 3.10+ is installed on your system.
2. Open your terminal and install NOVA AI:
   ```bash
   pip install nova-ai-pro
   ```
3. *(Optional)* Install in-process GGUF engine support:
   ```bash
   pip install "nova-ai-pro[inference-gguf]"
   ```
4. Start NOVA AI:
   ```bash
   nova serve
   ```
5. Open your browser to: **`http://localhost:8000`**

---

### Method C: Developer Source Install
*For modifying source code and contributing.*

1. Clone the repository:
   ```bash
   git clone https://github.com/Hamza35779/NOVA-AI.git
   cd NOVA-AI
   ```
2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   # Windows PowerShell:
   .venv\Scripts\Activate.ps1
   # macOS / Linux:
   source .venv/bin/activate
   ```
3. Install dependencies in editable mode:
   ```bash
   pip install -e ".[dev,inference-gguf,tools-search]"
   ```
4. Build the web frontend:
   ```bash
   cd frontend
   npm install
   npm run build
   cd ..
   ```
5. Start the development server:
   ```bash
   nova serve --reload
   ```

---

## 3. Starting NOVA AI

### Starting the Web UI Server
```bash
# Default (port 8000)
nova serve

# Custom host and port
nova serve --host 0.0.0.0 --port 8080
```

### Running as a Background Daemon
```bash
nova start      # Starts server in background
nova status     # Checks if server is running
nova stop       # Stops the server
nova restart    # Restarts the server
```

---

## 4. Managing & Running Models

NOVA AI gives you full flexibility in choosing how to run models:

```
┌─────────────────────────────────────────────────────────────┐
│                       NOVA AI Engine                        │
├─────────────────┬─────────────────────┬─────────────────────┤
│  1. In-Process  │  2. Local Ollama    │  3. Cloud APIs      │
│     GGUF        │     Integration     │     (OpenAI/Claude) │
│  (100% Offline) │  (Local Server)     │  (High Capability)  │
└─────────────────┴─────────────────────┴─────────────────────┘
```

### Option 1: In-Process GGUF Models (100% Free, No Ollama)
*No setup, zero configuration, works out of the box.*

1. Open NOVA AI in your browser (`http://localhost:8000`).
2. Click **GGUF Hub (No Ollama)** in the sidebar (`/gguf-hub`).
3. Browse the curated catalog (e.g. **Qwen 2.5**, **Llama 3.2**, **Phi-4 Mini**, **DeepSeek-R1**, **Mistral**).
4. Click **Download & Install**.
5. Watch the live progress bar download directly from Hugging Face into `~/.nova_ai/models/`.
6. Once complete, the model immediately appears in the chat model picker!

> **Manual GGUF Import:** You can also drop any `.gguf` file downloaded from Hugging Face directly into `C:\Users\<YourUsername>\.nova_ai\models\`. NOVA AI will auto-detect it.

---

### Option 2: Ollama Local Models
*If you already use Ollama.*

1. Install and run [Ollama](https://ollama.com):
   ```bash
   ollama serve
   ```
2. Pull any model in your terminal:
   ```bash
   ollama pull qwen2.5:7b
   ```
   *or* use the in-app **Model Hub (Ollama)** tab (`/model-hub`) to download models directly.
3. NOVA AI automatically detects running Ollama models and adds them to your dropdown.

---

### Option 3: Cloud Models
*For cloud-scale reasoning and vision models.*

1. Navigate to **Settings** (`/settings`) in the web UI.
2. Enter your API key(s) for your desired provider:
   - **OpenAI:** `OPENAI_API_KEY` (e.g. `gpt-4o`, `gpt-4o-mini`, `o3-mini`)
   - **Anthropic:** `ANTHROPIC_API_KEY` (e.g. `claude-3-5-sonnet`)
   - **Google Gemini:** `GEMINI_API_KEY` (e.g. `gemini-2.0-flash`, `gemini-1.5-pro`)
   - **Groq:** `GROQ_API_KEY` (e.g. `llama-3.3-70b-versatile`)
3. Select any cloud model from the top-bar dropdown.

---

## 5. Core Features & Usage Modes

### Web Workstation UI
* **Chat Interface:** Multi-turn conversations with code syntax highlighting, copy-to-clipboard, markdown formatting, and LaTeX math rendering.
* **Model Compare Mode (`/compare`):** Send a single prompt simultaneously to two different models side-by-side to compare latency, token speed, and answer quality.
* **Personas (`/personas`):** Switch between custom assistant personas (e.g., Senior Software Architect, Research Scientist, Technical Writer).

---

### Command-Line Interface (CLI)

NOVA AI includes command-line tools for quick terminal workflows:

#### 1. Quick Question (`nova ask`)
```bash
nova ask "Explain how vector embeddings work in two sentences"
```

#### 2. Terminal Interactive Chat (`nova chat`)
```bash
nova chat
```

#### 3. Clipboard AI (`nova clip`)
Summarize or translate whatever is currently in your system clipboard:
```bash
nova clip summarize
nova clip translate --to spanish
nova clip explain-code
```

#### 4. Diagnostic Doctor (`nova doctor`)
Verify your system dependencies, GPUs, and engine health:
```bash
nova doctor
```

---

### Voice Mode & Wake-Word Detection
Engage in hands-free voice conversations with NOVA AI:

```bash
# Push-to-talk voice mode
nova voice

# Hands-free wake-word mode (activates when you say "hey nova")
nova voice --wake-word "hey nova"
```

---

### Task Planner & Workflow Execution
Break down complex objectives into Directed Acyclic Graph (DAG) task plans with dependency resolution:

* In the Web UI or via API (`/api/tasks`), enter a high-level goal.
* The planner breaks the goal into sequential and parallel subtasks.
* Real-time progress updates are streamed live as each task executes.

---

### Interactive Canvas Artifacts
Generate dynamic HTML, CSS, React widgets, SVG diagrams, and visualizations directly inside your conversation:

* Ask NOVA AI to *"Create an interactive ROI calculator widget"* or *"Render an architecture diagram in Canvas"*.
* An interactive sandboxed preview renders directly inline inside the chat.

---

### Deep Research & Web Search
Perform multi-source web investigations with real-time fact synthesis:

```bash
nova ask --research "Summarize latest quantum computing milestones this month"
```

---

### Memory Wiki Knowledge Base
Build an evolving, long-term personal knowledge base:

```bash
# Inspect stored knowledge entities
nova memory-wiki list

# Search knowledge base
nova memory-wiki search "API architecture patterns"
```

---

## 6. Troubleshooting & Common Questions

### Q: Port 8000 is already in use
**Solution:** Specify an alternate port with `--port`:
```bash
nova serve --port 8080
```

### Q: Model runs slowly on my machine
**Solution:**
1. Use smaller quantized models such as **Qwen 2.5 0.5B / 1.5B** or **Phi-4 Mini 3.8B**.
2. For GPU acceleration with GGUF models on NVIDIA systems, reinstall `llama-cpp-python` with CUDA:
   ```bash
   pip install llama-cpp-python --upgrade --force-reinstall --no-cache-dir --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124
   ```

### Q: Where are configuration files and models stored?
* **Configuration:** `~/.nova_ai/config.toml`
* **GGUF Models:** `~/.nova_ai/models/`
* **Memory & Database:** `~/.nova_ai/`

---

*For issues, bug reports, and updates, visit the [NOVA AI GitHub Repository](https://github.com/Hamza35779/NOVA-AI).*

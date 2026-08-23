---
title: NOVA AI
description: Personal AI, On Personal Devices
search:
  boost: 2
hide:
  - navigation
---

# Personal AI, On Personal Devices

<p class="hero-tagline">
NOVA AI is a research framework for composable, on-device AI systems.
Build personal AI that runs on your hardware. Cloud APIs are optional.
</p>

<div class="grid cards" markdown>

-   :material-image-multiple:{ .lg .middle } **See what people use it for**

    ---

    A gallery of real setups — morning briefs that summarize your overnight Slack and email, a Discord companion that knows your calendar, a code reviewer that works at 30,000 feet. Outcome-first, with links to the docs that explain how to build each one.

    [:octicons-arrow-right-24: Browse the Showcase](showcase/index.md)

</div>

---

## Why NOVA AI?

Personal AI agents are exploding in popularity, but nearly all of them still route intelligence through cloud APIs. Your "personal" AI continues to depend on someone else's server. Local language models already handle most single-turn chat and reasoning queries, and their capability per watt keeps improving year over year. What has been missing is the software stack to make local-first personal AI practical.

NOVA AI is that stack. It is a framework for local-first personal AI, built around three core ideas: shared primitives for building on-device agents; evaluations that treat energy, FLOPs, latency, and dollar cost as first-class constraints alongside accuracy; and a learning loop that improves models using local trace data. The goal is simple: make it possible to build personal AI agents that run locally by default, calling the cloud only when truly necessary. NOVA AI aims to be both a research platform and a production foundation for local AI, in the spirit of PyTorch.

---

## Get Started

=== "Browser App"

    Run the full chat UI locally with one script:

    ```bash
    git clone https://github.com/Hamza35779/NOVA-AI.git
    cd NOVA AI
    ./scripts/quickstart.sh
    ```

    This installs dependencies, starts Ollama + a local model, launches the backend
    and frontend, and opens `http://localhost:5173` in your browser.

=== "Desktop App"

    The desktop app is a native window for the NOVA AI UI.
    The backend (Ollama + inference) runs on your machine — start it first, then open the app.

    **Step 1.** Start the backend:

    ```bash
    git clone https://github.com/Hamza35779/NOVA-AI.git
    cd NOVA AI
    ./scripts/quickstart.sh
    ```

    **Step 2.** Download and open the desktop app:

    [Download for macOS](https://github.com/Hamza35779/NOVA-AI/releases/download/desktop-v1.0.2/NOVA AI_1.0.1_universal.dmg){ .md-button .md-button--primary }

    Also available for [Windows](https://github.com/Hamza35779/NOVA-AI/releases/download/desktop-v1.0.2/NOVA AI_1.0.1_x64-setup.exe), [Linux (DEB)](https://github.com/Hamza35779/NOVA-AI/releases/download/desktop-v1.0.2/NOVA AI_1.0.1_amd64.deb), and [Linux (RPM)](https://github.com/Hamza35779/NOVA-AI/releases/download/desktop-v1.0.2/NOVA AI-1.0.1-1.x86_64.rpm). See the [Downloads](downloads.md) page for details.

    The app connects to `http://localhost:8000` automatically.

    !!! warning "macOS first launch"

        Run `xattr -cr /Applications/NOVA AI.app` if the app shows as "damaged".

=== "Python SDK"

    ```python
    from nova_ai import Nova

    j = Nova()                              # auto-detect engine
    response = j.ask("Explain quicksort.")
    print(response)
    ```

    For more control, use `ask_full()` to get usage stats, model info, and tool results:

    ```python
    result = j.ask_full(
        "What is 2 + 2?",
        agent="orchestrator",
        tools=["calculator"],
    )
    print(result["content"])       # "4"
    print(result["tool_results"])  # [{tool_name: "calculator", ...}]
    ```

=== "CLI"

    ```bash
    nova ask "What is the capital of France?"

    nova ask --agent orchestrator --tools calculator "What is 137 * 42?"

    nova serve --port 8000

    nova memory index ./docs/
    nova memory search "configuration options"
    ```

---

## Five Primitives for Personal AI

NOVA AI is built around five composable layers. Each has a clean interface and can be swapped independently.

1. **Intelligence** — Pick a model, or let NOVA AI pick one for your hardware. Manages the full catalog of local models across providers.
2. **Engine** — The inference runtime: [Ollama](https://ollama.com), [vLLM](https://github.com/vllm-project/vllm), [SGLang](https://github.com/sgl-project/sglang), [llama.cpp](https://github.com/ggerganov/llama.cpp), cloud APIs, and more. Auto-detects your hardware and recommends the best fit.
3. **Agents** — Multi-step reasoning with tool use. Eight built-in agent types from simple chat to orchestrated workflows.
4. **Tools & Memory** — Web search, calculator, file I/O, code interpreter, retrieval, persistent local state, and any external MCP server.
5. **Learning** — Your AI gets better over time. Every interaction generates traces that drive automatic improvements to model weights, prompts, and agent behavior.

---

## Key Features

<div class="grid cards" markdown>

-   **10+ Engine Backends**

    ---

    [Ollama](https://ollama.com), [vLLM](https://github.com/vllm-project/vllm), [SGLang](https://github.com/sgl-project/sglang), [llama.cpp](https://github.com/ggerganov/llama.cpp), [MLX](https://github.com/ml-explore/mlx), [Exo](https://github.com/exo-explore/exo), [LiteLLM](https://github.com/BerriAI/litellm), cloud (OpenAI/Anthropic/Google), and more. Same `InferenceEngine` interface, swap freely.

-   **Automated Workflows**

    ---

    Cron-based agents that monitor, summarize, and act. Code review, email triage, research digests — running 24/7 on your hardware.

-   **Hardware-Aware**

    ---

    Auto-detects GPU vendor, model, and VRAM. Recommends the optimal engine for your hardware.

-   **Offline-First**

    ---

    All core functionality works without a network connection. Cloud APIs are optional extras.

-   **OpenAI-Compatible API**

    ---

    `nova serve` starts a FastAPI server with SSE streaming. Drop-in replacement for OpenAI clients.

-   **Energy & Cost Tracking**

    ---

    Built-in telemetry for GPU power draw, token costs, and latency. See exactly what each query costs in watts and dollars.

</div>

---

## Documentation

<div class="grid cards" markdown>

-   **[Getting Started](getting-started/installation.md)**

    ---

    Install NOVA AI, configure your first engine, and run your first query.

-   **[User Guide](user-guide/cli.md)**

    ---

    CLI, Python SDK, and guides for [Morning Digest](user-guide/morning-digest.md), [Deep Research](user-guide/deep-research.md), [Code Assistant](user-guide/code-assistant.md), [Scheduled Monitor](user-guide/scheduled-monitor.md), [Simple Chat](user-guide/chat-simple.md), [Evaluations](user-guide/evaluations.md), agents, memory, tools, and telemetry.

-   **[Architecture](architecture/overview.md)**

    ---

    Five-primitive design, registry pattern, query flow, and cross-cutting learning.

-   **[API Reference](api-reference/nova_ai/index.md)**

    ---

    Auto-generated reference for every module.

-   **[Deployment](deployment/docker.md)**

    ---

    Docker, systemd, launchd. GPU-accelerated container images.

-   **[Development](development/contributing.md)**

    ---

    Contributing guide, extension patterns, roadmap, and changelog.

</div>


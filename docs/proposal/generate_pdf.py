"""Generate NOVA AI Technical Proposal PDF using fpdf2."""

from fpdf import FPDF

class NovaPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.add_font("Arial", "", r"C:\Windows\Fonts\arial.ttf")
        self.add_font("Arial", "B", r"C:\Windows\Fonts\arialbd.ttf")
        self.add_font("Arial", "I", r"C:\Windows\Fonts\ariali.ttf")
        self.add_font("ArialMono", "", r"C:\Windows\Fonts\consola.ttf")

    def header(self):
        self.set_font("Arial", "B", 9)
        self.set_text_color(120, 80, 220)
        self.cell(0, 8, "NOVA AI — Technical Proposal", align="R")
        self.ln(10)
        self.set_draw_color(120, 80, 220)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def section_title(self, num, title):
        self.set_font("Arial", "B", 14)
        self.set_text_color(120, 80, 220)
        self.ln(4)
        self.cell(0, 10, f"{num}. {title}")
        self.ln(10)
        self.set_text_color(50, 50, 50)

    def subsection(self, title):
        self.set_font("Arial", "B", 11)
        self.set_text_color(80, 50, 180)
        self.ln(2)
        self.cell(0, 8, title)
        self.ln(9)
        self.set_text_color(50, 50, 50)

    def body(self, text):
        self.set_font("Arial", "", 10)
        self.set_text_color(50, 50, 50)
        self.multi_cell(0, 5.5, text)
        self.ln(2)

    def code_block(self, text):
        self.set_fill_color(240, 240, 250)
        self.set_font("ArialMono", "", 9)
        self.set_text_color(60, 60, 60)
        x = self.get_x()
        self.multi_cell(0, 5, text, fill=True)
        self.ln(3)
        self.set_text_color(50, 50, 50)

    def table_header(self, cols, widths):
        self.set_font("Arial", "B", 9)
        self.set_fill_color(120, 80, 220)
        self.set_text_color(255, 255, 255)
        for i, col in enumerate(cols):
            self.cell(widths[i], 7, col, border=1, fill=True, align="C")
        self.ln()
        self.set_text_color(50, 50, 50)

    def table_row(self, cols, widths, fill=False):
        self.set_font("Arial", "", 9)
        if fill:
            self.set_fill_color(245, 240, 255)
        else:
            self.set_fill_color(255, 255, 255)
        max_h = 7
        for i, col in enumerate(cols):
            self.cell(widths[i], max_h, col, border=1, fill=fill, align="L")
        self.ln()


pdf = NovaPDF()
pdf.alias_nb_pages()
pdf.set_auto_page_break(auto=True, margin=20)

# === TITLE PAGE ===
pdf.add_page()
pdf.ln(40)
pdf.set_font("Helvetica", "B", 28)
pdf.set_text_color(120, 80, 220)
pdf.cell(0, 15, "NOVA AI", align="C")
pdf.ln(18)
pdf.set_font("Helvetica", "", 16)
pdf.set_text_color(80, 50, 180)
pdf.cell(0, 10, "Technical Proposal", align="C")
pdf.ln(14)
pdf.set_font("Helvetica", "I", 12)
pdf.set_text_color(120, 120, 120)
pdf.cell(0, 8, "Personal AI, On Personal Devices.", align="C")
pdf.ln(30)

pdf.set_draw_color(120, 80, 220)
pdf.line(60, pdf.get_y(), 150, pdf.get_y())
pdf.ln(15)

pdf.set_font("Helvetica", "", 11)
pdf.set_text_color(80, 80, 80)
info = [
    ("Version", "1.2.4"),
    ("License", "Apache 2.0"),
    ("Repository", "github.com/Hamza35779/NOVA-AI"),
    ("Documentation", "hamza35779.github.io/NOVA-AI"),
    ("Python", "3.10 - 3.13"),
    ("Date", "September 2026"),
]
for label, value in info:
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(50, 7, label + ":", align="R")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, "  " + value)
    pdf.ln(7)

# === 1. ABSTRACT ===
pdf.add_page()
pdf.section_title("1", "Abstract")
pdf.body(
    "NOVA AI is a local-first personal AI agent framework built in Python 3.10+ with Rust (PyO3) "
    "performance extensions and a TypeScript/Tauri desktop frontend. It provides a modular, "
    "extensible stack organized around five core primitives — Intelligence, Engine, Agentic Logic, "
    "Memory, and Learning — connected through trace-driven feedback loops.\n\n"
    "The framework ships with 8+ agent types, 58+ built-in tools, 5 memory backends, multiple "
    "inference engine backends (Ollama, vLLM, SGLang, llama.cpp, Cloud), full MCP (Model Context "
    "Protocol) integration, and a comprehensive CLI with a web-based workstation UI. It is designed "
    "to run AI agents locally by default, calling cloud APIs only when query complexity warrants it, "
    "with per-query cost tracking and automatic fallback."
)

# === 2. SYSTEM ARCHITECTURE ===
pdf.section_title("2", "System Architecture")

pdf.subsection("2.1 Five-Primitive Architecture")
pdf.body(
    "The system is organized around five core abstractions that communicate through a thread-safe "
    "pub/sub EventBus defined in core/events.py. The primitives form a directed dependency graph "
    "that creates a feedback loop: agents produce traces, traces inform learning, learning improves "
    "routing, and better routing improves agent performance."
)

arch = (
    "  +----------------------------------------------------+\n"
    "  |                   LEARNING                          |\n"
    "  |        (Trace-driven routing & rewards)             |\n"
    "  +----------+----------+----------+-------------------+\n"
    "  |INTELLIGENCE|  ENGINE  | AGENTS  |      MEMORY        |\n"
    "  | Model     | Inference| Pluggable|  Persistent        |\n"
    "  | Catalog   | Backends | Agents   |  Searchable Storage |\n"
    "  +----------+----------+----------+-------------------+\n"
    "           |              |              |\n"
    "           +--------------+--------------+\n"
    "                          |\n"
    "                     [EventBus]\n"
    "                (Trace Collection)"
)
pdf.code_block(arch)

pdf.subsection("2.2 Registry Pattern")
pdf.body(
    "All extensible components use a decorator-based registry for runtime discovery. Registration "
    "happens at import time — no factory function or configuration file needs modification."
)
pdf.code_block(
    '@EngineRegistry.register("ollama")\nclass OllamaEngine(InferenceEngine):\n    ...'
)

pdf.body("Typed registries exist for:")
w = [60, 60, 70]
pdf.table_header(["Registry", "Type Parameter", "Purpose"], w)
rows = [
    ["ModelRegistry", "Any (ModelSpec)", "Model metadata"],
    ["EngineRegistry", "Type[InferenceEngine]", "Inference backends"],
    ["MemoryRegistry", "Type[MemoryBackend]", "Memory backends"],
    ["AgentRegistry", "Type[BaseAgent]", "Agent implementations"],
    ["ToolRegistry", "Any (BaseTool classes)", "Tool implementations"],
    ["ChannelRegistry", "Any (BaseChannel classes)", "Channel implementations"],
]
for i, r in enumerate(rows):
    pdf.table_row(r, w, fill=(i % 2 == 0))

pdf.subsection("2.3 Source Layout")
pdf.code_block(
    "src/nova_ai/\n"
    "    core/           Registry, types, config, events\n"
    "    intelligence/   Model catalog, router\n"
    "    engine/         Inference backends (Ollama, vLLM, Cloud, ...)\n"
    "    agents/         Agent implementations (8+ types)\n"
    "    tools/          Tool implementations (58+ tools)\n"
    "    memory/         Memory backends (SQLite, FAISS, ColBERT, ...)\n"
    "    learning/       Router policies, rewards, SkillForge\n"
    "    traces/         Trace store, collector, analyzer\n"
    "    telemetry/      Inference metrics, aggregation\n"
    "    server/         FastAPI HTTP server (OpenAI-compatible)\n"
    "    mcp/            MCP client/server/adapter\n"
    "    sandbox/        Docker/Podman agent sandbox\n"
    "    channels/       Messaging channel integrations\n"
    "    scheduler/      Cron/interval task scheduler\n"
    "    cli/            Click-based CLI commands\n"
    "    security/       Guardrails, scanning, audit"
)

# === 3. INFERENCE ENGINE LAYER ===
pdf.add_page()
pdf.section_title("3", "Inference Engine Layer")

pdf.subsection("3.1 Engine Interface")
pdf.body("All backends implement the InferenceEngine ABC with a uniform interface:")
pdf.code_block(
    "class InferenceEngine(ABC):\n"
    "    def generate(self, messages, *, model, **kwargs) -> dict: ...\n"
    "    def stream(self, messages, *, model, **kwargs) -> Iterator[str]: ...\n"
    "    def list_models(self) -> list[str]: ...\n"
    "    def health(self) -> bool: ..."
)

pdf.subsection("3.2 Backend Implementations")
w = [30, 25, 50, 85]
pdf.table_header(["Backend", "Type", "Technology", "Use Case"], w)
rows = [
    ["Ollama", "Local", "Native HTTP API", "Default local engine, broad model support"],
    ["vLLM", "Local", "OpenAI-compat API", "High-throughput serving with PagedAttention"],
    ["SGLang", "Local", "OpenAI-compat API", "Structured generation with constrained decoding"],
    ["llama.cpp", "Local", "OpenAI-compat API", "GGUF quantized models, CPU/GPU hybrid"],
    ["MLX", "Local", "OpenAI-compat API", "Apple Silicon optimized inference"],
    ["Cloud", "Cloud", "Provider SDKs", "OpenAI, Anthropic, Google Gemini, DeepSeek"],
]
for i, r in enumerate(rows):
    pdf.table_row(r, w, fill=(i % 2 == 0))

pdf.subsection("3.3 Smart Model Router")
pdf.body(
    "The MultiEngine accepts model='auto': the last user message is scored by score_complexity(), "
    "simple queries stay on the fastest local engine, and queries at or above the "
    "auto_route_threshold (default 0.55) escalate to the first available cloud model from "
    "cloud_model_preference (claude -> gpt -> gemini -> deepseek). When cloud is unreachable, "
    "complex queries fall back to local instead of failing."
)
pdf.body(
    "Per-query cost tracking: OpenRouter's reported per-request cost when present, otherwise an "
    "estimate from the pricing table. Local inference always costs $0.00. Cost flows through "
    "InstrumentedEngine into telemetry records and persisted Trace.total_cost_usd."
)

pdf.subsection("3.4 Engine Discovery")
pdf.body(
    "discover_engines() probes all registered backends for health at startup, returning healthy "
    "engines sorted with the user's configured default first. The system automatically falls back "
    "to any available engine if the preferred one is unavailable."
)

# === 4. AGENT FRAMEWORK ===
pdf.add_page()
pdf.section_title("4", "Agent Framework")

pdf.subsection("4.1 Class Hierarchy")
pdf.code_block(
    "BaseAgent (ABC)\n"
    "  +-- SimpleAgent              (single-turn, no tools)\n"
    "  +-- OpenHandsAgent           (wraps openhands-sdk)\n"
    "  +-- ClaudeCodeAgent          (Claude Agent SDK via Node.js)\n"
    "  +-- SandboxedAgent           (wraps any BaseAgent in Docker)\n"
    "  +-- ToolUsingAgent           (accepts tools, ToolExecutor)\n"
    "        +-- OrchestratorAgent  (multi-turn tool-calling loop)\n"
    "        +-- NativeReActAgent   (Thought-Action-Observation)\n"
    "        +-- NativeOpenHandsAgent (CodeAct code execution)\n"
    "        +-- RLMAgent           (recursive LM with REPL)\n"
    "        +-- OperativeAgent     (persistent scheduled agent)\n"
    "        +-- MonitorOperative   (long-horizon monitoring)"
)

pdf.subsection("4.2 BaseAgent Contract")
pdf.code_block(
    "class BaseAgent(ABC):\n"
    "    agent_id: str\n"
    "    accepts_tools: bool = False\n\n"
    "    def run(self, input: str, context: Optional[AgentContext] = None,\n"
    "            **kwargs) -> AgentResult: ..."
)

pdf.body("AgentContext provides: conversation history, tool names, memory results, metadata.")
pdf.body("AgentResult returns: content, tool_results, turns, metadata.")

pdf.subsection("4.3 OrchestratorAgent (Default)")
pdf.body(
    "The OrchestratorAgent is the primary/default agent served via nova serve. It implements a "
    "tool-calling loop in two modes:\n\n"
    "- function_calling (default): Uses OpenAI-format tool definitions. Parses tool_calls from "
    "engine response. Supports parallel tool execution via ThreadPoolExecutor.\n\n"
    "- structured: Uses THOUGHT/TOOL/INPUT/FINAL_ANSWER text protocol. This is the format used "
    "by SFT/GRPO training pipelines, making the Orchestrator a trainable agent type.\n\n"
    "Loop guard: degenerate-loop detection via SHA-256 hash tracking, ping-pong detection, "
    "per-tool budgets, context overflow recovery."
)

pdf.subsection("4.4 Tool-Calling Loop")
pdf.code_block(
    "1. Build messages + tool definitions (OpenAI format)\n"
    "2. Call engine.generate() with messages\n"
    "3. If response has tool_calls -> execute each tool via ToolExecutor\n"
    "4. Append tool results as TOOL messages\n"
    "5. If no tool_calls -> return final answer\n"
    "6. If max_turns exceeded -> return with warning\n"
    "7. Goto step 2"
)

# === 5. TOOL SYSTEM ===
pdf.add_page()
pdf.section_title("5", "Tool System")

pdf.subsection("5.1 BaseTool Interface")
pdf.code_block(
    "class BaseTool(ABC):\n"
    "    tool_id: str\n\n"
    "    @property\n"
    "    def spec(self) -> ToolSpec: ...\n\n"
    "    def execute(self, **params) -> ToolResult: ...\n\n"
    "    def to_openai_function(self) -> Dict[str, Any]: ..."
)

pdf.subsection("5.2 Tool Categories (58+ Tools)")
categories = [
    ("Web", "web_search, browser_navigate, browser_click, browser_type, browser_extract, browser_screenshot, http_request, web_readability"),
    ("Code", "code_interpreter, code_interpreter_docker, shell_exec, repl, code_scaffolder, docker_shell_exec"),
    ("Files", "file_read, file_write, apply_patch, git_tool, git_manager, file_converter"),
    ("Knowledge", "knowledge_search, knowledge_sql, scan_chunks, retrieval, memory_manage, memory_wiki_tools, storage_tools"),
    ("Media", "image_tool, audio_tool, text_to_speech, screen_capture, screen_monitor"),
    ("System", "system_monitor, scheduler_tool, canvas_tool, clipboard_ai, api_tester"),
    ("Data", "data_analyzer, db_query, pdf_tool, doc_generator"),
    ("Integration", "mcp_adapter, cisco_packet_tracer, skill_manage, user_profile_manage, approval_store, proactive_tools, channel_tools, digest_collect"),
]
for cat, tools in categories:
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(30, 6, cat + ":")
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(0, 6, tools)
    pdf.ln(1)

pdf.subsection("5.3 MCP Integration")
pdf.body(
    "Full Model Context Protocol (MCP) client/server implementation:\n"
    "- MCPClient connects to external MCP servers via transports\n"
    "- MCPToolAdapter wraps external tools as native BaseTool instances\n"
    "- MCPToolProvider dynamically discovers and registers MCP-hosted tools\n"
    "- Protocol version: 2025-03-26\n"
    "- MCP-discovered tools are seamlessly integrated into agents through ToolExecutor"
)

pdf.subsection("5.4 ToolExecutor")
pdf.body(
    "The ToolExecutor handles tool dispatch with:\n"
    "- JSON argument parsing from model output\n"
    "- Latency tracking per tool call\n"
    "- EventBus integration (TOOL_CALL_START / TOOL_CALL_END events)\n"
    "- OpenAI function-calling format conversion via get_openai_tools()"
)

# === 6. MEMORY & RETRIEVAL ===
pdf.add_page()
pdf.section_title("6", "Memory & Retrieval")

pdf.subsection("6.1 Memory Backend Interface")
pdf.code_block(
    "class MemoryBackend(ABC):\n"
    "    def store(self, document, metadata) -> str: ...\n"
    "    def retrieve(self, query, k=5) -> list[RetrievalResult]: ...\n"
    "    def delete(self, doc_id) -> bool: ...\n"
    "    def count(self) -> int: ..."
)

pdf.subsection("6.2 Backend Implementations")
w = [35, 155]
pdf.table_header(["Backend", "Description"], w)
rows = [
    ["SQLite/FTS5", "Zero-dependency default. Full-text search with FTS5. Good for quick start."],
    ["FAISS", "Dense vector retrieval via Facebook AI Similarity Search. Requires sentence-transformers."],
    ["ColBERTv2", "Late interaction retrieval. Higher precision than FAISS for complex queries."],
    ["BM25", "Classic Okapi BM25 term-frequency retrieval. Fast, no embeddings needed."],
    ["Hybrid", "Reciprocal Rank Fusion combining sparse (BM25) + dense (FAISS) results."],
]
for i, r in enumerate(rows):
    pdf.table_row(r, w, fill=(i % 2 == 0))

pdf.subsection("6.3 Ingestion Pipeline")
pdf.body(
    "Document ingestion follows a pipeline: file reading -> chunking (ChunkConfig) -> embedding "
    "generation (SentenceTransformerEmbedder) -> storage in the chosen backend. When "
    "agent.context_from_memory is enabled, relevant documents are retrieved and prepended to "
    "the prompt with source attribution."
)

pdf.subsection("6.4 Context Injection")
pdf.body(
    "The inject_context() function retrieves relevant chunks from the memory backend and prepends "
    "them to the agent's prompt. Each chunk includes source attribution (file path, chunk index) "
    "so the agent can cite its sources."
)

# === 7. LEARNING & TRACE SYSTEM ===
pdf.add_page()
pdf.section_title("7", "Learning & Trace System")

pdf.subsection("7.1 Trace Schema")
pdf.body(
    "Every agent interaction produces a Trace capturing the full sequence of steps — routing "
    "decisions, memory retrieval, inference calls, tool invocations, and final responses. Traces "
    "are persisted in SQLite via TraceStore."
)

pdf.subsection("7.2 Trace-Driven Learning")
pdf.body(
    "The TraceAnalyzer computes statistics from accumulated traces (latency, cost, tool usage, "
    "success rates). The TraceDrivenPolicy uses these statistics to learn which model/agent/tool "
    "combinations produce the best outcomes for different query types."
)

pdf.subsection("7.3 Router Policies")
w = [40, 150]
pdf.table_header(["Policy", "Description"], w)
rows = [
    ["HeuristicRouter", "Default. Scores query complexity, routes simple to local, complex to cloud."],
    ["TraceDrivenPolicy", "Learns from trace outcomes. Uses aggregated stats for routing decisions."],
    ["GRPORouterPolicy", "Group Relative Policy Optimization. Future RL-based routing."],
]
for i, r in enumerate(rows):
    pdf.table_row(r, w, fill=(i % 2 == 0))

pdf.subsection("7.4 SkillForge")
pdf.body(
    "SkillForge is the skill synthesis pipeline that auto-creates skills from repeated tool "
    "patterns:\n"
    "- Miner: discovers repeated tool-calling patterns from traces\n"
    "- Synthesizer: turns mined patterns into reusable skill manifests (TOML) via local LLM\n"
    "- Pipeline: end-to-end skill creation\n"
    "- Gauntlet: validation of synthesized skills\n"
    "- Store: persistent skill storage\n"
    "- Adoption: tracks skill usage and effectiveness"
)

pdf.subsection("7.5 Training Pipelines")
pdf.body(
    "NOVA AI includes training pipelines for improving the Orchestrator agent:\n"
    "- SFT (Supervised Fine-Tuning): trains on trace data\n"
    "- GRPO (Group Relative Policy Optimization): RL-based training\n"
    "- DPO (Direct Preference Optimization): preference-based training\n"
    "- LoRA (Low-Rank Adaptation): efficient fine-tuning\n"
    "- Data pipeline: trace -> training data preparation\n"
    "- Deploy: trained model deployment"
)

# === 8. SECURITY MODEL ===
pdf.add_page()
pdf.section_title("8", "Security Model")

pdf.subsection("8.1 Loop Guard")
pdf.body(
    "The LoopGuard detects degenerate tool-calling loops via:\n"
    "- SHA-256 hash tracking of consecutive states\n"
    "- Ping-pong detection (A -> B -> A -> B ...)\n"
    "- Per-tool call budgets\n"
    "- Context overflow recovery (4-stage compression)\n"
    "Both Python and Rust backends available."
)

pdf.subsection("8.2 Capability Policy / RBAC")
pdf.body(
    "Tools declare required_capabilities. Agents need matching permissions. The OperatorManager "
    "checks capability requirements before activation. Capability names are validated against the "
    "Capability enum so manifest typos surface as warnings."
)

pdf.subsection("8.3 Security Scanning")
pdf.body(
    "- SecretScanner: detects hardcoded API keys and secrets\n"
    "- PIIScanner: detects personally identifiable information\n"
    "- Boundary Guard: scans external tool arguments for security threats\n"
    "- SSRF Protection: web tools check for server-side request forgery\n"
    "- Taint Checking: tracks data provenance through tool pipelines\n"
    "- Redaction-before-cloud: scrubs secrets/PII before cloud transmission"
)

pdf.subsection("8.4 Budget Enforcement")
pdf.body(
    "Per-agent cost/token limits with automatic pause on exceed. Tracked via TelemetryStore. "
    "Per-operator rate limiting (rate_limit_rpm field). Failure circuit breaker with "
    "max_consecutive_failures."
)

# === 9. DEPLOYMENT ===
pdf.add_page()
pdf.section_title("9", "Deployment")

pdf.subsection("9.1 Windows Installer")
pdf.body(
    "Self-contained Inno Setup installer built from PyInstaller onedir bundle:\n"
    "- Per-user install to %LOCALAPPDATA%\\Programs\\NOVA AI\n"
    "- No uv, git, or Python required for end users\n"
    "- Start Menu + optional desktop shortcuts\n"
    "- Optional PATH integration\n"
    "- Proper uninstaller (preserves user data in ~/.nova_ai)"
)

pdf.subsection("9.2 Docker")
pdf.body(
    "Containerized deployment with docker-compose:\n"
    "- Dockerfile: multi-stage build with Python + Node.js\n"
    "- Dockerfile.gpu: NVIDIA GPU support\n"
    "- Dockerfile.sandbox: sandboxed agent execution\n"
    "- docker-compose.yml: full stack with Ollama sidecar"
)

pdf.subsection("9.3 Desktop Application")
pdf.body(
    "Tauri 2.x desktop app:\n"
    "- Native window with real-time status\n"
    "- Ollama integration for local model management\n"
    "- Model Hub with curated catalog and background installation\n"
    "- Auto-update via GitHub releases\n"
    "- Built-in chat UI with voice support"
)

pdf.subsection("9.4 Channel Integrations")
pdf.body(
    "Built-in channels (15+): Telegram, Discord, Slack, WhatsApp, Line, Viber, Messenger, "
    "Reddit, Mastodon, XMPP, Rocket.Chat, Zulip, Twitter/X, Twitch, Nostr, Twilio, Gmail. "
    "Each channel implements the BaseChannel ABC and registers via @ChannelRegistry.register()."
)

# === 10. PERFORMANCE BENCHMARKS ===
pdf.section_title("10", "Performance Benchmarks")

pdf.subsection("10.1 Benchmark Framework")
pdf.body(
    "The bench/ module provides a pluggable benchmarking framework:\n"
    "- LatencyBenchmark: per-call latency measurement\n"
    "- ThroughputBenchmark: tokens/second measurement\n"
    "- BenchmarkSuite: configurable test suites\n"
    "- All benchmarks register via @BenchmarkRegistry.register()"
)

pdf.subsection("10.2 Cost Tracking")
pdf.body(
    "Every cloud inference call tracks:\n"
    "- Per-query USD cost (from OpenRouter or pricing table estimate)\n"
    "- Token counts (input/output)\n"
    "- Latency (time to first token, total)\n"
    "- Local inference always costs $0.00\n"
    "Cost data flows through InstrumentedEngine into telemetry and trace stores."
)

pdf.subsection("10.3 Energy Monitoring")
pdf.body(
    "Energy monitoring via pynvml (NVIDIA), amdsmi (AMD), zeus-ml (Apple Silicon). "
    "Tracks GPU power consumption during inference for energy-aware routing."
)

# === OUTPUT ===
output_path = r"D:\My Softwares\Friday AI\NOVA AI\docs\proposal\NOVA_AI_Technical_Proposal.pdf"
pdf.output(output_path)
print(f"PDF saved to: {output_path}")

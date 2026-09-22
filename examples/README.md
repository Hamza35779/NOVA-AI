# Examples

Runnable, self-contained scripts showing how to build on the NOVA AI SDK. Each
subdirectory has its own README with prerequisites and usage.

## Prerequisites (all examples)

1. **NOVA AI installed** from the repo root:

   ```bash
   git clone https://github.com/Hamza35779/NOVA-AI.git
   cd NOVA-AI
   uv sync --extra dev          # or: pip install -e ".[server,tools-search]"
   ```

2. **An inference engine running.** Either:

   - **Ollama** (local, default): `ollama serve` and `ollama pull qwen3:8b`
   - **Cloud API**: export the relevant key (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …) and pass `--engine cloud --model gpt-4o`

3. Run from the repo root so `src/` is importable, e.g.:

   ```bash
   uv run python examples/deep_research/research.py "quantum computing advances 2026"
   ```

## Index

| Example | Agent | What it shows |
|---|---|---|
| [`browser_assistant/`](browser_assistant/) | `orchestrator` | Web browsing + search loop with cited answers |
| [`code_companion/`](code_companion/) | `native_react` | Code review, debugging, test generation from a git repo |
| [`daily_digest/`](daily_digest/) | `orchestrator` | Topic-based news briefing generation |
| [`deep_research/`](deep_research/) | `orchestrator` | Multi-hop research with memory + file output (recipe-driven) |
| [`doc_qa/`](doc_qa/) | SDK memory API | RAG over a directory of documents with citations |
| [`messaging_hub/`](messaging_hub/) | `orchestrator` | Inbox triage/reply/summary; Slack + WhatsApp channels |
| [`multi_model_router/`](multi_model_router/) | Learning pillar | Heuristic vs. bandit (Thompson Sampling) model routing |
| [`scheduled_ops/`](scheduled_ops/) | mixed | Cron-scheduled autonomous agents via `nova scheduler` |
| [`security_scanner/`](security_scanner/) | `native_react` | Secret/vulnerability scanning of a project directory |

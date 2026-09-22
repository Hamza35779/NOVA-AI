# Rust workspace — native `nova_ai_rust` extension

The native extension behind NOVA AI's performance-critical paths: the
`OptimizationStore` / storage backend used by the memory layer and some server
APIs. It is exposed to Python through PyO3 via `crates/nova_ai-python` and is
imported **only** through the single bridge module `src/nova_ai/_rust_bridge.py`.

## Prerequisites

- **Rust 1.90+** — the workspace pins its toolchain in [`rust-toolchain.toml`](rust-toolchain.toml), so rustup installs/selects it automatically when you build from this repo
- **Python 3.10–3.13** in the project venv (`.venv` at the repo root)
- **maturin** — included in the `dev` extra (`uv sync --extra dev`)

## Build

```bash
# From the repo root — builds and installs the extension into .venv
uv run maturin develop --manifest-path rust/crates/nova_ai-python/Cargo.toml

# Release build (faster at runtime, slower to compile)
uv run maturin develop --release --manifest-path rust/crates/nova_ai-python/Cargo.toml
```

Verify it loaded:

```bash
uv run python -c "import nova_ai_rust; print('ok')"
```

CI builds the same way (see the `test` job in `.github/workflows/ci.yml`).

## Crates

| Crate | Purpose |
|---|---|
| `nova_ai-python` | PyO3 entry point — exposes ~50 Rust classes as the `nova_ai_rust` module |
| `nova_ai-core` | Foundation types, registry, config, and event bus |
| `nova_ai-agents` | Pluggable agent logic for queries, tool calls, memory (incl. loop guards) |
| `nova_ai-engine` | LLM runtime management — `InferenceEngine` trait + backends (Ollama, …) |
| `nova_ai-tools` | `BaseTool` trait, `ToolExecutor`, built-in tools, storage backends |
| `nova_ai-skills` | Skill manifests, execution results, and signature verification |
| `nova_ai-mcp` | MCP — JSON-RPC server/client for tool exposure |
| `nova_ai-a2a` | Google Agent-to-Agent protocol types and in-memory task store |
| `nova_ai-scheduler` | Cron / interval / one-shot task scheduling backed by SQLite |
| `nova_ai-sessions` | Cross-channel persistent session management |
| `nova_ai-templates` | Pre-configured agent templates loaded from TOML |
| `nova_ai-recipes` | Composable TOML configs that wire all five primitives |
| `nova_ai-workflow` | DAG-based workflow graph, builder, and execution planner |
| `nova_ai-learning` | Router policies, bandits, GRPO, trace-driven learning |
| `nova_ai-security` | Scanners, RBAC, taint tracking, audit, SSRF protection |
| `nova_ai-telemetry` | `InstrumentedEngine`, `TelemetryStore`, energy monitoring |
| `nova_ai-traces` | Full interaction-level recording and analysis |

## Conventions

- Toolchain: pinned via `rust-toolchain.toml` (1.90, with rustfmt + clippy). The workspace requires ≥ 1.88 for let-chains and `is_multiple_of`; fresh resolution currently needs 1.90.
- There is no committed `Cargo.lock` — fresh resolution picks transitive deps by their MSRV, which is why the pin exists.
- Check with `cargo clippy --workspace` and format with `cargo fmt --all` before committing; pre-commit runs these.

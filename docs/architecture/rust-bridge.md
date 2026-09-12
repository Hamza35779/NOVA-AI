# Rust bridge matrix — crate × capability × Python fallback × bench

> Priority per forensic §23: don't port everything. Rank by profile:
> tokenizer/chunker → embedding batching → rerank → telemetry aggregator.

| Crate | Capability (PyO3 classes) | Python fallback | Used in prod? | Priority |
|---|---|---|---|---|
| `nova_ai-security` | `GuardrailsEngine`, `CapabilityPolicy`, `AuditLogger`, `InjectionScanner` | `security/` pure-python | ✅ real (tools path) | P0 keep |
| `nova_ai-tools` | `CalculatorTool`, `FileRead/WriteTool`, `HttpRequestTool`, `ShellExecTool` | `tools/*.py` | ✅ real | P0 keep |
| `nova_ai-core` | `EventBus`, `Config`, loop guard | `core/events.py` | ✅ real | P0 keep |
| `nova_ai-telemetry` | aggregator, `FlopsEstimator` | `telemetry/` | ✅ real | P1 (batch it) |
| `nova_ai-engine` | tokenizer/chunker stubs | `engine/` | ⚠ partial | P1 (top port: chunker) |
| `nova_ai-sessions` / `traces` / `skills` / `templates` / `workflow` | storage twins | `sessions/`, `traces/store.py` | ⚠ unused twins | P2 gate behind feature |
| `nova_ai-agents` / `scheduler` / `learning` / `mcp` / `a2a` / `recipes` | agent/scheduler twins | `agents/hybrid/*` | ❌ zero prod callers | P2 gate or delete |

Rules:
- Keep Python fallback tested in CI (`NOVA_NO_RUST=1 pytest`).
- New Rust ports need a bench in `tests/bench/` proving speedup before merge.
- Pure-proxy Tauri `fetch_*` commands should be deleted (use `api.ts` directly).

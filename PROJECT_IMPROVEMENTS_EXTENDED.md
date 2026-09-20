# NOVA AI — Extended Suggestions & Improvements (Part 2)

**Date:** 2026-09-12
**Companion to:** `PROJECT_REVIEW_AND_IMPROVEMENTS.md` (P0/P1/P2 fixes)
**Focus here:** *new* value-add ideas — not repeating the first report. All scoped to what exists today: `src/nova_ai/{agents,engine,memory,connectors,channels,tools,server,telemetry,recipes,intelligence,operators,sandbox,speech}/`, `frontend/` (React 19 + Vite 6 + PWA + Tauri 2), `docs/development/roadmap.md` 6 workstreams.

How to use: pick one section per sprint. Each item has **Why → What → Smallest shippable fixture**.

---

## 1. Onboarding: from “clone + pray” to 5-minute wow

**Why:** Setup has 4+ paths (EXE, start.bat/sh, Docker, source) + model choice + Node 20+ + Ollama/vLLM. First-run dropoff is the #1 killer.

1. **`nova init --preset` wizard**
   - `chat-simple` / `code-assistant` / `deep-research` / `morning-digest` already exist in `configs/examples/`. Wire them: `nova init --preset code-assistant --engine ollama --model qwen3:8b` writes `~/.nova_ai/config.toml`, pulls model, runs `router test` + `doctor --check-all`.
   - Fixture: add `cli/init_cmd.py::preset_manifests = {"chat-simple": {...model, tools:[], memory:"faiss"}}` + e2e test per preset.

2. **`nova doctor --fix --bundle`**
   - Extend existing `doctor` to check: Python 3.10-3.13, Node >=20, Ollama reachable, model present, port 8000 free, `~/.nova_ai/` writable, keyring available. `--fix` pulls model / kills stale pid / creates dirs. `--bundle` zips redacted logs via existing `CredentialStripper` for GitHub issues.
   - Fixture: `doctor --json > doctor.json` consumed by frontend Onboarding page progress checklist.

3. **Frontend Onboarding page (`/onboarding`)**
   - 4 steps: Engine → Model → Quick test chat → Shortcuts (`Alt+Space`). Store `onboarded=true` in zustand + localStorage. Deep-link from Tauri tray “Setup”.
   - Empty states everywhere else: Interact tab with no model → CTA button “Pull qwen3:8b”, not blank screen.

4. **Sample data seeder**
   - `nova demo --seed` creates 1 operator + 1 memory entry + 1 digest + 1 trace so Dashboard/Build Diagnostics aren’t empty on first run. Demo mode flag `NOVA_DEMO=1`.

## 2. Frontend UX that feels pro (cheap wins)

**Current:** `vite.config.ts` PWA + manualChunks good, proxy `/v1,/health,/api` good, but: 1 test, no eslint, no i18n, no virtualized lists, charts untested.

5. **Streaming + optimistic UX contract**
   - Standardize SSE events: `token | tool_start | tool_end | done | error` with `request_id`. `lib/sse.ts` retry with backoff + resume via `Last-Event-ID`. Show tool progress chips (already in daemon replies) + cancel button (AbortController → `POST /v1/cancel {request_id}`).
   - Fixture: `types/events.ts: type AgentEvent = {request_id, seq, kind, ...}` + `useAgentEvents(request_id)` hook test with mocked EventSource.

6. **Performance budget**
   - `manualChunks` already splits react/markdown/charts/router — add `light` + `katex` chunks (katex is heavy, only needed on math pages), `recharts` lazy via `React.lazy()`. Add `vite-plugin-compression` + bundle guard in CI: `npm run build && du -sh ../src/nova_ai/server/static` fail if >8 MB gzip.
   - Long chat lists: `virtua` or `tanstack-virtual`, markdown memo (`React.memo` + `remark` cache), `recharts` downsample to 200 pts.

7. **A11y + keyboard + i18n**
   - Shortcuts: `Ctrl+K` command palette (chat/new digest/dev-watch/runs), `Ctrl+/` shortcuts modal, `/` focus input, `Esc` close popup (already). Focus trap in Quick Capture, `aria-live` for streaming tokens, contrast check on `#0F0B1E` theme.
   - i18n: `i18next` + `en` + `pt` (you asked in Portuguese!) + `es`. Start with `src/i18n/*.json` for nav/onboarding/errors only — full chat content stays as-is.
   - Fixture: `frontend/src/i18n/en.json: {"onboarding.engine":"Choose engine", ...}`.

8. **PWA offline + Tauri parity**
   - `VitePWA navigateFallbackDenylist` already excludes `/v1,/health,/dashboard,/api` — good. Add: cached shell + queued “send when back online” outbox (`localStorage outbox[]` → flush on `navigator.onLine`). Tauri updater already in deps (`plugin-updater`) — wire `docs/desktop-auto-update.md` checklist into release CI + add “Check for updates” menu.

9. **Dashboard v2 (uses what you already collect)**
   - You persist `Trace.total_cost_usd`, telemetry latency/energy, devwatch 50-run ring. Surface: per-model cost/latency/energy cards, per-tool success rate, digest history, operator health timeline. Persist devwatch to SQLite (roadmap “Ready” item) so charts survive restart.
   - Fixture: `GET /api/stats/summary?days=7 → {cost_usd, tokens, p50_latency_ms, wh, by_model[], by_tool[]}` + `pages/Dashboard.tsx` recharts.

## 3. Backend architecture: make scale boring

10. **API versioning + pagination + idempotency**
    - Prefix new routes `/v2/` (keep `/v1` OpenAI-compat frozen). All list endpoints: `?limit&cursor` + `X-Request-ID` echo. Mutating tool/operator runs accept `Idempotency-Key` header → dedupe in `traces/store.py`.
    - Fixture: `server/pagination.py: def paginate(q, limit, cursor)` + middleware `request_id`.

11. **Background jobs > in-request work**
    - Digest, deep-research, index, evals should enqueue (`scheduler/` + `daemon/`) returning `202 {job_id}`, frontend polls/subscribes. Prevents proxy timeouts + enables retry. Add `GET /api/jobs/{id}` + SSE `job_progress`.
    - Retry policy: exponential backoff + `max_consecutive_failures` circuit breaker pattern already in operators — generalize to `core/retry.py`.

12. **Plugin SDK (roadmap “Plugin ecosystem”)**
    - Formalize what `tools/` + `agents/` + `engine/` already do ad-hoc: `nova plugin new --kind tool|agent|engine` scaffolds `pyproject.toml [project.entry-points."nova_ai.tools"]` + `BaseTool` subclass + tests. Registry: `nova registry search|install tool-weather`.
    - Fixture: `recipes/composer.py` becomes `nova compose up recipe.yaml` (multi-operator recipes) with JSON-schema validation.

13. **Event-driven operators (roadmap Design Needed)**
    - Today: cron/interval ticks. Add `on: {event: "channel.message" | "file.indexed" | "memory.updated", filter: {...}}` to operator manifest, subscribed via existing `core/EventBus`. First use: “summarize every starred Slack thread” without polling.
    - Chaining: `needs: [operator-a]` + `pass: {digest_path}` semantics; visualize DAG in Dashboard.

14. **Operator versioning & safe rollout**
    - `manifest.version`, `nova operators deploy v2 --canary 10%`, auto-rollback on `max_consecutive_failures`. Store per-version traces so `learning/` can A/B prompts. This unblocks “self-improving operators” research item.

15. **Migrations + backups**
    - `nova backup create|restore ~/.nova_ai/backups/2026-09-12.zip` (config + sqlite + memory index + credentials ref, secrets redacted). `nova migrate --check` for config schema bumps (`configs/schema.json` from Part 1). Document restore in `docs/deployment/`.

## 4. AI quality: router, memory, evals, guardrails

16. **Router that learns (roadmap Workstream 3 + 1)**
    - Today: `score_complexity` heuristic + threshold. Next: log `(features, engine, latency, cost, thumb_up/down)` → nightly Thompson-sampling bandit (`learning/` already has DSPy/GEPA) producing `router_policy.json`. Dashboard shows “why this model?” (`rule` vs `learned`, confidence).
    - Minions sequential first (local summarize → cloud reason) before parallel/speculative — smaller surface, matches redaction pipeline already shipped.

17. **Memory lifecycle (federated memory prep)**
    - Add: `memory consolidate` (dedupe + merge), `memory forget <id|query>` (GDPR), `memory export|import`, TTL + provenance (`source: chat|digest|connector`). Sync stub: `memory sync --target ./peer` (file-based CRDT-ish, later network). Surface memory-wiki graph in frontend.
    - Fixture: `memory entry {id, text, embedding, source, created_at, expires_at, taint:Set}` — taint already exists for cloud boundary, reuse.

18. **Eval harness expansion (your moat)**
    - Nightly `nova eval --suite core --publish docs/evals/leaderboard.md` (accuracy + p50 + $/1k + Wh) — embodies “energy first-class”. Add regression gate: fail PR if `Δaccuracy < -2%` or `Δcost > +15%` on pinned suite.
    - Red-team suite: prompt-injection, jailbreak, PII-leak, tool-abuse cases → `GuardrailsEngine` score. Use `bench/` + `evals/` backends already present.

19. **RAG hybrid that’s measurable**
    - `faiss + bm25 + colbert/rerank` already in deps. Ship `nova bench rag --corpus docs/` comparing `bm25-only vs dense-only vs hybrid` with recall@k + latency, then set hybrid default + show citations in chat (`[1][2]` → sources drawer). This makes deep-research trustworthy.

20. **Voice loop that ships (roadmap Research-Stage)**
    - `speech/` + `voice/` + faster-whisper/sounddevice already vendored. MVP: push-to-talk in desktop (`nova voice --push-to-talk` exists) → stream transcript → agent → TTS reply + waveform. Phone channels later. Add `docs/tutorials/voice-mode.md`.

## 5. Performance & cost: faster + cheaper on same hardware

21. **Cold-start + import diet**
    - `litellm 1.100.0` 9s import tax noted. Lazy-import `litellm/vllm/transformers/faiss` inside engine constructors, add `nova --profile-imports` (python `-X importtime`) CI check. Target: `nova --help <400ms`, `nova chat` first token local <2s warm.
    - Quant presets: `q4_k_m` default, `q8_0` quality, `q2_k` low-RAM with `nova model recommend --ram 8GB` table.

22. **Caching everywhere (safe)**
    - Prompt cache (exact prefix) + embedding cache (sqlite) + tool cache (`web_search` 1h, `arxiv` 24h) with `Cache-Key` + `Cache-Control: no-store` escape for tainted/secret data. Show “cached” badge + saved $/ms in footer (telemetry already flows there).

23. **Rust acceleration priorities**
    - Don’t port everything. Rank by profile: tokenizer/chunker → embedding batching → rerank → telemetry aggregator. Publish `docs/architecture/rust-bridge.md` matrix (crate × hit rate × speedup) so contributors know where Rust actually helps. Keep Python fallback tested in CI (`NOVA_NO_RUST=1 pytest`).

## 6. Reliability & observability

24. **Structured logs + OpenTelemetry**
    - `structlog` JSON logs (`request_id, operator, engine, model, cost_usd, latency_ms`) → OTLP to local Jaeger/PostHog (posthog already dep). `Trace` already has cost; add `span_id` propagation CLI→server→engine→tool. `docs/telemetry.md` documents PII redaction (reuse `analytics/redaction.py`).

25. **Health that means something**
    - `GET /healthz` (liveness) + `GET /readyz` (ollama + model + db + disk) for Docker/K8s/systemd. Frontend status dot + `nova status --watch`. Add synthetic probe: `nova probe --every 60s` sends “ping” chat, alerts on fail (feeds operator health workstream).

26. **Failure injection + chaos (small)**
    - `NOVA_CHAOS="engine.flaky:0.2,tool.timeout:0.1"` in dev to prove retries/circuit breakers/fallbacks. One `tests/test_chaos_fallback.py` is worth 10 happy-path tests.

## 7. Security & privacy (beyond Part 1)

27. **Permissions UX people understand**
    - Per-tool consent: first use of `shell_exec/http_request/code_interpreter` prompts “Allow once / Always for this project / Deny” (Tauri dialog + CLI confirm). Persist in `capability_policy` (today defaults to None). Show lock icon + policy in chat footer.

28. **SBOM + signed releases**
    - `uv export --format cyclonedx → sbom.json` + `npm sbom` per release, attach to GitHub release. Sign Windows EXE + Tauri bundles (roadmap auto-update doc exists — finish it). Add `docs/security/threat-model.md` (assets: local files, creds, cloud keys; boundaries: tool sandbox, redaction-before-cloud, TEE roadmap).

29. **Data retention controls**
    - `nova privacy --retention 30d --purge-traces --no-telemetry` + per-connector scopes (`gmail.readonly`, not full). Surface in onboarding + settings page. Needed before federated memory / cloud collaboration.

## 8. DX & community flywheel

30. **Devcontainers + `just` tasks**
    - `.devcontainer/{devcontainer.json,Dockerfile}` (Python 3.13 + Node 22 + Ollama stub) + `just init|dev|test|bench|docs` wrapper over `uv/pytest/npm`. Contributors on Windows/WSL2/macOS get identical env. Fixes “works on my box” + space-path issues.

31. **Showcase + templates gallery**
    - `docs/showcase/*` exists (memory, digest, discord, cost, coding). Add: 30-sec GIFs, `examples/{coding-assistant,research-operator,discord-companion}/` one-click `nova compose up`, “Deploy to …” buttons. Best growth lever for plugin ecosystem.

32. **Notebook + video pipeline (roadmap Workstream 4)**
    - `notebooks/{router-tuning,rag-bench,memory-wiki}.ipynb` executed in CI (`jupyter nbconvert --execute`) so they never rot. Video scripts live next to written tutorials (roadmap already says this — enforce via `docs/tutorials/_template.md`).

33. **Good-first-issue factory**
    - From roadmap: AMD iGPU detect, GPU_SPECS rows, devwatch SQLite, custom-tool tutorial, per-platform guides. Label `good-first-issue` + `effort:S` + provide `tests/` stub + expected output. Auto-assign on “take” (already documented — add bot).

## 9. Suggested build order (next 30/60/90 days)

**30 days — activation + trust:**
`init --preset` + `doctor --fix` + onboarding page + seeder → SSE contract + cancel → `/readyz` + `backup` → router “why this model?” label → leaderboard nightly.

**60 days — quality + perf:**
Hybrid RAG default + citations → memory consolidate/forget/TTL → plugin scaffold + registry search → devwatch SQLite + Dashboard v2 → import diet + caches + bundle guard → OTel spans.

**90 days — autonomy + moat:**
Event-driven + chained + versioned operators → Minions sequential → red-team suite gate → Rust top-1 port + bench → signed auto-updates + SBOM → notebooks + showcase gallery.

---

## 10. Concrete next-file fixtures (copy-paste starters)

**`src/nova_ai/core/retry.py`:**
```python
from dataclasses import dataclass
import random, time
@dataclass
class RetryPolicy:
    attempts: int = 3; base_ms: int = 200; factor: float = 2.0; jitter_ms: int = 50
def run_with_retry(fn, policy=RetryPolicy(), retry_on=(Exception,)):
    for i in range(policy.attempts):
        try: return fn()
        except retry_on:
            if i == policy.attempts - 1: raise
            time.sleep(policy.base_ms/1000 * policy.factor**i + random.uniform(0, policy.jitter_ms/1000))
```

**`server/pagination.py`:**
```python
def paginate(items: list, limit: int = 50, cursor: str | None = None):
    start = int(cursor or 0); page = items[start:start+limit]
    next_cursor = str(start+limit) if start+limit < len(items) else None
    return {"items": page, "next_cursor": next_cursor}
```

**`frontend/src/types/events.ts`:**
```ts
export type AgentEvent =
 | { kind:"token"; request_id:string; seq:number; delta:string }
 | { kind:"tool_start"; request_id:string; seq:number; tool:string }
 | { kind:"tool_end"; request_id:string; seq:number; tool:string; ok:boolean }
 | { kind:"done"; request_id:string; seq:number; cost_usd:number }
 | { kind:"error"; request_id:string; seq:number; message:string };
```

**`justfile` (DX):**
```make
init: ; uv sync --extra dev; cd frontend && npm ci
dev: ; nova serve & cd frontend && npm run dev
test: ; pytest -m "not live and not cloud and not hub and not slow" -q; cd frontend && npm run test -- --coverage
```

---

*Part 2 — net-new ideas only. Pair with Part 1 P0 fixes first; then pick one 30-day track. Suggested commit: `docs: add extended improvements part 2`.*

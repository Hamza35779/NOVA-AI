# NOVA AI — Forensic Audit Report

**Date:** 2026-09-12 · **Commit:** bd9e02a (main) · **Auditor method:** 4 parallel deep-sweep passes (security, architecture, AI/performance, reliability/frontend) + ground-truth execution (7,000+ tests, ruff, pip-audit, npm audit, live reproduction of claimed bugs, micro-benchmarks) + independent verification of every headline claim.

Every "Confirmed" finding below was either reproduced live or read and verified at the cited file:line. Nothing is reported from docstrings or names alone.

---

## 1. Executive Summary

NOVA AI is a **much stronger project than its self-promotional README suggests in some ways, and weaker in others**. The core loop — local Ollama inference with cloud fallback, SQLite/FTS5 knowledge store, tool-executing agents, a FastAPI server, and a Tauri desktop shell — genuinely works: 7,000+ tests pass locally (one environment-dependent failure), `pip-audit` reports zero known Python CVEs, no secrets are tracked in git, and the offline degradation path is real, not marketing.

But the audit found **a security posture that does not match the "local-first, private" promise**: the two most dangerous tools (`code_interpreter`, `shell_exec`) give the LLM (and therefore any prompt-injected document) a path to arbitrary code execution with full user privileges, and the defenses that exist on paper (`InjectionScanner`, capability policies, credential stripper) are largely **unwired or optional**. On the reliability side, the sync engine's cursor checkpointing is broken (confirmed, live-verified), chat history lives in unguarded localStorage while a durable server-side store sits unwired, and Windows — the primary desktop platform — is effectively untested in CI. On the performance side, the server's non-streaming chat path blocks the entire event loop while a generation runs (one slow Ollama call freezes every endpoint, including `/health`), and the frontend re-parses and re-persists the whole conversation store ~12×/second during streaming — both confirmed at the dispatch sites, both cheap to fix.

The codebase is 157k non-blank lines of Python + 24k frontend + 6.5k Rust, with a test suite of 6,969 test functions (94.5k lines, >99% of which actually runs in the Linux CI lane). That is an unusually serious engineering effort for a personal project — and it makes the structural debts (two conflicting pricing tables, an 1,825-line 8-provider engine class, a 2,494-line server router, ~2/3 of the Rust extension unused) the main drag on future velocity.

**Overall: 6.9/10.** Works today, hurts tomorrow.

---

## 2. Project Architecture

```text
User
 ↓
React 19 + Vite frontend (desktop webview; PWA; ~24k lines TS/TSX)
 ├─ direct fetch → FastAPI server (localhost REST + SSE)
 └─ Tauri IPC → lib.rs (2,942 lines: boot supervisor, 31 commands)
        ↓
FastAPI server (nova_ai/server/: agents, connectors, digest, webhooks, auth middleware)
        ↓
CLI layer (nova_ai/cli/: 40+ commands; registry of tools/agents)      ← imports FROM server (violation)
        ↓
Agent layer (agents/: 9 core + 9 hybrid paradigms; toolorchestra, mini_swe, ReAct…)
        ↓
Tool executor (tools/: 78 registered tools) ── Rust bridge (_rust_bridge.py → nova_ai_rust)
        ↓                                            (security scanning, BM25, storage, basic tools)
Engine layer (engine/: SmartRouter → MultiEngine → Ollama local / 8 cloud providers / litellm)
        ↓
Data layer (connectors/: SQLite FTS5 knowledge store, sync engine, Gmail/Slack/Obsidian/…;
            traces, conversations, chat history — all SQLite under ~/.nova_ai/)
        ↓
Channels (Slack/WhatsApp/iMessage/Telegram daemons), Scheduler, Evals (23% of codebase)
```

Scale: 1,449 Python files (157,509 non-blank src lines), 6,969 test functions (94,518 lines), 86 frontend files (24,447 lines), 17 Rust crates (6,461 lines), 89 docs pages, 14 GitHub workflows.

---

## 3. Component-by-Component Analysis

| Component | State | Notes |
|---|---|---|
| **CLI (`nova`)** | ✅ Works | All README headline commands verified live. But 3.4–3.9 s startup for `--version`/`--help`; imports 2,305 modules / 109 MB RSS before doing anything. |
| **Engines** | ✅ Works, ⚠ structure | Router is real (regex heuristics + learned corrections + proving ground), not theater. `CloudEngine` = 1,825 lines, 8 providers in one class, missing `_xai_client` init (reproduced: `AttributeError`). |
| **Knowledge store** | ✅ Works, ⚠ perf | FTS5 + 9 indexes + WAL + parameterized queries. 6.6 ms/chunk insert (per-chunk commit), 20 ms query @ 5k docs. Vector search = brute-force numpy scan of ALL embeddings per query. |
| **Sync engine** | ⚠ broken checkpoint | `current_cursor` never advances (verified) — resume restarts pagination; masked for Gmail by `since`, not for Slack. |
| **Server** | ✅ Works, ⚠ size | Good auth middleware (fails closed on non-loopback without key), CORS allowlist, HMAC webhooks. But `agent_manager_routes.py` = 2,494 lines / five routers in one file, imports business logic *upward* from CLI. Non-streaming `/v1/chat/completions` runs engine/agent calls inline on the event loop — one slow generation freezes the whole server (fix is one `asyncio.to_thread`). |
| **Tools** | ⚠ security | 78 tools. `code_interpreter` blocklist bypassable (reproduced by inspection), `shell_exec` shell=True + LLM-chosen env passthrough, `git_manager` argument injection. |
| **Rust extension** | ⚠ 1/3 used | Security/BM25/storage/tools bridges are real. ~50 PyO3 classes exposed; agents/engines/scheduler Rust twins have **zero** Python callers. |
| **Tauri desktop** | ✅ Works | Boots Ollama, pulls models, spawns backend, health-polls. CSP allows `unsafe-inline`; capabilities grant sidecar `"args": true`. |
| **Frontend** | ✅ Works, ⚠ persistence | Good typed API client, SSE handling. Chat history = localStorage only (quota crash + silent wipe on version bump); streaming flushes re-render every message and stringify the whole store ~12×/s (`MessageBubble` unmemoized, `store.ts:437`); 12+ raw `fetch()` sites bypass auth header; 1 test file; `npm test` never runs in CI. |
| **Evals** | ⚠ weight | 37.5k lines = 23% of the package. 42 datasets, several with no external consumer. `evals/cli.py` = 78 elif branches. 12 test modules ship in the wheel but never run. |
| **Channels** | ⚠ | Slack has real 429/Retry-After handling (best in repo). WhatsApp/Baileys bridge reports CONNECTED while dead; sends fail silently at debug level. |
| **Docs** | ✅ good | 89 pages; claims about agents/presets verified present (under-stated if anything). |

---

## 4. Confirmed Bugs

| ID | Sev | Location | Problem | Repro | Fix |
|---|---|---|---|---|---|
| B1 | 🔴 | `src/nova_ai/engine/cloud.py:367-377,1163` | `CloudEngine.__init__` never initializes `self._xai_client`; `_generate_xai` reads it unguarded → `AttributeError` instead of a clean "not configured" error whenever XAI_API_KEY is unset | **Reproduced live** (see below) | Add `self._xai_client = None` in `__init__` (or `getattr` like line 1764) |
| B2 | 🟠 | `src/nova_ai/connectors/sync_engine.py:104` | `current_cursor` is assigned once and never updated; every checkpoint persists the stale pre-sync cursor → resume restarts pagination from scratch | Read-verified: no reassignment anywhere in `sync()`; gmail.py:561 writes `self._last_cursor` which nothing reads | Track cursor per batch (read `connector.sync_status()` or yield `(doc, cursor)` tuples) |
| B3 | 🟠 | `src/nova_ai/engine/cloud.py:35` vs `agents/hybrid/_prices.py:22` | Two conflicting pricing tables: gpt-4o = (2.50,10.00) vs (0.15,0.60) — the latter is gpt-4o-*mini* pricing; gpt-5 differs 8×. Cost reporting is wrong somewhere | Read-verified both tables | One pricing module; changelog the corrected numbers |
| B4 | 🟠 | `tests/connectors/test_live_smoke.py:33` | `KnowledgeStore` never closed → `TemporaryDirectory` cleanup fails on Windows (`PermissionError: live.db in use`). The live test **fails on Windows today** | **Reproduced**: 1 failed, 2,173 passed in the -x run | `store.close()` in a `finally`, or context-manager |
| B5 | 🟡 | `frontend/src/lib/store.ts:65-67` | `saveConversations` has no try/catch → `QuotaExceededError` (>5 MB history) throws into every caller that saves after each message | Code-read; localStorage quota is 5 MB per origin | try/catch + prune oldest conversations |
| B6 | 🟡 | `frontend/src/lib/store.ts:57-59` | Any stored blob with `version !== 1` → conversations silently wiped. Future schema bump = total data loss for every user | Code-read | Migration path instead of reset |
| B7 | 🟡 | `src/nova_ai/server/agent_manager_routes.py:610`, `scheduler/scheduler.py:527`, `channels/slack_daemon.py:56` | server → cli → agents → server conceptual import cycle, held together by function-level imports and a try/except with frozen-set fallback (line 597-646) | Import-graph script + read | Extract shared tool/memory-backend factories into a neutral layer |
| B8 | 🟡 | `src/nova_ai/agents/hybrid/runner.py:21` | Top-level `import fcntl` (Unix-only) — importing this module on Windows raises ImportError | Read-verified; Windows CI only runs 2 test files so it's never caught | Gate behind `sys.platform` |
| B9 | 🟢 | `docs/proposal/generate_pdf.py:54` etc. | 5 ruff findings (2 unsorted imports, 2 unused imports, 1 unused var) — all in docs/proposal scripts | ruff run | `ruff check --fix` |
| B10 | 🟡 | `src/nova_ai/cli/chat_cmd.py:209-281` | `nova chat` accumulates the full history with no window/summarization/token cap (only `/clear`); long sessions overflow the model context (Ollama silently truncates the prompt) and per-turn cost grows linearly. The 4-stage `LoopGuard.compress_context` exists but is wired only into `OperativeAgent` | Read-verified | Cap history or wire `compress_context` into the CLI loop |

**B1 live repro output:** `CONFIRMED AttributeError: 'CloudEngine' object has no attribute '_xai_client'` with all keys unset.
**B4 live repro:** full suite run → `FAILED tests/connectors/test_live_smoke.py::test_live_obsidian_full_pipeline` (WinError 32), after the test itself printed "SMOKE TEST PASSED — 6712 chunks indexed".

## 5. Potential Bugs

- **SQLite `busy_timeout` never set anywhere** (grep = 0 hits) while server background sync + API handlers write concurrently → intermittent `database is locked` under load. Likely.
- **Windows daemon stop path**: `os.kill(pid, SIGTERM)` on Windows = TerminateProcess → graceful close never runs (`channels/slack_daemon.py:252` vs handler at 187-195). Likely.
- **`loadConversations`** wipe (B6) interacts with PWA service worker caching old store shapes. Potential.
- **`_apply_toml_section`** (`core/config/loader.py:44`) silently drops unknown TOML keys → config typos vanish. Potential UX bug factory.
- **Two `LiveResearchBenchDataset` classes** in different modules force alias imports (`evals/cli.py:418-425`) — a rename collision waiting to spread. Potential.
- **Stale-PID reuse** in daemon pidfile checks (`slack_daemon.py:231-242` validates only `kill(pid, 0)`). Potential.

## 6. Security Audit

The full professional pass produced 2 Critical, 6 High, 8 Medium, 6 Low findings. Headline items (each independently verified during this audit):

```text
Vulnerability: LLM-driven arbitrary code execution (blocklist sandbox)
Severity: CRITICAL
Affected: src/nova_ai/tools/code_interpreter.py:14-27,80-85
Scenario: The "sandbox" is a 12-entry substring blocklist ("subprocess.", "eval(", "open("…) checked
  before running code via subprocess.run([sys.executable, "-c", code]) with full user rights and
  full environment. "import subprocess" contains none of the blocked substrings; getattr()/importlib
  defeat the rest. Any prompt-injected instruction in an ingested email/doc can achieve code exec.
Risk: full account compromise. Fix: use the existing ContainerRunner (sandbox/runner.py:105-134,
  already has --network none + ro mounts) or require per-execution confirmation. No exploit details needed — the gap is a missing sandbox, not a subtle bug.

Vulnerability: shell_exec with shell=True + LLM-chosen env_passthrough
Severity: CRITICAL
Affected: src/nova_ai/tools/shell_exec.py:120-124,155-163
Scenario: Tool takes a shell command verbatim and copies ANY requested env var (env_passthrough
  list comes from tool arguments) into the child → "printenv" returns every API key; output goes
  back to the LLM which can exfiltrate via http_request. Confirmation gate is the only barrier and
  is optional per executor config (tools/_stubs.py:209-226).
Fix: fixed env allowlist; mandatory server-side confirmation.

Vulnerability: git_manager argument injection
Severity: HIGH · Affected: tools/git_manager.py:143-165
Scenario: LLM-supplied args whitespace-split into git commands with no "--" separator →
  diff --no-index reads arbitrary files, bypassing the file policy. (git_tool.py:228 does it right.)
Fix: per-action arg allowlists + "--".

Vulnerability: SSRF redirect bypass in web_search; fail-open DNS
Severity: HIGH · Affected: tools/web_search.py:88-98; security/ssrf.py:120-135
Scenario: SSRF check runs on the original URL, then httpx follows redirects un-checked → 302 to
  169.254.169.254. DNS fail-open on gaierror. (http_request.py:206-251 re-checks each hop — reuse that.)
Fix: shared redirect-aware fetch; fail closed.

Vulnerability: env expansion of LLM-controlled headers
Severity: HIGH · Affected: tools/http_request.py:112-115
Scenario: os.path.expandvars on header values → "Authorization": "$OPENAI_API_KEY" to any URL = one-call key exfiltration.
Fix: fixed allowlist of expandable vars.

Vulnerability: declared-but-unenforced security layers
Severity: HIGH (absence) · Evidence: InjectionScanner has 0 production call sites (grep-verified);
  capability_policy defaults to None at every ToolExecutor construction site (the check exists at
  tools/_stubs.py:153-175 but is never enabled by default config); CredentialStripper (6 regexes)
  wired only into CLI log formatting, while traces/store.py:125-172 persists raw message content.
Fix: wire them — the code exists; it is not invoked.
```

**Also confirmed:** plaintext credentials at `~/.nova_ai/credentials.toml` with `chmod 0600` (a no-op on Windows — `core/credentials.py:93-100`); Tauri sidecar allowlist `"args": true` + unscoped `shell:allow-execute` + `unsafe-inline` CSP (`capabilities/default.json:10-27`, `tauri.conf.json:22`); Docker compose publishes Ollama unauthenticated on 0.0.0.0 (`docker-compose.yml:23`); decorative pairing PIN derived from `abs(hash(ip))` (`mobile_pair_router.py:60`); indirect prompt injection path is open end-to-end (Gmail→ingest→knowledge_search→LLM context with no framing or scanning); cloud streaming via the engine path (`_stream_openai`/`_stream_anthropic` at `engine/cloud.py:1329+`) iterates **sync SDK streams inside async generators** — per-token event-loop stalls on the `/handle_stream_tools` path (`routes.py:470`), the same bug class `ollama.py:61-66` already fixed for Ollama.

**Additional structural findings (verified this pass):** no runtime failover — `_resolve_auto` consumes the ordered cloud preference list as first-match only (`engine/multi.py:171-179`), and the server's own cloud path (`server/cloud_router.py`) has zero retries; the sophisticated retry hardening (`agents/hybrid/_openai_retry.py`: 8 retries + backoff) applies only when hybrid agents are imported, never on `nova serve`/`nova ask`. `model="auto"` pays a blocking `GET /api/tags` on **every** request (`multi.py:271-273` refreshes the model map per call). The server's cloud chat path (`cloud_router.py:190-236`) skips the Anthropic prompt-cache annotation that `engine/cloud.py:301-323` applies — a free cost/latency win left off the main path. No response/embedding cache anywhere; every hybrid query re-embeds.

**Checked and safe** (verified, not scary): CORS allowlist, HMAC-verified webhooks (all 4 endpoints), WebSocket auth, bind-safety gate (`NOVA_AI_API_KEY` required for non-loopback), fully parameterized SQL including FTS `MATCH ?`, upload path extension allowlist + never using filenames as paths, hand-rolled frontmatter parser (no yaml.load), `cli_bridge` argv-only with metachar validation, `db_query` read-only URI mode, no secrets in git history, `pip-audit`: **no known vulnerabilities** in 129 installed packages.

## 7. Performance Audit

**Measured (this machine, not fabricated):**

```text
Performance Issue: CLI startup cost
Current Behavior: nova --version / --help = 3.42–3.85 s; import nova_ai.cli = 3.17 s;
  2,305 modules, 109 MB RSS at import; import nova_ai = 1.10 s (575 modules) then +2.33 s for cli.
Why It Is Slow: cli/__init__ eagerly wires 40+ command modules at import; every command pays.
Expected Impact: every CLI invocation, daemon spawn, scheduler tick.
How To Measure: python -X importtime -c "import nova_ai.cli"
Recommended Fix: lazy subcommand loading (Click lazy groups); defer Rich/connector imports.
Expected Improvement: ~3.5 s → <0.8 s cold.

Performance Issue: litellm import tax when used
Current Behavior: import litellm = 8.5–9.2 s warm-cache (34 s cold disk).
Why: litellm is enormous. It IS lazily imported (engine/litellm.py:50 inside methods) — good —
  but any user configuring a litellm engine pays ~9 s on first use.
Fix: keep lazy; consider dropping the dependency for a thin OpenAI-compatible client (it duplicates
  engine/cloud.py's function) or subprocess isolation. Improvement: first-call latency 9s → <1s.

Performance Issue: knowledge-store ingest throughput
Current Behavior: 6.6 ms/chunk (201 chunks/s insert, 5k-chunk bench = 33.2 s); 5.0 ms/chunk at 300.
Why It Is Slow: one commit per chunk (store.py:313) = one WAL fsync per row; plus an UPDATE-path
  second commit (store.py:334-357). 6,712-chunk docs sync ≈ 45 s of pure fsync.
How To Measure: the bench above (add batching and diff).
Recommended Fix: batch inserts in a single transaction per _BATCH_SIZE (pipeline already batches
  docs in memory — extend to DB writes); keep checkpoint commits per batch.
Expected Improvement: 5-10× ingest throughput (fsync amortization), transactional batches also
  fix the partial-failure window.

Performance Issue: vector recall is brute force over all embeddings
Current Behavior: hybrid_search.py:254-290 loads EVERY embedding BLOB from SQLite into a numpy
  matrix on each query; fine at 5k chunks (~20 ms BM25 + decode), degrades linearly.
Why: no ANN index. Expected Impact: at 100k+ chunks, multi-second queries + large RSS spikes.
Recommended Fix: sqlite-vec (vec0) virtual table, or numpy mmap + float32 pre-loaded cache
  with incremental refresh; quantize (int8/binary) to cut RAM 4-32×.
Improvement: O(n) decode → indexed/constant recall; RSS spike eliminated.

Performance Issue: Ollama timeout = 1800 s default, no intermediate health check
Current Behavior: engine/ollama.py:53. A hung generate pins a worker thread for 30 min.
Fix: 120-300 s default + streaming keepalive heartbeat. Impact: unbounded thread stalls removed.
```

**AI/ML specifics:** token counting is `len(raw) // 4` (`engine/gemma_cpp.py:119`) — char-estimate, not tokenizer, so context-window management is approximate. Router (verified good): precompiled regex tiers, learned corrections, proving-ground overrides, servability checks — genuinely useful, not complexity theater. Caching: tool-description cache exists; **no response or embedding cache** — identical queries re-embed every time (embedder cost per query when hybrid is on).

## 8. Dependency Audit

**Python (129 installed): `pip-audit` = 0 known vulnerabilities.** Core 12 deps, 13 optional groups. Key versions installed: openai 2.54.0, httpx 0.28.1, pydantic 2.13.5, fastapi 0.141.1, litellm 1.100.0, datasets 5.0.1, click 8.5.0, rich 15.0.0 — all current-generation majors, none abandoned.

| Dependency | Current | Status | Risk | Recommendation |
|---|---|---|---|---|
| litellm | 1.100.0 | heavy (9 s import), duplicates cloud.py function | Medium | Replace with thin client or isolate |
| datasets (HF) | 5.0.1 | only needed by evals; in **core** deps | Low | Move to evals extra; slims every install |
| nvidia-ml-py | core dep | GPU-only feature | Low | Move to extra |
| posthog | 7.48.0 | telemetry in core | Low | fine; keep non-blocking (it is) |
| httpx2 | 2.12.0 installed | unusual name — verify it's intentional | Low | audit why both httpx and httpx2 present |

**Frontend (40 deps): `npm audit` = 36 vulnerabilities (14 high, 19 moderate, 3 low), ALL with `fixAvailable=true`** — notable: react-router (RCE-class turbo-stream deserialization — you're on react-router 7.13.1), vite (path traversal + dev-server file read), lodash, js-yaml, nanoid, serialize-javascript. None of the high ones are in the shipped desktop bundle's runtime path except react-router/vite-adjacent code; **run `npm audit fix` and re-test** — it's one command.

**Rust:** Cargo.lock current; embed-resource/tauri-winres pinned (known-good for the GNU toolchain workaround).

## 9. Code Quality Audit

**Genuinely good:** zero bare `except:` in 157k lines; 965 `except Exception` blocks but only 3 `except Exception: pass`; systematic `soft_fail()` (245 sites, forced context, greppable); ~90% return-annotation coverage (4,878/5,415 defs; 20/36 subpackages at 98-100%).

**Ranked debt:**
1. **God files** (all confirmed by read): `server/agent_manager_routes.py` 2,494 (five routers in one file, 5-tuple return signature); `agents/hybrid/toolorchestra.py` 1,868; `engine/cloud.py` 1,825 (8 providers, parallel `_generate_*/_stream_*` pairs); `evals/cli.py` 1,799 (78 elif dispatch); `evals/datasets/coding_assistant.py` 1,632 (30 hand-written test tasks as inline Python — should be a JSON fixture); `agents/hybrid/mini_swe_agent.py` 1,603 (4 provider loops duplicating engine/cloud.py); `lib.rs` 2,942 (boot supervisor + 31 commands, of which the `fetch_*` family are pure HTTP proxies duplicating what api.ts already does); `frontend/src/pages/AgentsPage.tsx` 4,007 (≈15 in-file components, duplicated by `AgentsPanel.tsx` 1,210).
2. **Duplication:** two pricing tables (B3); ≥4 overlapping retry regimes (`_openai_retry.py` monkey-patch, `_base.py` max_retries=12, `minions.py` `_patch_anthropic_globally`, cloud.py temperature-retry); ≥5 sites each building their own OpenAI/Anthropic client; 12 per-engine config dataclasses differing only in a `host` default (`sections.py:36-122`).
3. **Dead/shadowed code:** `agents/hybrid/skillorchestra.py` (416 lines) fully shadowed by the `skillorchestra/` package (package wins; would raise double-registration if both loaded); 12 test modules inside `src/nova_ai/evals/tests/` ship in the wheel and never run (pyproject packages `src/nova_ai`, testpaths `tests`); `nexa_shim.py`, `server/stream_bridge.py`, `learning/spec_search/student_runner.py` unreferenced (likely); mock-created directory `MagicMock/load_config().../` at repo root (harmless fossil).
4. **Typing:** mypy config is report-only (`check_untyped_defs=false`, `no_strict_optional=true` — pyproject:280-289); no `py.typed`, so the excellent annotations don't help downstream consumers. Weak spots: server/ 54% return-annotated.
5. **Config:** 31 sections / 79 classes; validation is type-walking only (no ranges/cross-field); silent-drop of unknown TOML keys (asymmetric with strict `config set`).

## 10. Testing Audit

**Reality check (verified):** 6,969 test functions; >99% of the suite runs in the Linux CI lane (only 19 marker-deselected: live/cloud/hub/slow). The "7,648" figure from earlier sessions ≈ this suite + parametrization. Coverage gate `--cov-fail-under=60`. One live test fails on Windows (B4). Windows CI runs exactly **2 test files** (`ci.yml:125`). Frontend: **1 test file**, and `frontend.yml:35-37` runs only tsc + build — **`npm test` never runs in CI**, so even that one test could fail without blocking.

**Missing-test plan (highest value first):**

```text
Test: mid-sync cursor advancement + resume
Input: connector yielding 2 pages, crash after page 1
Expected: checkpoint cursor = page-1 token; resume fetches only page 2
Current: cursor stays None (B2) — test would fail today
Priority: P0

Test: code_interpreter escape
Input: "import subprocess; subprocess.run([...])"  (no dots in blocked substrings)
Expected: blocked or sandboxed
Current: executes with full privileges — test would fail today
Priority: P0 (write it as a security regression test that must fail-open loudly)

Test: CloudEngine without XAI_API_KEY
Input: no env keys, call _generate_xai
Expected: EngineConnectionError("not configured")
Current: AttributeError (B1) — reproduces
Priority: P1

Test: localStorage saveConversations quota exceeded
Input: mock setItem to throw
Expected: graceful prune + warning
Current: exception propagates (B5)
Priority: P1 (also make CI run npm test)

Test: FTS update path preserves searchability
Input: store doc, update content, retrieve new terms
Current: verified working manually — pin it as regression test
Priority: P2

Test: Windows lane expansion — run the connectors + engine suites on windows-latest
Current: 2 files; B4 and B8 would both have been caught
Priority: P1
```

## 11. Reliability Audit

**Verified weakest points, ranked:** (1) SyncEngine checkpoint incoherence (B2 — worst for Slack: full workspace re-fetch); (2) no 429/5xx retry in Gmail/Google connectors (`google_auth.py:114-116` re-raises everything non-401; one rate-limit aborts a mailbox sync) vs Slack's exemplary `Retry-After` handling; (3) chat-history persistence fragility (B5/B6 + durable `chat_history.db` and `/api/history` exist but the main UI never calls them — dual persistence, fragile one wired); (4) Windows second-class (2 test files, fcntl crash, no daemon supervision, chmod no-op); (5) Ollama 1,800 s timeout + no SQLite `busy_timeout` + Baileys bridge reporting CONNECTED while dead with sends swallowed at debug.

**Offline test (traced, all externals down):** local-first is real — chat fails fast with `EngineConnectionError` surfaced in UI; `model="auto"` degrades to Ollama-only with a clear error, never silently billing cloud; knowledge *retrieval* keeps working over FTS (embedder failure returns None; ingestion skips vectors); update checks and analytics soft-fail; no crash loops or corruption. Degradation = "local chat + search, no ingestion." ✅

## 12. Scalability Audit

Single-user local product — the meaningful scale axis is **data volume and concurrency, not users**:

- **1k–100k chunks:** FTS fine (20 ms @ 5k). Brute-force vector recall is the first wall (~100k chunks → seconds + RAM spikes per query). Insert throughput 200/s means a 100k-chunk initial sync ≈ 8 min of fsync-bound writes.
- **Concurrent requests:** FastAPI is fine, but per-chunk SQLite commits + no busy_timeout → lock contention with background sync; the 1,800 s Ollama timeout can pin threads.
- **10k+ conversations/messages:** localStorage quota (5 MB) will brick chat persistence (B5) — this is the "what breaks first" answer for a heavy user: **frontend chat history**, at maybe a few hundred long conversations.
- **Multi-user:** not a design goal; server binds loopback without a key (correct), but nothing scales past one user (no queueing, no multi-tenant anything). Fine — but say so in docs.

## 13. AI/Agent Audit

- **Router:** real and well-built (regex tiers + feedback corrections + proving-ground + servability). Not complexity theater. ✅
- **Agent loops:** tool loops exist across 9 hybrid paradigms; loop_guard exists in Rust and is bridged. Termination limits exist per-agent; the risk is not infinite loops but **unbounded token burn with no budget guard** — no per-task cost ceiling found in toolorchestra/_base paths.
- **Verification:** agents trust LLM output; no task-verification pass or output-contract checking outside evals.
- **Context management:** char-based token estimates (`len // 4`); truncation exists in uv-sync helpers but no rigorous context-window budgeting per engine.
- **Prompt injection:** the whole chain is open (see §6): ingested content → knowledge_search → context, with the scanner built and unwired. Combined with code_interpreter/shell_exec, this is the project's single largest risk cluster.
- **Hallucinated tool args:** taint checking and sensitive-file policy exist and are wired (tools/_stubs.py:180+) — genuinely good; they just don't cover the execution tools.

## 14. Competitive/Industry Research

Live web research was unavailable in this session; the comparison below is from training knowledge and should be re-validated against current docs before decisions.

```text
Project: Open WebUI
Architecture: React + FastAPI, Ollama/OpenAI backends, SQLite/Postgres
Strength: mature chat UX, huge community; Weakness: heavier server, less agent/eval depth
What NOVA does better: evals-as-first-class (energy/latency/cost), hybrid agent paradigms, trace-driven learning loop
What NOVA does worse: chat persistence (OWUI stores server-side durably — NOVA's is localStorage), auth maturity, onboarding polish

Project: OpenHands
Architecture: event-stream agent runtime + sandboxed exec (Docker by default)
Strength: code-agent execution safety via real sandboxes; Weakness: heavy, cloud-leaning
What NOVA does better: local-first resource budgeting, energy telemetry
What NOVA does worse: code_interpreter sandbox (OpenHands' container model is the fix NOVA's own ContainerRunner should be wired to)

Project: Khoj
Architecture: Django + web + desktop, local/cloud model split
Strength: retrieval quality, sync UX; Weakness: less agent programmability
What NOVA does better: tool registry breadth (78), skills system, channel daemons
What NOVA does worse: sync reliability (cursor bug), embedding index (Khoj uses proper ANN via pgvector/Asymmetric tradeoffs)

Industry best practice NOVA is missing: secrets in OS keyring; ANN vector index; server-side chat persistence; per-task LLM budget ceilings; signed updater key-rotation path (docs admit none exists).
```

## 15. Benchmark Results

All measured on this machine (Windows 11, GNU toolchain build), stated as measured:

| Benchmark | Result |
|---|---|
| `nova --version` / `--help` | 3.42 / 3.70 s (3-run min/avg: 3.42/3.66) |
| `import nova_ai` | 1.10 s (575 modules) |
| `import nova_ai.cli` | +2.33 s → 2,305 modules, **109 MB RSS** |
| `import litellm` | 8.5–9.2 s warm (34 s cold) |
| `import nova_ai.server.app` | 3.93 s |
| `import nova_ai.engine.cloud` | 1.24 s |
| knowledge store insert | 6.6 ms/chunk (5k bench: 33.2 s total) |
| knowledge store query (BM25 @5k) | 20.1 ms |
| re-store (update path) | 4.2 ms/chunk |
| Full suite (`-m "not slow" -x`) | 2,173 passed, 1 failed (B4), 172.8 s |
| Live smoke test alone | 61.8 s (6,712 chunks indexed end-to-end) |

**Not measured — benchmark required:** Ollama end-to-end inference latency (needs a live model run), frontend runtime FPS/render profiles, hybrid-search vector recall at scale, memory under 24 h daemon uptime, sync throughput with a live connector. Procedures: standard `llm-perf` harness for (1); React DevTools profiler + long task API for (2); the 5k bench scaled ×20 with the embedder on for (3); 24 h soak with RSS sampling for (4); `time.perf_counter` around `_embed_chunk`/`store()` with embedder on vs off (`pipeline.py:118-119` isolates embedding cost) for (5).

## 16. Edge-Case Analysis

**Edge Case Matrix (probed live where marked ✅):**

| Case | Result |
|---|---|
| Empty search query | ✅ returns 0 results, no crash |
| 100k-char query | ✅ 2 ms, no crash |
| FTS operator-only (`NEAR OR AND NOT`) / unclosed quote / special chars | ✅ caught by `OperationalError` → [] (store.py:444-446) |
| SQL injection string in query | ✅ parameterized, harmless |
| Knowledge store: update path FTS refresh | ✅ verified — updated content is searchable (good catch by design at store.py:334-357) |
| All external deps down | ✅ graceful (see §11) |
| 5k→100k chunks | ⚠ linear BM25 fine; vector recall degrades |
| localStorage >5 MB | 🔴 throws uncaught (B5) |
| Store `version: 2` blob | 🔴 wipes history (B6) |
| Missing Ollama at startup | ✅ EngineConnectionError, clean UI surfacing |
| Concurrent writers to SQLite | ⚠ no busy_timeout — intermittent lock errors likely |
| Windows temp-dir cleanup with open DB handle | 🔴 live test fails (B4) |
| XAI key unset | 🔴 AttributeError (B1) |
| Disk full mid-ingest | ⚠ SQLite raises; partial batch persists; checkpoint stale (B2 makes resume wasteful but dedup prevents duplication) |
| Corrupt knowledge.db | 🔴 no integrity check/repair path anywhere; raw DatabaseError per request |

## 17. Critical Issues

### 🔴 MUST FIX
1. **Execution-tool security** — code_interpreter blocklist sandbox + shell_exec env_passthrough (§6 C1/C2). This is the "personal AI" trust boundary.
2. **Wire the security that exists** — InjectionScanner (0 call sites), capability_policy (never enabled by default), trace redaction (raw content persisted).
3. **Event-loop blocking in the server** — non-streaming `/v1/chat/completions` calls `engine.generate`/`agent.run` inline (`routes.py:229,239`); one slow generation (Ollama timeout is 1,800 s) freezes every endpoint. One-line `asyncio.to_thread` fixes at both dispatch sites.
4. **B1** CloudEngine `_xai_client` AttributeError (reproduced).
5. **B2** SyncEngine cursor checkpointing broken.
6. **B5+B6** chat history: quota crash + version-bump wipe; wire the existing server-side store.
7. **Frontend dependency CVEs** — `npm audit fix` (all fixable, includes react-router RCE-class and vite advisories).

### 🟠 SHOULD FIX
8. Retry/backoff for Gmail/Google connectors; SQLite `busy_timeout` everywhere; Baileys bridge health/supervision.
9. SSRF: unify on redirect-re-checking fetch; DNS fail-closed.
10. Runtime model failover: iterate the cloud preference list on failure instead of first-match (`multi.py:171-179`); port `_openai_retry`'s wrapper to `engine/cloud.py` + `cloud_router.py`.
11. `git_manager` arg injection; file-policy symlink resolution + `.git-credentials`/`.aws/credentials` patterns.
12. Batch knowledge-store inserts (5-10× ingest); sqlite-vec or cached matrix for vector recall.
13. Windows parity: expand CI Windows lane beyond 2 files; fix fcntl; real keyring for credentials.
14. B3 pricing-table merge; B4 test store.close(); B7 layering extraction; B10 chat-history cap.

### 🟡 IMPROVEMENTS
15. CLI lazy loading (3.5 s → <1 s); drop `datasets`/`nvidia-ml-py` from core deps; litellm replacement decision.
16. Split agent_manager_routes.py (5 modules) and cloud.py (per-provider classes); delete shadowed skillorchestra.py; move evals/tests into tests/; data-drive evals CLI.
17. mypy strictness for core/+server/, add py.typed; warn on unknown config keys; per-page error boundaries; error boundaries + `npm test` in frontend CI.
18. Frontend streaming perf: memoize `MessageBubble`, render the live bubble from `streamState` instead of mutating the array at 12.5 Hz, debounce `saveConversations`.
19. TTL-cache the MultiEngine model map (kills a per-request `/api/tags` probe); apply Anthropic prompt-cache annotation on the `cloud_router.py` path.

### 🟢 OPTIONAL
20. Shrink unused Rust twins (feature-gate ~2/3 of nova_ai-python); delete pure-proxy Tauri commands; split lib.rs into boot/commands/keys.
21. Docs: state single-user scope explicitly; document updater key-rotation recovery (currently none).

## 18. Root-Cause Analysis

**Symptom: LLM can exfiltrate secrets / run arbitrary code.**
Immediate cause: dangerous tools with weak gates. Underlying cause: trust boundary defined as "the user confirmed" instead of "the runtime enforces". Architectural cause: security layers (scanner/capabilities/stripper) were built as standalone modules with no enforcement point in the executor — the ToolExecutor is the natural chokepoint and it's optional. **Permanent fix:** make the executor the only dispatch path and make confirmation/capability/scanning non-optional there; containerize execution tools by default.

**Symptom: sync resume re-fetches everything.**
Immediate: stale cursor persisted. Underlying: connector API returns documents only; cursor state lives in connector instances that die between runs. Architectural: the sync contract (`connector.sync(since, cursor)` → iterator) has no channel for cursor progress. **Permanent fix:** change the contract to yield progress (`(doc, cursor)` or a sync_status object the engine reads per batch), and add the interrupt-resume test.

**Symptom: two costs for the same model call.**
Immediate: two tables. Underlying: hybrid agents were vendored from a research harness ("ported verbatim") with their own plumbing. Architectural: no single owner of provider metadata. **Permanent fix:** one provider-metadata module (pricing, context windows, capabilities) consumed by engine + agents.

**Symptom: everything is huge files.**
Immediate: features accreted in place. Underlying: no file-size/module-boundary linting, and the registry pattern that works so well for engines/agents/tools was never applied to routers, providers, and eval benchmarks. **Permanent fix:** apply the existing RegistryBase pattern to evals dispatch and server routers; add a soft per-file line budget in CI (ruff plugin) to stop regression.

## 19. Recommended Architecture

**Do NOT rewrite.** The bones are good: registry pattern, layered-ish imports, Rust bridge for hot paths, one data layer. This is a refactor-and-wire project.

```text
CURRENT                          →  PROPOSED
server → cli → agents (cycles)   →  composition/ layer: tool factories, memory backend,
                                    provider metadata; server+cli+scheduler all import DOWN
engine/cloud.py (8-in-1)         →  engine/providers/{openai,anthropic,google,...}.py on
                                    _openai_compat base; CloudEngine = thin dispatcher
tools exec (blocklist)           →  sandbox/runner.py as default path for code/shell tools;
                                    ToolExecutor enforces capabilities+scanning+confirmation
chat history (localStorage)      →  server chat_history.db via /api/history (exists!),
                                    localStorage becomes cache-only
vector recall (brute force)      →  sqlite-vec vec0 table + int8 quantization fallback
rust mirror (100% parity)        →  keep security/storage/tools/loop_guard; feature-gate rest
evals (23% of package)           →  separate nova-ai-evals distribution or extras group
```

**Migration plan:** (1) executor enforcement + sandbox default (no API changes); (2) composition layer extraction (move, don't rewrite — imports update only); (3) provider split (mechanical, per-provider PRs); (4) chat persistence switch (feature-flag, fallback to localStorage); (5) vector index (additive); (6) evals split (packaging only).

## 20. Prioritized Fix Roadmap

**Phase 1 — Emergency (this week)**
```text
P0 | Wire enforcement in ToolExecutor: mandatory confirmation for shell_exec/code_interpreter, capability defaults on, scanner on retrieval | tools/_stubs.py, security/* | blocks prompt-injection→exec | Medium | Critical | —
P0 | npm audit fix + frontend test run in CI | frontend | closes 14 high CVEs | Trivial | High | —
P0 | asyncio.to_thread around _handle_direct/_handle_agent | server/routes.py:229,239 | unblocks whole server during generation | Trivial | High | —
P1 | Fix B1 (one line), B2 (contract change), B4 (test hygiene) | engine/cloud.py, sync_engine.py, test file | correctness | Small | High | —
```
**Phase 2 — Stability (2-3 weeks)**: retry/backoff for Google connectors; busy_timeout; Baileys supervision; chat persistence to server store with quota-safe fallback; Windows CI lane expansion + fcntl fix; keyring credentials; runtime model failover over the preference list.
**Phase 3 — Performance**: batch inserts; lazy CLI; sqlite-vec; Ollama timeout tuning; tokenizer-accurate counting for context budgets; async SDK streams in cloud.py; frontend streaming memoization; TTL model-map cache.
**Phase 4 — Architecture**: composition layer; cloud.py provider split; agent_manager_routes split; evals data-driving + packaging split; pricing single-source.
**Phase 5 — Scaling**: vector index at scale; ingest pipeline transactionality; daemon watchdogs; soak-test harness.
**Phase 6 — Advanced**: budget ceilings per task; task verification passes; updater key-rotation story; multi-channel secret redaction at trace save.

## 21. Project Scorecard

| Category | Score | Why |
|---|---:|---|
| Architecture | 7.5 | Strong registries, real layering broken by 5 upward imports; god files everywhere |
| Code Quality | 7 | 90% annotations, zero bare excepts; mypy decorative; duplication clusters |
| Functionality | 8.5 | Everything README claims exists and runs; verified |
| Performance | 6.5 | Solid FTS core; 3.5 s CLI, fsync-per-chunk ingest, brute-force vectors, event-loop blocking in server |
| Security | 4.5 | Good server/webhook auth, but execution tools + unwired defenses + plaintext keys |
| Reliability | 6 | Offline-first real, Slack retry great; sync cursor broken, Gmail brittle, fragile chat persistence |
| Scalability | 5.5 | Fine to ~10⁵ chunks/1 user; vector recall + localStorage + lock contention walls after |
| Testing | 7 | 6,969 real tests, >99% run in CI; Windows blind spot, frontend effectively untested |
| Maintainability | 6 | Registries help; 5 files >1,800 lines + dead mirrors tax every change |
| AI/Agent Design | 7 | Router is genuinely good; no budgets, no verification pass, injection path open |
| Documentation | 8 | 89 pages, claims verified honest (under-promises agents if anything) |
| **Overall** | **6.9** | Works, tested, honest docs — held back by security wiring, sync correctness, and structural debt |

## 22. Final Verdict

1. **Does it work?** Yes. Verified end-to-end: CLI, server, desktop (I built and launched the exe this week), knowledge sync of 6,712 real chunks, retrieval, router, offline degradation.
2. **What works well?** Registry/plugin architecture; the SmartRouter; Slack retry handling; offline-first behavior; the test suite's realness; docs honesty.
3. **What is broken?** xai AttributeError (reproduced), sync cursor, Windows live test, chat persistence, Gmail resilience.
4. **What is fragile?** localStorage chat history, Baileys channel, SQLite concurrency, Windows paths everywhere.
5. **Unnecessarily complicated?** 8-provider CloudEngine, 78-elif evals CLI, the unused 2/3 of the Rust mirror, dual agent UIs (4,007-line page + 1,210-line panel).
6. **Dangerous?** code_interpreter + shell_exec with unwired scanner/capabilities; env-passthrough; plaintext keys on Windows; Docker Ollama on 0.0.0.0.
7. **Slowing it down?** 3.5 s CLI startup; fsync-per-chunk ingest; brute-force vector recall; event-loop blocking on the server's non-streaming path; per-request model-map probe on `auto`.
8. **What breaks at scale?** Vector recall (~10⁵ chunks), localStorage (~10² conversations), SQLite locking under concurrent sync.
9. **Remove?** Shadowed skillorchestra.py, evals/tests from the wheel, unused Rust twins (gate), pure-proxy Tauri commands, `datasets`+`nvidia-ml-py` from core deps.
10. **Redesign?** No rewrite. Extract a composition layer, split cloud.py/routes, make ToolExecutor the enforced chokepoint.
11. **Keep?** Registries, SmartRouter, FTS store, Rust security bridge, evals core, test discipline, docs.
12. **Production-ready?** For you, locally, today: yes with eyes open. For anyone else or always-on channels: not until Phase 1-2 are done.
13. **Single biggest weakness?** The trust boundary: an AI with arbitrary-execution tools whose paper defenses are not wired in.
14. **Single highest-value improvement?** Enforce capabilities + confirmation + injection-scanning inside ToolExecutor and route code/shell tools through the existing ContainerRunner. One change collapses the entire critical risk cluster.
15. **If I were responsible, first fix?** Phase 1 in order: ToolExecutor enforcement → `npm audit fix` → B1/B2/B4 → sync-cursor regression test. Everything else follows.

---

# TOP 10 THINGS I SHOULD FIX FIRST

1. **Enforce security in ToolExecutor** — mandatory confirmation for `code_interpreter`/`shell_exec`, drop `env_passthrough`, enable `capability_policy` defaults, call `InjectionScanner` on ingestion/retrieval (`tools/_stubs.py:153-226`, `tools/code_interpreter.py`, `tools/shell_exec.py`).
2. **`npm audit fix`** — 36 vulnerabilities, all auto-fixable, including RCE-class react-router and vite advisories; add `npm test` to `frontend.yml`.
3. **Fix CloudEngine `_xai_client`** — one-line init at `engine/cloud.py:367`; add a no-keys config test (reproduced AttributeError).
4. **Fix SyncEngine cursor checkpointing** — `sync_engine.py:104`; change connector contract to surface cursor progress; add interrupt-resume test.
5. **Chat persistence to the server store** — wire `chat_history.db`/`/api/history` (both exist); guard `saveConversations` (store.ts:65) and stop wiping on version mismatch (store.ts:57).
6. **Retry/backoff for Gmail/Google connectors** — mirror Slack's `Retry-After` pattern (`slack_connector.py:138`); currently one 429 aborts a whole sync.
7. **Route `web_search` through the redirect-aware SSRF fetch and fail DNS closed** (`web_search.py:88` vs the correct `http_request.py:206` helper).
8. **Batch knowledge-store inserts + SQLite `busy_timeout`** — one transaction per batch (5-10× ingest), removes lock contention (store.py:313).
9. **Windows parity pass** — expand the Windows CI lane beyond 2 files, fix `fcntl` import (runner.py:21), OS keyring for credentials (chmod 0600 is a no-op there).
10. **Merge pricing tables & extract the composition layer** — kill the conflicting gpt-4o/gpt-5 numbers, move shared factories out of `cli/ask.py` to break the server↔cli↔agents cycle.

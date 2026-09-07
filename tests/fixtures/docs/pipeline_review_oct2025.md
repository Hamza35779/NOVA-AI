# Pipeline Code Review — Oct 2025

Five modules reviewed after the October hybrid-paradigm session: `agentic_runner.py`, `coding_task.py`, `_openai_retry.py`, `agent_manager_routes.py`, and `research_router.py`. Each has a severity rating: **blocker**, **bug**, **wobble**, or **cosmetic**.

## AgenticRunner (`evals/core/agentic_runner.py`)

### Bug: Orphan threads on timeout

Both `_run_sequential` and `_run_concurrent` use `asyncio.wait_for` to enforce `query_timeout`. When the timeout fires, `asyncio.TimeoutError` is raised but the underlying `run_in_executor` thread continues running — it keeps calling the model, accumulating tokens, and consuming telemetry capacity. With a concurrency semaphore the orphan holds no slot, so another query may launch alongside it, leading to:

- Energy attribution overlap (telemetry windows pollute adjacent queries)
- Unbounded resource burn on long-running timed-out queries
- Possible port / socket exhaustion from leaked Playwright sessions

**Fix needed:** wrap the executor in a cancellable pattern (e.g. `asyncio.to_thread` with a shutdown callback), or use a `concurrent.futures.ThreadPoolExecutor` per query so the thread dies when the future is cancelled (limited to sync-only tool calls).

### Bug: gather swallows per-query failures

`_run_concurrent` calls `asyncio.gather(*tasks)` with no `return_exceptions=True`. If a task's `_process` fn raises outside its inner try/except (e.g. `copy.deepcopy(self._agent)` blows up, or `_save_query_artifacts` hits a filesystem error), the entire sweep fails at once and every other in-flight trace is lost. Under `concurrency=50` that's 49 valid results discarded for one artifact write error.

Fixed in this session: `return_exceptions=True` now isolates failures.

### Wobble: tool-turn matching by name (not id)

`_build_turn_traces` keys tool starts and ends by tool *name* in `tool_start_times: dict[str, float]`. When two concurrent calls use the same tool (e.g. two parallel `file_read` calls), the second start overwrites the first, and the end callback matches the wrong start timestamp — producing wildly wrong latency figures and losing one tool's arguments.

**Fix:** key by the event's `tool_call_id` (the LLM-side unique call ID) instead of the tool name. This requires the event metadata to include the call ID, which the relay bridge in `_run_single_query` does not currently carry.

### Cosmetic: deprecated `get_event_loop()`

Line 223 uses `asyncio.get_event_loop()` which emits a `DeprecationWarning` in Python 3.12+. Replaced with `get_running_loop()` in this session.

## Coding Task Scorer (`evals/scorers/coding_task.py`)

### Bug: code-exec crash masks as `no_assertions_found`

When `exec(code, namespace)` raises (SyntaxError, NameError, import error), `_run_tests` returns `(0, 0, "Code execution error: …")`. The scorer then sees `total == 0` and returns `(None, {"reason": "no_assertions_found"})`.

A crash is **not** "no assertions" — it's a model failure. Returning `None` means downstream resolve-rate code excludes this from the denominator, artificially inflating resolve-rate. The model that wrote broken code gets a free pass.

**Fix:** propagate the error as `is_correct=False` with a dedicated reason string.

### Bug: line-by-line exec mis-counts passes

When `exec(test_cases, namespace)` fails with `AssertionError`, the fallback runs each line individually — counting `assert` lines as tests. But many tests span multiple lines: setup/arrange lines without `assert`, try/except blocks, parenthesized multi-line assertions. Executing a bare line like `result = my_fn(42)` (part of a multi-line arrange block) will either raise `NameError` (previous setup not run) or falsely succeed, throwing off the pass count.

**Fix:** require tests to be a single `def test_*()` function and run it via `unittest.TestCase` or the existing assertion-counter on the whole block is actually fine — just treat any exec-level `AssertionError` as 0 passed, rather than trying fine-grained line-by-line counting.

### Wobble: first-fence extraction

`_extract_code` grabs the first ```python fence it finds. If the model leads with an example snippet in its explanation before presenting the real implementation, the wrong code is scored. Against GPT/claude this is rare but happens.

## OpenAI Retry Layer (`agents/hybrid/_openai_retry.py`)

### Bug: async path dead-code stubs the import

Lines 344–355 import the async module, find `AsyncCompletions`, then silently skip. The module-level import of the same `from openai.resources.chat import completions as _comp_mod_async` aliases the *sync* module again — it never actually imports `openai.resources.chat.completions`'s async variant. If a paradigm ever uses async OpenAI calls, no retry/throttle is applied.

### Wobble: stream calls wrapped but not stream-retriable

The wrap replaces `chat.completions.create` including `stream=True` calls. A stream that times out mid-flight gets no retry (correct), but the timeout of 600s on the SDK `create()` itself is also harmless. The hidden risk: if `stream=True` is passed and the SDK raises mid-stream (not during create), the retry doesn't fire because the generator runs outside the wrapped call.

### Cosmetic: `_is_local_endpoint` catches `Exception`

Line 133–146 catches bare `Exception` from `getattr(client, "api_key")` and `urlparse`. Could mask a `NameError` from a typo in client inspection.

## Agent Manager Routes (`server/agent_manager_routes.py`)

### Blocker: tool execution blocks the event loop

In `_stream_managed_agent`'s generator (line ~1379, ~1418), both MCP adapter calls (`mcp_adapter.execute(**parsed_args)`) and ToolExecutor calls (`executor.execute(...)`) run **synchronously** inside `async def generate()`. The entire `StreamingResponse` generator runs on the asyncio event loop's thread. A tool call that takes 30 seconds (shell_exec, file read of a large directory, knowledge_search on a busy DB) blocks the entire server — all other SSE streams, all HTTP requests, and the health-check endpoint stall for 30 seconds.

**Fix needed:** wrap every tool execution in `await asyncio.to_thread(...)` so it yields the event loop to other pending coroutines.

### Budder: DeepResearch orphan on queue timeout

The DeepResearch SSE path (line ~1043) uses `asyncio.to_thread(progress_q.get, timeout=600)`. On timeout the generator breaks and returns, but the `daemon=True` worker thread keeps running — it continues calling the model, accumulating `progress_q` entries, and tries to `store_agent_response` after the SSE stream is gone. The store may succeed on a dangling app_state, but the user sees a truncated response.

### Wobble: resource leak in `list_traces` / `get_trace`

Every call opens a new `TraceStore(db_path)` and never closes it. If TraceStore uses connection-per-instance, these accumulate. Most DB stores are fine with multiple connections, but SQLite in WAL mode can hit `SQLITE_BUSY` under concurrent reads from threads.

### Cosmetic: inline imports inside hot path

`import time as _lgtime`, `import json`, `from nova_ai.core.types import ToolCall as MsgToolCall` appear mid-function inside `generate()` and `_stream_managed_agent`. Python's import cache makes this harmless but adds ~0.5ms per import resolution. These should be at module top-level.

### Cosmetic: hardcoded model default

Line 1899 `"qwen3.5:9b"` is used as a fallback when `engine._model` is empty. This string should be a module-level constant or come from config.

## Research Router (`server/research_router.py`)

### Bug: no overall timeout on research call

`_stream_research` has no deadline. If the agent thread gets stuck (Ollama daemon wedged, a search call hangs on the network), the queue `get()` blocks forever and the SSE connection stays open indefinitely. The DeepResearch path has a 600s queue timeout; this one has none.

**Fix needed:** apply a total deadline to the consumer loop (e.g. `asyncio.wait_for(queue.get(), timeout=300)`), and in the timeout handler send error + done frames → cancel the worker thread.

### Wobble: exn in cancelled generator escapes

In the `finally` block of `_stream_research`, line 458 awaits the worker task inside a generator that may be cancelled by the SSE client disconnecting or by Starlette's timeout. Under `CancelledError` the `await task` raises immediately — and since `CancelledError` inherits from `BaseException`, it is not caught by `except Exception`. The generator throws, and Starlette logs a generic "cancelled" message rather than a clean "done" frame.

**Fix:** wrap the cancellation-sensitive part in `try/except BaseException`, or make the worker task shielded with `asyncio.shield`.

## Severity Summary

| File | Component | Severity | Issue |
|------|-----------|----------|-------|
| `agent_manager_routes.py` | Tool execution | **Blocker** | Sync I/O blocks event loop |
| `research_router.py` | SSE consumer | **Bug** | No total deadline → hang forever |
| `agentic_runner.py` | Concurrency | **Bug** | Orphan threads on timeout |
| `coding_task.py` | Scorer logic | **Bug** | Crash → None (excluded from resolve-rate) |
| `coding_task.py` | Code extraction | **Bug** | Line-by-line pass miscount |
| `agentic_runner.py` | Turn building | **Wobble** | Tool latencies wrong on concurrent same-name calls |
| `agent_manager_routes.py` | Streaming | **Wobble** | DeepResearch orphan on queue timeout |
| `agent_manager_routes.py` | Resource | **Wobble** | TraceStore connection leak |
| `research_router.py` | SSE | **Wobble** | CancelledError escapes finally clause |
"""SSE streaming for managed-agent runs.

Split from ``agent_manager_routes.py``. ``_stream_managed_agent`` runs a
managed agent with real LLM token streaming; supports multi-turn tool
calling and the deep-research progress loop.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Dict, List

from nova_ai.agents.manager import AgentManager
from nova_ai.core.types import Message, Role
from nova_ai.core.types import ToolCall as MsgToolCall

try:
    from fastapi.responses import StreamingResponse
except ImportError:
    raise ImportError("fastapi is required for server routes")

from nova_ai.server.agent_manager.common import (
    _build_deep_research_tools,
    _build_managed_system_prompt,
    _get_mcp_tools,
    _merge_tool_call_fragments,
    _replay_history_messages,
    _resolve_tool_specs,
    _sampler_kwargs,
    _sse_chunk,
    _tool_progress_label,
    logger,
)

# Queue timeout for the DeepResearch SSE consumer (seconds): if no event
# arrives within this window the worker is considered wedged and the stream
# is terminated with a timeout notice.
_DR_QUEUE_TIMEOUT_S = 600.0


_DEFAULT_LOCAL_MODEL = "qwen3.5:9b"


async def _stream_managed_agent(
    *,
    manager: AgentManager,
    agent_record: Dict[str, Any],
    user_content: str,
    message_id: str,
    engine: Any,
    bus: Any,
    app_state: Any = None,
) -> StreamingResponse:
    """Run a managed agent with real LLM token streaming via SSE.

    Uses ``engine.stream_full()`` to yield tokens as they arrive from the
    LLM. Supports multi-turn tool-calling: when the model emits tool_calls,
    they are executed and the results fed back for the next turn.
    """
    agent_id = agent_record["id"]
    config = agent_record.get("config", {})
    # Resolve the model: prefer the agent's own config, then the server's
    # resolved model (app.state.model — what the engine was booted with),
    # and only then the legacy engine._model attr. OllamaEngine takes the
    # model per-call and exposes no _model attr, so without the app_state
    # fallback this resolved to "" and Ollama 400'd on an empty model.
    model = (
        config.get("model")
        or getattr(app_state, "model", None)
        or getattr(engine, "_model", "")
    )
    system_prompt = config.get("system_prompt")
    temperature = config.get("temperature", 0.7)
    max_tokens = config.get("max_tokens", 1024)
    max_turns = config.get("max_turns", 10)

    # Build conversation messages from history + current input
    llm_messages: List[Message] = []

    # Wire the SystemPromptBuilder to inject SOUL.md / MEMORY.md / USER.md
    # persona files (parity with the CLI/ask path) — see #431.
    app_config = getattr(app_state, "config", None)
    if app_config is None:
        from nova_ai.core.config import load_config

        app_config = load_config()

    final_system_prompt = _build_managed_system_prompt(system_prompt or "", app_config)

    if final_system_prompt and final_system_prompt.strip():
        llm_messages.append(
            Message(role=Role.SYSTEM, content=final_system_prompt.strip())
        )

    # Resolve agent type and class for DeepResearch tool wiring
    agent_type = agent_record.get("agent_type", "")
    if agent_type == "deep_research":
        dr_tools = _build_deep_research_tools(
            engine=engine,
            model=model,
        )
        # Store on app_state so streaming loop can access them
        if app_state is not None and dr_tools:
            app_state._dr_tools = dr_tools

    # Load prior conversation context (DESC order, reverse for chronological).
    # Replaying recorded tool_calls (assistant tool-use + tool results) keeps
    # multi-turn tool behaviour from regressing to fabricated output (#382).
    history = manager.list_messages(agent_id, limit=50)
    llm_messages.extend(_replay_history_messages(history, message_id))

    # Append the current user message
    llm_messages.append(Message(role=Role.USER, content=user_content))

    # Mark the user message as delivered
    manager.mark_message_delivered(message_id)

    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    # For deep_research agents: run the full agent loop, not raw streaming
    if agent_type == "deep_research" and app_state is not None:
        dr_tools = getattr(app_state, "_dr_tools", None)
        if dr_tools:

            async def generate_deep_research():
                """Run DeepResearchAgent in thread, stream progress + result."""
                import queue
                import threading

                from nova_ai.agents.deep_research import DeepResearchAgent

                progress_q: queue.Queue = queue.Queue()
                # Set when the SSE consumer gives up on the worker (queue
                # timeout or client disconnect). _run_agent checks it before
                # storing the response so a dead stream doesn't get a late
                # write, and the thread can wind down at its next checkpoint.
                _dr_cancelled: Dict[str, bool] = {"stop": False}

                # Log query start
                _dr_start = time.time()
                try:
                    manager.add_learning_log(
                        agent_id,
                        "query_start",
                        f"Query: {user_content[:100]}",
                        {"full_query": user_content},
                    )
                except Exception as _log_exc:
                    logger.warning(
                        "Failed to log query_start: %s",
                        _log_exc,
                    )

                # Patch the agent's tool executor to emit progress
                dr_agent = DeepResearchAgent(
                    engine=engine,
                    model=model,
                    tools=dr_tools,
                    max_turns=int(config.get("max_turns", 8)),
                    temperature=float(config.get("temperature", 0.3)),
                    interactive=True,
                    confirm_callback=lambda _prompt: True,
                )

                # Wrap the executor to capture tool calls
                original_execute = dr_agent._executor.execute

                def _tracked_execute(tc):
                    tool_name = tc.name
                    full_args = tc.arguments or ""
                    args_str = full_args[:80]
                    # Log tool call start
                    try:
                        manager.add_learning_log(
                            agent_id,
                            "tool_call",
                            f"Calling {tool_name}: {args_str}",
                            {"tool": tool_name, "arguments": full_args},
                        )
                    except Exception as _tc_exc:
                        logger.warning("Log tool_call failed: %s", _tc_exc)

                    progress_q.put(
                        {
                            "type": "tool_start",
                            "tool": tool_name,
                            "args": args_str,
                            "full_args": full_args,
                        }
                    )
                    _tool_start = time.monotonic()
                    result = original_execute(tc)
                    _tool_latency_ms = (time.monotonic() - _tool_start) * 1000

                    # Log tool result
                    try:
                        _ok = "succeeded" if result.success else "failed"
                        _clen = len(result.content) if result.content else 0
                        manager.add_learning_log(
                            agent_id,
                            "tool_result",
                            f"{tool_name} {_ok} ({_clen} chars)",
                            {
                                "tool": tool_name,
                                "success": result.success,
                                "output_length": _clen,
                            },
                        )
                    except Exception as _tr_exc:
                        logger.warning("Log tool_result failed: %s", _tr_exc)

                    progress_q.put(
                        {
                            "type": "tool_end",
                            "tool": tool_name,
                            "arguments": full_args,
                            "success": result.success,
                            "latency": _tool_latency_ms,
                            "result": result.content or "",
                        }
                    )
                    return result

                dr_agent._executor.execute = _tracked_execute

                def _run_agent():
                    agent_metadata = {}
                    try:
                        result = dr_agent.run(user_content)
                        content = result.content or "No results found."
                        agent_metadata = result.metadata or {}
                    except Exception as exc:
                        content = f"Error: {exc}"

                    elapsed = time.time() - _dr_start

                    if _dr_cancelled["stop"]:
                        # The SSE consumer timed out or disconnected; the
                        # stream that would receive this response is gone.
                        # Skip the late store/log so we don't resurrect a
                        # truncated conversation as complete.
                        logger.info(
                            "Deep-research worker finished after consumer "
                            "stopped for agent %s; discarding result",
                            agent_id,
                        )
                        return

                    # Log BEFORE queue put (put triggers SSE end)
                    try:
                        is_err = content.startswith("Error:")
                        manager.add_learning_log(
                            agent_id,
                            "query_error" if is_err else "query_complete",
                            f"{'Error' if is_err else 'Response'}: "
                            f"{len(content)} chars in {elapsed:.1f}s",
                            {
                                "response_length": len(content),
                                "elapsed_seconds": round(elapsed, 2),
                            },
                        )
                    except Exception as _qc_exc:
                        logger.warning(
                            "Log failed: %s",
                            _qc_exc,
                        )

                    progress_q.put(
                        {
                            "type": "error" if content.startswith("Error:") else "done",
                            "content": content,
                            "metadata": agent_metadata,
                            "elapsed": elapsed,
                        }
                    )

                thread = threading.Thread(target=_run_agent, daemon=True)
                thread.start()

                # Collect tool calls from deep-research so we can persist them
                # alongside the final response (and the UI can re-render them
                # after a page reload).
                dr_tool_calls: List[Dict[str, Any]] = []
                _pending_dr_starts: Dict[str, str] = {}

                try:
                    # Stream progress events and final content
                    while True:
                        try:
                            event = await asyncio.to_thread(
                                progress_q.get, timeout=_DR_QUEUE_TIMEOUT_S
                            )
                        except Exception:
                            # Queue timeout — the worker is wedged. Tell the
                            # client, then STOP the thread from piling more
                            # work onto a dead SSE stream: mark it so
                            # _run_agent's late store_agent_response is a
                            # no-op and the process can be reaped (#517).
                            _dr_cancelled["stop"] = True
                            yield _sse_chunk(chunk_id, model, "Agent timed out.")
                            break

                        if event["type"] == "tool_start":
                            tool = event["tool"]
                            args = event.get("args", "")
                            full_args = event.get("full_args", "")
                            _pending_dr_starts[tool] = full_args
                            # Structured event so the UI can render a tool_call
                            # message card (same shape as the non-DR path).
                            _start_payload = json.dumps(
                                {"tool": tool, "arguments": full_args}
                            )
                            yield f"event: tool_call_start\ndata: {_start_payload}\n\n"
                            # Keep the human-readable progress label for the
                            # thinking-bubble fallback.
                            label = _tool_progress_label(tool, args)
                            progress_data = {
                                "id": chunk_id,
                                "object": "chat.completion.chunk",
                                "model": model,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {},
                                        "finish_reason": None,
                                        "tool_progress": label,
                                    }
                                ],
                            }
                            yield f"data: {json.dumps(progress_data)}\n\n"

                        elif event["type"] == "tool_end":
                            tool = event["tool"]
                            dr_tool_calls.append(
                                {
                                    "tool": tool,
                                    "arguments": event.get(
                                        "arguments", _pending_dr_starts.get(tool, "")
                                    ),
                                    "result": event.get("result", ""),
                                    "success": bool(event.get("success", False)),
                                    "latency": float(event.get("latency", 0.0)),
                                }
                            )
                            _pending_dr_starts.pop(tool, None)
                            _end_payload = json.dumps(
                                {
                                    "tool": tool,
                                    "success": bool(event.get("success", False)),
                                    "latency": float(event.get("latency", 0.0)),
                                    "result": event.get("result", ""),
                                }
                            )
                            yield f"event: tool_call_end\ndata: {_end_payload}\n\n"

                        elif event["type"] in ("done", "error"):
                            content = event["content"]
                            meta = event.get("metadata", {})
                            elapsed_s = event.get("elapsed", 0)

                            # Stream content word-by-word
                            words = content.split(" ")
                            for i, word in enumerate(words):
                                token = word if i == 0 else " " + word
                                yield _sse_chunk(chunk_id, model, token)

                            # Build usage + telemetry
                            prompt_tok = meta.get("prompt_tokens", 0)
                            comp_tok = meta.get("completion_tokens", 0)
                            total_tok = meta.get("total_tokens", 0)
                            word_count = len(words)
                            speed = (
                                round(word_count / elapsed_s) if elapsed_s > 0 else 0
                            )

                            # Final chunk with usage + telemetry
                            finish_data = {
                                "id": chunk_id,
                                "object": "chat.completion.chunk",
                                "model": model,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {},
                                        "finish_reason": "stop",
                                    }
                                ],
                                "usage": {
                                    "prompt_tokens": prompt_tok,
                                    "completion_tokens": comp_tok,
                                    "total_tokens": total_tok
                                    or (prompt_tok + comp_tok),
                                },
                                "telemetry": {
                                    "engine": "ollama",
                                    "model_id": model,
                                    "total_ms": round(elapsed_s * 1000),
                                    "tokens_per_sec": speed,
                                    "tool_calls": len(meta.get("sources", [])),
                                },
                            }
                            yield f"data: {json.dumps(finish_data)}\n\n"
                            yield "data: [DONE]\n\n"

                            # Persist (with the tool calls captured during
                            # the deep-research turn so they survive reload).
                            manager.store_agent_response(
                                agent_id,
                                content,
                                tool_calls=dr_tool_calls or None,
                            )
                            break
                finally:
                    # If the client disconnects (GeneratorExit) or the queue
                    # timeout above fired, the daemon worker would otherwise
                    # keep calling the model forever and try to store a
                    # response into a dead stream. Flag it so the late
                    # store_agent_response no-ops (#517). A daemon thread
                    # cannot be force-killed; the flag is the clean lever.
                    _dr_cancelled["stop"] = True

            return StreamingResponse(
                generate_deep_research(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )

    # Build extra kwargs for stream_full (e.g. tools from config).
    # Template stores tool names as strings; convert to OpenAI function specs
    # so the engine can actually bind them to the model.
    stream_kwargs: Dict[str, Any] = {}
    resolved_tools = _resolve_tool_specs(config.get("tools"))
    if resolved_tools:
        stream_kwargs["tools"] = resolved_tools

    # Forward any per-agent sampler params (repetition_penalty, top_p, …) so
    # locally-hosted models can be tuned per agent (#386).
    stream_kwargs.update(_sampler_kwargs(config))

    # Discover MCP tools and merge into stream_kwargs
    mcp_adapters: Dict[str, Any] = {}
    if app_state is not None:
        try:
            mcp_openai_tools, mcp_adapters = _get_mcp_tools(app_state)
            if mcp_openai_tools:
                existing_tools = stream_kwargs.get("tools", [])
                stream_kwargs["tools"] = existing_tools + mcp_openai_tools
                logger.info(
                    "Added %d MCP tools to streaming request",
                    len(mcp_openai_tools),
                )
        except Exception as exc:
            logger.warning(
                "Failed to get MCP tools for streaming: %s", exc, exc_info=True
            )

    # Shared state between the generator and the BackgroundTask that
    # runs after the SSE response completes (or the client disconnects
    # mid-stream). Starlette guarantees the BackgroundTask runs in both
    # cases, so we use it as the single, reliable persistence point.
    persist_state: Dict[str, Any] = {
        "content": "",
        "tool_calls": [],
        "persisted": False,
    }

    def _persist_final() -> None:
        if persist_state["persisted"]:
            return
        persist_state["persisted"] = True
        if persist_state["content"]:
            try:
                manager.store_agent_response(
                    agent_id,
                    persist_state["content"],
                    tool_calls=persist_state["tool_calls"] or None,
                )
            except Exception as store_exc:
                logger.error(
                    "Failed to store agent response: %s",
                    store_exc,
                    exc_info=True,
                )
        try:
            content = persist_state["content"] or ""
            manager.add_learning_log(
                agent_id,
                "query_complete",
                f"Response: {len(content)} chars, "
                f"{len(persist_state['tool_calls'])} tool calls",
                {
                    "response_length": len(content),
                    "tool_calls": len(persist_state["tool_calls"]),
                },
            )
        except Exception as _qc_exc:
            logger.warning("Log query_complete failed: %s", _qc_exc)

    async def generate():
        """Async generator yielding SSE-formatted chunks with real token streaming."""

        collected_content = ""
        collected_tool_calls: List[Dict[str, Any]] = []
        messages_for_llm = list(llm_messages)
        turns = 0

        _query_start_ts = time.time()
        try:
            manager.add_learning_log(
                agent_id,
                "query_start",
                f"Query: {user_content[:100]}",
                {"full_query": user_content},
            )
        except Exception as _qs_exc:
            logger.warning("Log query_start failed: %s", _qs_exc)

        while turns < max_turns:
            turns += 1
            turn_content = ""
            tool_call_fragments: Dict[int, Dict[str, Any]] = {}
            current_finish_reason = None

            try:
                async for chunk in engine.stream_full(
                    messages_for_llm,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **stream_kwargs,
                ):
                    # Stream content tokens immediately to the client
                    if chunk.content:
                        turn_content += chunk.content
                        # Mirror partial content so a disconnect during
                        # generation still saves what we've produced.
                        persist_state["content"] = collected_content + turn_content
                        chunk_data = {
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "model": model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": chunk.content},
                                    "finish_reason": None,
                                }
                            ],
                        }
                        yield f"data: {json.dumps(chunk_data)}\n\n"

                    # Accumulate tool_call fragments
                    if chunk.tool_calls:
                        _merge_tool_call_fragments(
                            tool_call_fragments,
                            chunk.tool_calls,
                        )

                    if chunk.finish_reason:
                        current_finish_reason = chunk.finish_reason

            except Exception as exc:
                logger.error("Managed agent stream error: %s", exc, exc_info=True)
                error_data = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": f"Error: {exc}"},
                            "finish_reason": "stop",
                        }
                    ],
                }
                yield f"data: {json.dumps(error_data)}\n\n"
                yield "data: [DONE]\n\n"
                return

            # Handle tool calls: execute tools and loop for next turn
            if tool_call_fragments and current_finish_reason == "tool_calls":
                # Build the assistant message with tool_calls
                sorted_tcs = [
                    tool_call_fragments[i] for i in sorted(tool_call_fragments.keys())
                ]

                # Add assistant message with tool_calls to conversation
                assistant_msg = Message(
                    role=Role.ASSISTANT,
                    content=turn_content or None,
                    tool_calls=[
                        MsgToolCall(
                            id=tc["id"],
                            name=tc["function"]["name"],
                            arguments=tc["function"]["arguments"],
                        )
                        for tc in sorted_tcs
                    ],
                )
                messages_for_llm.append(assistant_msg)

                # Execute each tool call and append results. Emit
                # tool_call_start/tool_call_end around each call so the UI
                # can render them live (same event names as the main chat
                # in stream_bridge.py).
                for tc in sorted_tcs:
                    tool_name = tc["function"]["name"]
                    tool_args = tc["function"]["arguments"]
                    tool_result_content = f"Tool '{tool_name}' not available"
                    tool_succeeded = False

                    _start_payload = json.dumps(
                        {"tool": tool_name, "arguments": tool_args}
                    )
                    yield f"event: tool_call_start\ndata: {_start_payload}\n\n"
                    try:
                        manager.add_learning_log(
                            agent_id,
                            "tool_call",
                            f"Calling {tool_name}: {tool_args[:80]}",
                            {"tool": tool_name, "arguments": tool_args or ""},
                        )
                    except Exception as _tc_exc:
                        logger.warning("Log tool_call failed: %s", _tc_exc)
                    tool_start_ms = time.monotonic() * 1000

                    try:
                        # Try MCP adapter first (external tools)
                        mcp_adapter = mcp_adapters.get(tool_name)
                        if mcp_adapter is not None:
                            try:
                                parsed_args = json.loads(tool_args) if tool_args else {}
                            except (json.JSONDecodeError, TypeError):
                                parsed_args = {}
                            # Run tool execution off the event loop so a slow
                            # tool (shell_exec, knowledge_search, …) doesn't
                            # block every other SSE stream and HTTP request.
                            # (#514)
                            result = await asyncio.to_thread(
                                mcp_adapter.execute, **parsed_args
                            )
                        else:
                            from nova_ai.server.agent_manager.common import (
                                _execute_local_tool,
                            )

                            result = await _execute_local_tool(
                                tool_name, tool_args, engine, model, app_state, bus
                            )
                        tool_result_content = result.content
                        tool_succeeded = True
                    except Exception as tool_exc:
                        logger.error(
                            "Tool execution error for %s: %s",
                            tool_name,
                            tool_exc,
                            exc_info=True,
                        )
                        tool_result_content = f"Error executing {tool_name}: {tool_exc}"

                    tool_latency_ms = (time.monotonic() * 1000) - tool_start_ms
                    collected_tool_calls.append(
                        {
                            "tool": tool_name,
                            "arguments": tool_args,
                            "result": tool_result_content,
                            "success": tool_succeeded,
                            "latency": tool_latency_ms,
                        }
                    )
                    # Update the shared persist state so mid-stream
                    # disconnects still capture already-executed tools.
                    persist_state["tool_calls"] = list(collected_tool_calls)
                    try:
                        _ok = "succeeded" if tool_succeeded else "failed"
                        _clen = len(tool_result_content) if tool_result_content else 0
                        manager.add_learning_log(
                            agent_id,
                            "tool_result",
                            f"{tool_name} {_ok} ({_clen} chars)",
                            {
                                "tool": tool_name,
                                "success": tool_succeeded,
                                "output_length": _clen,
                            },
                        )
                    except Exception as _tr_exc:
                        logger.warning("Log tool_result failed: %s", _tr_exc)
                    _end_payload = json.dumps(
                        {
                            "tool": tool_name,
                            "success": tool_succeeded,
                            "latency": tool_latency_ms,
                            "result": tool_result_content,
                        }
                    )
                    yield f"event: tool_call_end\ndata: {_end_payload}\n\n"

                    # Add tool result message to conversation
                    messages_for_llm.append(
                        Message(
                            role=Role.TOOL,
                            content=tool_result_content,
                            tool_call_id=tc["id"],
                            name=tool_name,
                        )
                    )

                # Continue to next turn (loop back to stream_full)
                collected_content += turn_content
                # Mirror to shared state so BackgroundTask can persist
                # even if the client disconnects mid-stream.
                persist_state["content"] = collected_content
                persist_state["tool_calls"] = list(collected_tool_calls)
                continue

            # No tool calls — this is the final response
            collected_content += turn_content
            persist_state["content"] = collected_content
            persist_state["tool_calls"] = list(collected_tool_calls)
            break

        # Final chunk with finish_reason
        final_data = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }
        yield f"data: {json.dumps(final_data)}\n\n"
        yield "data: [DONE]\n\n"

    from starlette.background import BackgroundTask

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        background=BackgroundTask(_persist_final),
    )

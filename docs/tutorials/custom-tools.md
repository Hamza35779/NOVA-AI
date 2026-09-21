---
title: Adding Custom Tools
description: Implement, register, test, and ship a BaseTool from scratch — with a weather API example
---

# Adding Custom Tools

Tools are how NOVA AI agents act on the world. Everything an agent can *do* — reading files, searching the web, running code — is a registered tool. This tutorial walks through building one from scratch: a weather lookup tool that calls a real HTTP API, handles errors cleanly, and shows up in the agent's toolbox.

By the end you will have:

1. A working `BaseTool` implementation registered under `nova_ai.contrib`
2. A test suite for it that runs in CI
3. The tool wired into agents via the CLI and the SDK

!!! tip "Prerequisites"
    - Python 3.10 or later
    - NOVA AI installed: `uv sync --extra dev` from the repository root
    - ~15 minutes

## How tools fit together

Four pieces cooperate to make a tool callable:

| Piece | Where | Role |
|---|---|---|
| [`BaseTool`](../user-guide/tools.md#basetool-abc) | `nova_ai.tools._stubs` | ABC you subclass; exposes a `spec` and an `execute()` |
| [`ToolSpec`](../user-guide/tools.md#toolspec) | `nova_ai.tools._stubs` | Metadata: name, description, JSON-schema parameters |
| [`ToolResult`](../user-guide/tools.md#toolresult) | `nova_ai.core.types` | What `execute()` returns: content, success flag, cost, telemetry |
| [`ToolRegistry`](../user-guide/tools.md#tool-registration) | `nova_ai.core.registry` | Global registry the decorator writes into; agents look tools up here by name |

The flow: the agent model sees every registered tool's **spec** rendered as an OpenAI-style function definition, decides to call one, and the **ToolExecutor** dispatches the call to your `execute()` and wraps the result back into the conversation.

## Step 1 — Define the tool

Create `src/nova_ai/contrib/weather.py`. The `contrib` package is the conventional home for tools that are useful but not core (`nova_ai/tools/` itself is reserved for built-ins):

```python title="src/nova_ai/contrib/weather.py"
"""Weather lookup tool — current conditions via the open-meteo API."""

from __future__ import annotations

import json
from typing import Any

import httpx

from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.tools._stubs import BaseTool, ToolSpec

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


@ToolRegistry.register("weather")
class WeatherTool(BaseTool):
    """Look up current weather for a city."""

    tool_id = "weather"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="weather",
            description=(
                "Get current weather for a city. Returns temperature (C), "
                "apparent temperature, humidity, and wind speed."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City name, e.g. 'Lisbon' or 'Tokyo'.",
                    },
                },
                "required": ["city"],
            },
            category="web",
            timeout_seconds=15.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        city = str(params.get("city", "")).strip()
        if not city:
            return ToolResult(
                tool_name="weather",
                content="No city provided.",
                success=False,
            )

        try:
            geo = httpx.get(
                _GEOCODE_URL,
                params={"name": city, "count": 1},
                timeout=10.0,
            )
            geo.raise_for_status()
            results = geo.json().get("results") or []
            if not results:
                return ToolResult(
                    tool_name="weather",
                    content=f"No city named '{city}' found.",
                    success=False,
                )
            place = results[0]

            forecast = httpx.get(
                _FORECAST_URL,
                params={
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "current": "temperature_2m,apparent_temperature,"
                               "relative_humidity_2m,wind_speed_10m",
                },
                timeout=10.0,
            )
            forecast.raise_for_status()
            current = forecast.json()["current"]
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
            return ToolResult(
                tool_name="weather",
                content=f"Weather lookup failed: {exc}",
                success=False,
            )

        content = (
            f"Weather in {place['name']}, {place.get('country', '')}: "
            f"{current['temperature_2m']}°C "
            f"(feels like {current['apparent_temperature']}°C), "
            f"humidity {current['relative_humidity_2m']}%, "
            f"wind {current['wind_speed_10m']} km/h."
        )
        return ToolResult(
            tool_name="weather",
            content=content,
            success=True,
        )
```

Three conventions worth internalizing from this example:

- **Never raise out of `execute()`.** Return a failed `ToolResult` instead — the agent can read the error text and retry or change approach. An exception would abort the whole turn.
- **Write the description for the model, not for humans.** It is injected verbatim into the function-calling prompt; the model chooses tools based on it. Say what it returns, not how it works.
- **Set a realistic `timeout_seconds`.** The default is 30s; a network call that should take 2s shouldn't be allowed to stall an agent turn for 30.

## Step 2 — Register it

The `@ToolRegistry.register("weather")` decorator is what makes the tool discoverable. But decoration only happens when the module is **imported**, so the package must import it.

Create the contrib package's `__init__.py` that imports your module (following the same guarded pattern as `nova_ai/tools/__init__.py`):

```python title="src/nova_ai/contrib/__init__.py"
"""Community-contributed tools, loaded alongside built-ins."""

from __future__ import annotations

try:
    import nova_ai.contrib.weather  # noqa: F401
except ImportError:
    pass
```

Confirm registration:

```bash
uv run nova tool list | grep weather
# weather  Get current weather for a city...
```

## Step 3 — Exercise it directly

Before wiring it into an agent, run it standalone:

```python
from nova_ai.core.registry import ToolRegistry

tool = ToolRegistry.create("weather")
result = tool.execute(city="Lisbon")
print(result.success, result.content)
# True  Weather in Lisbon, Portugal: 21.3°C (feels like 21.0°C), ...
```

`ToolRegistry.create()` instantiates a registered class; `ToolRegistry.get()` returns the class itself. This is also exactly how the `ToolExecutor` will invoke it mid-agent-turn, so if this works, the agent path works.

## Step 4 — Test it

Tool tests live in `tests/tools/`, mirroring the `src/` layout. Network calls are mocked so the suite runs in CI:

```python title="tests/tools/test_weather.py"
"""Tests for the contrib weather tool."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from nova_ai.core.registry import ToolRegistry


@pytest.fixture
def tool():
    from nova_ai.contrib import weather  # noqa: F401  (triggers registration)

    return ToolRegistry.create("weather")


def _fake_response(payload):
    """Minimal stand-in for an httpx.Response."""
    return SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: payload,
    )


GEO_RESPONSE = {
    "results": [{"name": "Lisbon", "country": "Portugal",
                 "latitude": 38.7, "longitude": -9.1}]
}
FORECAST_RESPONSE = {
    "current": {"temperature_2m": 21.3, "apparent_temperature": 21.0,
                "relative_humidity_2m": 60, "wind_speed_10m": 12.5}
}


class TestWeatherTool:
    def test_registered(self):
        assert ToolRegistry.has("weather")

    def test_success(self, tool):
        def fake_get(url, **kwargs):
            if "geocoding" in url:
                return _fake_response(GEO_RESPONSE)
            return _fake_response(FORECAST_RESPONSE)

        with patch("nova_ai.contrib.weather.httpx.get", side_effect=fake_get):
            result = tool.execute(city="Lisbon")

        assert result.success is True
        assert "21.3" in result.content

    def test_unknown_city_is_failed_result_not_exception(self, tool):
        with patch("nova_ai.contrib.weather.httpx.get",
                   side_effect=_fake_response({"results": []})):
            result = tool.execute(city="Nowhereville")

        assert result.success is False
        assert "Nowhereville" in result.content

    def test_missing_city(self, tool):
        result = tool.execute()
        assert result.success is False

    def test_http_error_is_failed_result(self, tool):
        with patch("nova_ai.contrib.weather.httpx.get",
                   side_effect=httpx.ConnectError("boom")):
            result = tool.execute(city="Lisbon")

        assert result.success is False

        # The error text is agent-readable — it should say what went wrong.
        assert "boom" in result.content
```

```bash
uv run pytest tests/tools/test_weather.py -v
```

!!! note "Why assert on failures?"
    The most common bug in agent tools is not "wrong answer" — it's an unhandled exception that kills the agent turn. Tests for the *failure* paths (unknown city, HTTP error, missing argument) are the ones that save you.

## Step 5 — Use it with agents

### CLI

```bash
# One-off query — the agent decides when to call the tool
nova ask --tools weather "Should I bring an umbrella in Porto today?"

# Verify it's visible to the router
nova tool list
```

### SDK

```python
from nova_ai import Nova

j = Nova(model="qwen3:8b", engine_key="ollama")
try:
    response = j.ask(
        "What's the weather in Tokyo right now?",
        agent="orchestrator",
        tools=["weather"],
    )
    print(response)
finally:
    j.close()
```

The model sees the `weather` spec, emits a call, the executor runs `execute(city="Tokyo")`, and the result text flows back into the model's context for the final answer.

## Security checklist

Before shipping a tool that reaches the outside world, run through this list — the [security guide](../user-guide/security.md) covers each in depth:

- [ ] **No secrets in arguments.** API keys belong in config or the environment, never in `spec.parameters` (the model composes those).
- [ ] **Bound every network call** with an explicit `timeout=` — the tool-level `timeout_seconds` is a backstop, not a substitute.
- [ ] **Validate and coerce inputs.** `params` arrives from model output; treat every value as untrusted. Cast, strip, length-check.
- [ ] **Failed results, not exceptions.** Error text is agent-readable context; tracebacks are turn-killers.
- [ ] **Mark side effects.** If the tool mutates state (sends mail, writes files), set `requires_confirmation=True` in the `ToolSpec` so the executor asks the user first.

## Where to go next

- [`docs/user-guide/tools.md`](../user-guide/tools.md) — the full tools reference: `ToolExecutor` internals, capability gating, description overrides
- [`tutorials/skills-workflow.md`](skills-workflow.md) — packaging recurring tool *sequences* as skills the agent can learn and optimize
- [`architecture/memory.md`](../architecture/memory.md) — how tool results become trace metadata that feeds the learning loop

Once your tool is stable, consider contributing it upstream: open a PR adding the module under `src/nova_ai/contrib/` (or propose it for `src/nova_ai/tools/` if it's broadly useful) with the test file alongside.

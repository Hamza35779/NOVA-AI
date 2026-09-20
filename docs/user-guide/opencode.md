# opencode Integration

Use [opencode](https://opencode.ai) (terminal AI coding agent) with NOVA AI in
both directions:

1. **opencode → NOVA models** — your downloaded Ollama models (and the NOVA
   router) appear inside opencode as the `nova-ai` provider, exactly like any
   cloud model. No extra API keys for local inference.
2. **opencode → NOVA tools** — `nova mcp serve` exposes the NOVA tool
   registry (memory, web search, calculator, …) as an opencode MCP server.

## Quick start

```bash
nova opencode install   # installs opencode CLI when missing (no-op otherwise)
nova opencode init      # writes/merges ./opencode.json
nova serve              # start the backend (another terminal)
nova opencode launch    # open opencode TUI wired to NOVA AI
```

`nova opencode status` shows the health of all three pieces (CLI, server,
config) at any time. Setup scripts (`install.bat`, `scripts/quickstart.sh`,
`scripts/install/install.sh`) already run `install` + `init` for you.

## Connect wizard (like API keys / Ollama)

`nova connect` is the guided place for every integration — data sources,
model keys, Ollama, and now opencode:

```bash
nova connect opencode                  # interactive: install → wire → pick model
nova connect --yes opencode            # scripted (flags go before the source)
nova connect --yes --model phi4:14b opencode
```

The wizard checks the opencode CLI (offers install), merges
`opencode.json`, then lets you switch the default model. Re-run it anytime
to re-wire after pulling new Ollama models.

## Switching models

```bash
nova opencode model --list   # show available NOVA models
nova opencode model          # interactive picker
nova opencode model phi4:14b # switch default (prefix optional)
```

This rewrites only `model`/`small_model` in `opencode.json` — providers,
MCP servers, and permissions are untouched. A non-NOVA `small_model` you
set yourself is left alone.

Reverse direction: NOVA AI can also drive opencode's agentic loop with a
local engine via the built-in `opencode` agent:

```bash
nova ask --agent opencode "refactor the retry helper"
```

## Private (local-only) mode — models without data compromise

Yes: point opencode **only** at NOVA AI and your code never leaves the
machine. Data flow per provider:

| Provider | Where prompts go | Keys needed |
|---|---|---|
| `nova-ai` (Ollama via `nova serve`) | Stays on `127.0.0.1` — local inference | None (keyless loopback) |
| `b.ai`, `openrouter`, … | Their clouds — code leaves the device | API key |

Lock it in one command:

```bash
nova opencode init --local-only
# or: nova connect --local-only --yes opencode
```

This writes `"enabled_providers": ["nova-ai"]` (cloud providers stay
configured but can never be selected) and `"share": "disabled"` (opencode's
`/share` uploads transcripts to opencode.ai — off in this mode).
`nova opencode status` then shows a per-provider residency readout:

- `Provider: nova-ai` — local, code never leaves this machine
- `Provider: b.ai` — CLOUD (disabled) / sharing disabled / LOCAL-ONLY lock

Three residual risks and their mitigations:

1. **NOVA cloud fallback** — if your NOVA config holds cloud keys, the
   router *could* pick a cloud engine. For strict privacy, keep
   `OPENAI_API_KEY`/`ANTHROPIC_API_KEY`/etc. unset so only local engines
   are servable (`nova doctor` shows engine health).
2. **Destructive MCP tools** — `shell_exec`/`code_interpreter` run with
   your user privileges. In opencode set `"permission": {"bash": "ask"}`.
3. **Pasted secrets** — use `nova opencode set-key` (env only); raw keys
   never belong in `opencode.json`.

## How it works

`nova opencode init` writes `./opencode.json` (merged — your own providers,
agents, and permissions are preserved):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "model": "nova-ai/qwen3:8b",
  "provider": {
    "nova-ai": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "NOVA AI (local)",
      "options": {
        "baseURL": "http://127.0.0.1:8000/v1",
        "apiKey": "{env:NOVA_AI_API_KEY}"
      },
      "models": { "qwen3:8b": { "name": "qwen3:8b (via NOVA AI)" } }
    }
  },
  "mcp": {
    "nova-ai-tools": {
      "type": "local",
      "command": ["nova", "mcp", "serve"],
      "enabled": true
    }
  }
}
```

- **Model list is live:** `init` queries `GET /v1/models` on your running
  server and writes the real IDs. With the server down it falls back to the
  `qwen3:8b` starter — re-run `init` after `nova serve` + `ollama pull`.
- **No secrets on disk:** the template references `{env:NOVA_AI_API_KEY}`
  only. Keyless local servers (loopback default) work with the variable
  unset; key-protected servers inherit it from your environment automatically
  since opencode launches with the same env.
- **Your defaults win:** `init` never overwrites an existing
  `model`/`small_model` (pass `--force-model` to switch to NOVA).

## Commands

| Command | What it does |
|---|---|
| `nova opencode status` | CLI version, server reachability + models, config presence |
| `nova opencode install [--dry-run]` | Install opencode (npm / install script / brew / choco guidance per OS) |
| `nova opencode init [--server-url URL] [--no-mcp] [--force-model] [--dir DIR]` | Write/merge `opencode.json` |
| `nova opencode model [--list] [ID]` | Show or switch opencode's default NOVA model |
| `nova opencode launch ["prompt"]` | Open the TUI, or run one headless prompt |
| `nova opencode setup` | Guided setup wizard: install → init → pick model |
| `nova connect opencode` | Guided wizard: install → wire → pick model |
| `nova mcp serve` | Serve NOVA tools over MCP stdio (used by opencode) |
| `nova mcp tools` | List the tools `mcp serve` exposes |

## Using NOVA tools inside opencode

Once `init` has wired the MCP server, prompt with the server name:

> Summarize my unread mail. use nova-ai-tools

Disable noisy tools globally with a glob (opencode convention):

```jsonc
{ "tools": { "nova-ai-tools_channel*": false } }
```

> **Execution tools are gated by opencode, not NOVA here.** The MCP list
> includes `shell_exec`, `code_interpreter`, and `git_manager`. opencode
> allows all operations by default — set `"permission": {"bash": "ask"}`
> (or per-tool denies like `"nova-ai-tools_shell_exec": false`) unless you
> want the agent running shell commands unattended. Same caution as
> `nova`'s own confirmation gates.

## Troubleshooting

- **`nova-ai/*` calls fail with connection refused** — `nova serve` isn't
  running. Start it, then retry. `nova opencode status` confirms.
- **Model ID not found** — you pulled a new Ollama model after `init`.
  Re-run `nova opencode init` to refresh the list.
- **401 Invalid API key** — your server sets `NOVA_AI_API_KEY` but opencode's
  environment doesn't have it. Export it in the same terminal before launch.
- **`nova` not found by opencode MCP** — the `nova` console script isn't on
  PATH (source checkout without install). Re-run `init` from a terminal
  where `nova` resolves, or `pip install -e .` the checkout; `init` falls
  back to `python -m nova_ai.cli mcp serve` automatically.
- **Windows native (non-WSL)** — prefer `npm install -g opencode-ai`;
  `nova opencode install` picks this automatically when npm exists.

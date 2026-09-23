# CLI Reference (auto-generated)

```text
Usage: python -m nova_ai.cli [OPTIONS] [COMMAND] [ARGS]...

  NOVA AI — modular AI assistant backend

Options:
  --version  Show the version and exit.
  --verbose  Enable debug logging
  --quiet    Suppress non-error output
  --help     Show this message and exit.

Commands:
  add                  Add an MCP server configuration
  agents               Manage persistent agents — create, inspect, chat, bin
  ask                  Ask Nova a question
  auth                 Manage authentication credentials for connectors
  bench                Run inference benchmarks
  canvas               Manage interactive Canvas visual artifacts
  channel              Manage messaging channels
  channels             Manage messaging channels (iMessage/SMS via SendBlue,
  chat                 Start an interactive multi-turn chat session
  clip                 Clipboard AI — quickly summarize, translate, or expla
  compose              Compose, run, benchmark, and deploy NOVA AI configura
  config               Inspect configuration — show loaded settings, hardwar
  connect              Manage connections (Gmail, Obsidian, opencode, etc.)
  conversation         Conversation trees: forks, sibling answers, preferenc
  deep-research-setup  Configure local deep-research sources (Obsidian vault
  dev-watch            Watch a build/test command and self-diagnose failures
  digest               Display and play the morning digest
  doctor               Run diagnostic checks on your NOVA AI installation
  eval                 Evaluation framework — benchmark models, agents, and
  feedback             Trace feedback management
  forge                Forge skills from your repeated multi-step tool workf
  gateway              Manage the NOVA AI multi-channel gateway
  host                 Download (if needed) and serve a model locally
  init                 Detect hardware and generate ~/.nova_ai/config.toml
  integrations         Manage app integrations, software connectors, and MCP
  logs                 Show NOVA AI log files (server daemon + CLI); -f to f
  mcp                  Serve or inspect NOVA AI tools via MCP (e.g. for open
  memory               Manage the memory store
  memory-wiki          Manage structured Memory Wiki knowledge base
  mine                 Configure and run Pearl mining
  model                Manage language models
  opencode             Integrate opencode (AI coding agent) with NOVA AI mod
  operators            Manage operators — persistent, scheduled autonomous a
  optimize             LLM-driven configuration optimization
  oracle               Fleet Oracle: pooled, anonymized performance answers
  pearl                Access Pearl node, wallet, and RPC tools
  plugin               Scaffold NOVA AI plugins
  prove                Prove whether a new model actually beats the incumben
  quickstart           Guided 5-step setup for new users
  registry             Inspect registered components — list registries, show
  research             Run multi-hop deep research with citations
  restart              Restart the NOVA AI server daemon
  router               Smart Model Router commands
  scan                 Audit your environment for privacy and security risks
  scheduler            Manage scheduled tasks
  screen               Screen perception and OCR tools
  self-update          Upgrade NOVA AI to the latest release. Detects how yo
  serve                Start the OpenAI-compatible API server
  skill                Manage reusable skills
  start                Start the NOVA AI server as a background daemon
  status               Show status of the NOVA AI server daemon
  stop                 Stop the running NOVA AI server daemon
  telemetry            Query and manage inference telemetry data
  tool                 Manage tools — list, inspect
  train                Self-training: fine-tune a model from your own usage
  tunnel               Expose the local API server via a Cloudflare Tunnel
  vault                Manage encrypted credentials
  voice                Start a voice conversation with Nova
  workflow             Manage workflows — list, run, status

```

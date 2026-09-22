# Scripts

| Script | Purpose |
|---|---|
| `quickstart.sh` | One-command local setup (Python 3.10–3.13, Node 22+, Ollama + starter model) |
| `install/` | Windows / POSIX installers |
| `gen-cli-docs.py` | Regenerates `docs/cli/` from `nova --help` (run in CI to stop CLI-doc rot) |
| `check-versions.sh` | Fails if stale installer version or agent count strings reappear |

Run `shellcheck scripts/*.sh` before committing shell changes.

## `install/` helper scripts

| Script | Purpose | Notes |
|---|---|---|
| `install.sh` | POSIX one-liner installer (`curl … \| bash`) | Installs uv, syncs Python deps, delegates background work to `bg-orchestrator.sh`, symlinks the `nova` CLI |
| `install-rust.sh` | Installs the Rust toolchain via rustup if `cargo` is missing | Idempotent — exits 0 when cargo is already on PATH |
| `build-extension.sh` | Builds the `nova_ai_rust` maturin extension into the venv | Writes `extension-built` / `extension-failed` markers under `$NOVA_AI_HOME/.state/` |
| `pull-model.sh` | Pulls an Ollama model with state-file lifecycle | Usage: `pull-model.sh <model-id>`; state under `$NOVA_AI_HOME/.state/models/` |
| `nova-wrapper.sh` | Symlinked to `~/.local/bin/nova` | Activates the managed venv and execs the real `nova` CLI |
| `bg-orchestrator.sh` | Detached parent of all background install work | Runs Rust install + extension build sequentially, model pulls in parallel; spawned by `install.sh` via `nohup … & disown` |
| `nova-uninstall.sh` | Clean removal of NOVA AI from `$HOME` | Removes `~/.nova_ai/` and `~/.local/bin/nova` |

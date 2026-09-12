# Scripts

| Script | Purpose |
|---|---|
| `quickstart.sh` | One-command local setup (Python 3.10–3.13, Node 22+, Ollama + starter model) |
| `install/` | Windows / POSIX installers |
| `gen-cli-docs.py` | Regenerates `docs/cli/` from `nova --help` (run in CI to stop CLI-doc rot) |
| `check-versions.sh` | Fails if stale installer version or agent count strings reappear |

Run `shellcheck scripts/*.sh` before committing shell changes.

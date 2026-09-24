#!/usr/bin/env bash
# nova-wrapper.sh — symlinked to ~/.local/bin/nova.
# Activates the managed venv and execs the real nova CLI.

NOVA_AI_HOME="${NOVA_AI_HOME:-$HOME/.nova_ai}"
VENV="$NOVA_AI_HOME/.venv"

if [[ ! -d "$VENV" ]]; then
    echo "nova: venv not found at $VENV" >&2
    echo "Re-run the installer: curl -fsSL https://raw.githubusercontent.com/Hamza35779/NOVA-AI/main/scripts/install/install.sh | bash" >&2
    exit 1
fi

exec "$VENV/bin/nova" "$@"

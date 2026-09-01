#!/usr/bin/env bash
# nova-uninstall.sh — clean removal of NOVA AI from $HOME.
#
# Removes:
#   ~/.nova_ai/
#   ~/.local/bin/nova
#   ~/.local/bin/nova-uninstall
#
# Does NOT remove: ollama, uv, or the Rust toolchain.

set -euo pipefail

NOVA_AI_HOME="${NOVA_AI_HOME:-$HOME/.nova_ai}"

if [[ -f "$NOVA_AI_HOME/.state/bg.pid" ]]; then
    pid=$(cat "$NOVA_AI_HOME/.state/bg.pid" 2>/dev/null || echo "")
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        echo "Stopping background work (pid=$pid)..."
        kill "$pid" 2>/dev/null || true
    fi
fi

if command -v ollama >/dev/null 2>&1; then
    ollama stop >/dev/null 2>&1 || true
fi

if [[ -d "$NOVA_AI_HOME" ]]; then
    rm -rf "$NOVA_AI_HOME"
    echo "Removed $NOVA_AI_HOME"
fi

for f in "$HOME/.local/bin/nova" "$HOME/.local/bin/nova-uninstall"; do
    if [[ -L "$f" ]] || [[ -f "$f" ]]; then
        rm -f "$f"
        echo "Removed $f"
    fi
done

cat <<EOF

NOVA AI removed.

Left intact (may be used by other tools):
  - Ollama       (uninstall: brew uninstall ollama  /  rm -f /usr/local/bin/ollama)
  - uv           (uninstall: rm -rf ~/.local/share/uv ~/.cargo/bin/uv)
  - Rust toolchain (uninstall: rustup self uninstall)
EOF

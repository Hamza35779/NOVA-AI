#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
export PYTHONPATH="$DIR/src:$PYTHONPATH"

echo "======================================================="
echo "              NOVA AI - Personal AI Assistant          "
echo "======================================================="
echo ""

if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
    echo "[ERROR] Python 3 is not installed."
    echo "Please install Python 3.10+ using your package manager (apt, brew, dnf)."
    exit 1
fi

PY_BIN="$(command -v python3 || command -v python)"

# The menu runs nova_ai from the system Python. If the package isn't
# installed there, every option would crash with ModuleNotFoundError —
# fail up front with the fix instead (first-run onboarding bug).
if ! "$PY_BIN" -c "import nova_ai" >/dev/null 2>&1; then
    echo "[ERROR] The 'nova_ai' package is not installed for: $PY_BIN"
    if [ -x "$DIR/.venv/Scripts/python.exe" ]; then
        echo "A project venv exists at $DIR/.venv — activate it first, then re-run this script:"
        echo "  source \"$DIR/.venv/Scripts/activate\""
    elif [ -x "$DIR/.venv/bin/python" ]; then
        echo "A project venv exists at $DIR/.venv — activate it first, then re-run this script:"
        echo "  source \"$DIR/.venv/bin/activate\""
    else
        echo "Install dependencies first (from the repo root):"
        echo "  uv sync --extra server --extra tools-search"
        echo "  or: python -m venv .venv && source .venv/bin/activate && pip install -e '.[server,tools-search]'"
        echo "Then re-run ./start.sh (Windows: start.bat)."
    fi
    exit 1
fi

echo "Choose an option to start:"
echo "1) Interactive Chat (CLI)"
echo "2) Voice Conversation Mode (Speak with Nova)"
echo "3) Web/Desktop Backend Server (API & UI)"
echo "4) Memory Wiki Manager"
echo "5) Run System Diagnostics (doctor)"
echo "6) Exit"
echo ""
read -p "Enter option (1-6) [default: 1]: " choice
choice=${choice:-1}

case $choice in
    1)
        echo "Starting NOVA AI Chat..."
        "$PY_BIN" -m nova_ai.cli chat
        ;;
    2)
        echo "Starting Voice Mode..."
        "$PY_BIN" -m nova_ai.cli voice
        ;;
    3)
        echo "Starting NOVA AI Server at http://127.0.0.1:8000..."
        "$PY_BIN" -m nova_ai.cli serve
        ;;
    4)
        "$PY_BIN" -m nova_ai.cli memory-wiki list
        echo ""
        "$PY_BIN" -m nova_ai.cli memory-wiki show profile
        ;;
    5)
        "$PY_BIN" -m nova_ai.cli doctor
        ;;
    *)
        exit 0
        ;;
esac

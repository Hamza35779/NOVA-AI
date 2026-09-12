# NOVA AI task runner (requires `just`: https://just.systems)
# Wraps uv + pytest + npm so Windows/WSL2/macOS share one interface.

init:
  uv sync --extra dev
  cd frontend && npm ci

dev:
  nova serve & cd frontend && npm run dev

test:
  pytest -m "not live and not cloud and not hub and not slow" -q
  cd frontend && npm run test -- --coverage

test-slow:
  pytest -m "slow" -q

lint:
  ruff check src tests
  ruff format --check src tests
  cd frontend && npm run lint

typecheck:
  .venv/Scripts/python.exe -m mypy src/nova_ai/core src/nova_ai/security src/nova_ai/engine || python3 -m mypy src/nova_ai/core src/nova_ai/security src/nova_ai/engine
  cd frontend && npm run typecheck

bench:
  pytest tests/bench -q

docs:
  mkdocs serve

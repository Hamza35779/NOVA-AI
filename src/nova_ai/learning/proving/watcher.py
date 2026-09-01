"""New-model detection and auto-prove gating.

The watcher keeps a snapshot of every locally visible model in
``known_models.json``. When ``discover_models()`` surfaces a name the
snapshot has never seen, that model is "new" — a candidate for the proving
ground. Auto-proving additionally requires ``[learning.proving] enabled``
AND ``auto_trigger`` AND no run currently in flight (the same
double-opt-in discipline as the training auto-trigger).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

KNOWN_MODELS_FILENAME = "known_models.json"


def list_local_models(config: Any) -> list[str]:
    """Return the union of model ids visible across all healthy engines."""
    from nova_ai.engine._discovery import discover_engines, discover_models

    try:
        engines = discover_engines(config)
        models = discover_models(engines)
    except Exception as exc:
        logger.warning("Model discovery failed: %s", exc)
        return []
    seen: dict[str, None] = {}
    for _engine_key, model_ids in models.items():
        for mid in model_ids:
            seen.setdefault(mid, None)
    return sorted(seen)


def _load_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {"models": {}}
    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"models": {}}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read model state at %s: %s", state_path, exc)
        return {"models": {}}


def _save_state(state_path: Path, state: dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def detect_new_models(
    *,
    state_path: Path,
    models: list[str],
) -> list[str]:
    """Diff *models* against the snapshot; return newly seen names.

    Updates the snapshot with every current model (new entries get a
    ``first_seen`` timestamp; removed ones are dropped, so a model pulled
    again later counts as new again).
    """
    state_path = Path(state_path)
    state = _load_state(state_path)
    known: dict[str, Any] = state.get("models", {})

    fresh = [m for m in models if m not in known]
    now = datetime.now(timezone.utc).isoformat()
    new_state = {"models": {m: known.get(m, {"first_seen": now}) for m in models}}
    _save_state(state_path, new_state)

    for m in fresh:
        logger.info("New model detected: %s", m)
    return fresh


def maybe_auto_prove(
    *,
    trace_store: Any,
    config: Any,
    run_store: Any,
    proving_root: Path,
    config_obj: Optional[Any] = None,
) -> list[dict[str, Any]]:
    """Run the gauntlet on every new model when allowed to.

    Gates: ``config.enabled`` AND ``config.auto_trigger`` AND no run in
    flight. Returns one summary dict per proven (or skipped) model.
    """
    if not getattr(config, "enabled", False):
        return [{"status": "skipped", "reason": "proving disabled"}]
    if not getattr(config, "auto_trigger", False):
        return [{"status": "skipped", "reason": "auto_trigger disabled"}]
    if run_store.is_running():
        return [{"status": "skipped", "reason": "a proving run is already in flight"}]

    from nova_ai.learning.proving.pipeline import run_proving

    root = Path(proving_root)
    models = list_local_models(config_obj)
    state_path = root / KNOWN_MODELS_FILENAME
    new_models = detect_new_models(state_path=state_path, models=models)

    if not new_models:
        return [{"status": "skipped", "reason": "no new models"}]

    results: list[dict[str, Any]] = []
    for candidate in new_models:
        try:
            record = run_proving(
                candidate=candidate,
                trace_store=trace_store,
                config=config,
                run_store=run_store,
                proving_root=root,
                trigger="auto",
                config_obj=config_obj,
            )
            results.append(
                {
                    "candidate": candidate,
                    "status": record.get("status", "unknown"),
                    "run_id": record.get("id", ""),
                    "adopted": record.get("adopted", {}),
                }
            )
        except Exception as exc:
            logger.warning("Auto-prove for %s failed: %s", candidate, exc)
            results.append(
                {"candidate": candidate, "status": "failed", "error": str(exc)}
            )
    return results


__all__ = [
    "KNOWN_MODELS_FILENAME",
    "detect_new_models",
    "list_local_models",
    "maybe_auto_prove",
]

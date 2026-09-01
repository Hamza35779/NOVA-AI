"""Policy map persistence — the output of the proving ground.

Winners proven by a run are written to ``policy_map.json`` under the
proving root (``~/.nova_ai/learning/proving/``), mapping query class →
the model that should serve it::

    {"code": {"model": "qwen3:8b", "run_id": "prove_…", "margin": 0.12,
              "adopted_at": "…"}}

Adoption is the *only* mutation the proving ground performs on live
behavior, and only happens on ``nova prove adopt`` or with
``[learning.proving] auto_adopt = true``. ``nova prove revert <class>``
removes an entry.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

POLICY_MAP_FILENAME = "policy_map.json"


def _map_path(proving_root: Path) -> Path:
    return Path(proving_root) / POLICY_MAP_FILENAME


def load_policy_map(proving_root: Path) -> dict[str, dict[str, Any]]:
    """Load the policy map, or ``{}`` when absent/corrupt."""
    path = _map_path(proving_root)
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read policy map at %s: %s", path, exc)
        return {}


def save_policy_map(
    policy_map: dict[str, dict[str, Any]], proving_root: Path
) -> Path:
    """Persist the policy map (creating the root if needed)."""
    root = Path(proving_root)
    root.mkdir(parents=True, exist_ok=True)
    path = _map_path(root)
    path.write_text(
        json.dumps(policy_map, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def adopt_winners(
    *,
    run_id: str,
    per_class: dict[str, dict[str, Any]],
    min_margin: float = 0.05,
    proving_root: Path,
) -> dict[str, str]:
    """Write non-incumbent winners from a run into the policy map.

    Only classes where the *candidate* won by at least *min_margin* are
    adopted; incumbent-winning or tied classes are left untouched. Returns
    the ``{query_class: model}`` entries actually written.
    """
    current = load_policy_map(proving_root)
    adopted: dict[str, str] = {}
    for qclass, verdict in per_class.items():
        winner = verdict.get("winner")
        margin = verdict.get("delta", 0.0)
        if winner is None or margin < min_margin:
            continue
        current[qclass] = {
            "model": winner,
            "run_id": run_id,
            "margin": round(float(margin), 4),
            "adopted_at": datetime.now(timezone.utc).isoformat(),
        }
        adopted[qclass] = winner
    if adopted:
        save_policy_map(current, proving_root)
        logger.info(
            "Adopted %d proven winner(s) from run %s: %s",
            len(adopted),
            run_id,
            adopted,
        )
    return adopted


def revert_class(qclass: str, *, proving_root: Path) -> bool:
    """Remove *qclass* from the policy map. Returns True when removed."""
    current = load_policy_map(proving_root)
    if qclass not in current:
        return False
    del current[qclass]
    save_policy_map(current, proving_root)
    logger.info("Reverted routing for query class %r", qclass)
    return True


def proven_model_for(
    query_class: str, *, proving_root: Path
) -> Optional[str]:
    """Return the proven model for *query_class*, or ``None``.

    Read helper for the router; any I/O problem degrades to ``None`` so a
    broken file can never break routing.
    """
    try:
        entry = load_policy_map(proving_root).get(query_class)
    except Exception:  # pragma: no cover - load_policy_map already guards
        return None
    if not entry:
        return None
    return entry.get("model") or None


__all__ = [
    "POLICY_MAP_FILENAME",
    "adopt_winners",
    "load_policy_map",
    "proven_model_for",
    "revert_class",
    "save_policy_map",
]

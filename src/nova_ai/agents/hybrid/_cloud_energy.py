"""Cloud J/token energy estimates for hybrid cells (audit item A3).

GPU energy is measured directly via NVML (see ``_energy.py``), but cloud
calls (Anthropic / OpenAI / Google) have no measurable joules on our side —
the compute happens on vendor hardware.  This module provides a
*documented, conservative estimate* of the datacenter energy attributable
to those cloud tokens so hybrid comparisons don't quietly treat cloud
inference as free.

Why an estimate at all
----------------------
Without it, a cell that offloads most work to the cloud reports ~0 J while
the local cell reports real GPU joules — comparisons read as "cloud is
free", which is false.  The estimate is deliberately **separate** from
``energy_j_total`` (the measured quantity) in every report we emit.

Method (kept simple and auditable)
----------------------------------
``J/token = tokens × J/token-factor`` where the per-token factor already
bakes in a datacenter PUE.  Defaults below are order-of-magnitude
estimates in the spirit of Patterson et al. 2021 ("Carbon Emissions and
Large Neural Network Training") and Luccioni et al. 2022 ("Estimating the
Carbon Footprint of BLOOM"); they are *not* vendor numbers and should not
be quoted as measurements.

- ``anthropic`` / ``openai`` / ``google``: ``2.0e-3`` J/token
- ``default`` (unknown provider): ``2.0e-3`` J/token

``2e-3 J/token`` corresponds to a mid-size hosted model run at a PUE of
~1.2 with roughly 0.6 J/inference-round-trip amortised per 1k tokens —
one to two orders of magnitude below a local GPU second (~40–70 W ≈ 50 J/s)
per token of wall time, which is the honest conclusion: per *token*, cloud
is efficient; per *call*, the round trips add up.

Controls
--------
- ``NOVA_AI_CLOUD_ENERGY=0`` — disable entirely (estimate fields stay 0.0)
- ``NOVA_AI_CLOUD_ENERGY_J_PER_TOKEN=<float>`` — override the default factor

Failure modes are absorbed: a malformed override disables estimation with
a one-time warning; nothing here can crash a cell run.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

DEFAULT_J_PER_TOKEN = 2.0e-3

# Providers seen in hybrid metadata.  Unknown providers fall back to the
# default factor rather than being silently treated as free.
PROVIDER_J_PER_TOKEN: Dict[str, float] = {
    "anthropic": 2.0e-3,
    "openai": 2.0e-3,
    "google": 2.0e-3,
    "default": 2.0e-3,
}

_FACTOR_WARNED = False


def _warn_once(msg: str) -> None:
    global _FACTOR_WARNED
    if not _FACTOR_WARNED:
        print(f"[cloud-energy] {msg}", flush=True)
        _FACTOR_WARNED = True


def enabled() -> bool:
    """Estimation is on unless ``NOVA_AI_CLOUD_ENERGY=0``."""
    return os.environ.get("NOVA_AI_CLOUD_ENERGY", "1") != "0"


def j_per_token(provider: str = "") -> float:
    """Return the estimated joules-per-token factor for *provider*.

    ``NOVA_AI_CLOUD_ENERGY_J_PER_TOKEN`` overrides every provider.
    A malformed override logs once and returns ``0.0`` (estimate disabled)
    — never raises.
    """
    raw = os.environ.get("NOVA_AI_CLOUD_ENERGY_J_PER_TOKEN")
    if raw:
        try:
            return float(raw)
        except ValueError:
            _warn_once(
                f"Invalid NOVA_AI_CLOUD_ENERGY_J_PER_TOKEN={raw!r}; "
                "cloud energy estimation disabled for this run."
            )
            return 0.0
    return PROVIDER_J_PER_TOKEN.get(provider.lower(), DEFAULT_J_PER_TOKEN)


def _row_provider(row: Dict[str, Any]) -> str:
    """Best-effort provider extraction from a hybrid result row."""
    provider = row.get("cloud_provider")
    if isinstance(provider, str) and provider:
        return provider
    traces = row.get("traces")
    if isinstance(traces, dict):
        trace_provider = traces.get("cloud_provider")
        if isinstance(trace_provider, str) and trace_provider:
            return trace_provider
    return ""


def estimate_row_energy_j(row: Dict[str, Any]) -> float:
    """Estimated cloud joules attributable to one result row."""
    if not enabled():
        return 0.0
    tokens = int(row.get("tokens_cloud", 0) or 0)
    if tokens <= 0:
        return 0.0
    return tokens * j_per_token(_row_provider(row))


def estimate_summary_energy_j(rows: Any) -> float:
    """Estimated cloud joules across all result rows."""
    if not enabled():
        return 0.0
    total = 0.0
    for row in rows:
        total += estimate_row_energy_j(row)
    return total


def summary_note() -> str:
    """Human-readable provenance note for reports/summary fields."""
    override = os.environ.get("NOVA_AI_CLOUD_ENERGY_J_PER_TOKEN")
    if override:
        return f"estimate (NOVA_AI_CLOUD_ENERGY_J_PER_TOKEN={override})"
    if not enabled():
        return "disabled (NOVA_AI_CLOUD_ENERGY=0)"
    return "estimate (Patterson 2021 / Luccioni 2022 spirit; NOT a measurement)"


__all__ = [
    "DEFAULT_J_PER_TOKEN",
    "PROVIDER_J_PER_TOKEN",
    "enabled",
    "estimate_row_energy_j",
    "estimate_summary_energy_j",
    "j_per_token",
    "summary_note",
]

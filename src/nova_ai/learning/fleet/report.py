"""Fleet Oracle — report building (the only data that ever leaves the machine).

``build_report`` aggregates anonymized hardware + per-model performance
stats from local telemetry. The output shape is a **fixed field list**:
no prompts, no content, no paths, no user IDs, no timestamps beyond the
window size. Everything else in the feature reads these files.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from nova_ai.core.config import NovaConfig

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


def _hardware_payload(config_obj: NovaConfig) -> Dict[str, Any]:
    """Fixed hardware fields — nothing else about the machine."""
    hw = config_obj.hardware
    gpu: Optional[Dict[str, Any]] = None
    if hw.gpu is not None:
        gpu = {
            "vendor": hw.gpu.vendor,
            "name": hw.gpu.name,
            "vram_gb": round(float(hw.gpu.vram_gb), 1),
        }
    return {
        "platform": hw.platform,
        "cpu_count": hw.cpu_count,
        "ram_gb": round(float(hw.ram_gb), 1),
        "gpu": gpu,
    }


def _model_payload(stats, min_calls: int) -> Optional[Dict[str, Any]]:
    """Fixed per-model fields, or None when k-anonymity drops the model."""
    if stats.call_count < min_calls:
        return None
    return {
        "model_id": stats.model_id,
        "engine": getattr(stats, "engine", "") or "",
        "call_count": stats.call_count,
        "avg_latency_s": round(float(stats.avg_latency), 3),
        "avg_ttft_s": round(float(stats.avg_ttft), 3),
        "avg_throughput_tok_per_sec": round(
            float(stats.avg_throughput_tok_per_sec), 2
        ),
        "avg_tokens_per_joule": round(float(stats.avg_tokens_per_joule), 2),
        "total_tokens": stats.total_tokens,
    }


def build_report(
    *,
    config_obj: NovaConfig,
    since_days: Optional[int] = None,
    min_calls_per_model: Optional[int] = None,
) -> Dict[str, Any]:
    """Build an anonymized fleet report from local telemetry.

    Parameters
    ----------
    config_obj :
        The loaded ``NovaConfig`` (hardware is read from
        ``config_obj.hardware``, telemetry db from ``config_obj.telemetry.db_path``).
    since_days :
        Aggregation window override; default ``learning.fleet.since_days``.
    min_calls_per_model :
        k-anonymity threshold override; default
        ``learning.fleet.min_calls_per_model``.

    Returns
    -------
    dict
        ``{schema_version, report_id, generated_at, hardware, models,
        window_days}``. ``models`` is sorted by call_count desc. The
        ``report_id`` is a stable pseudonym of the hardware fingerprint —
        it lets the fleet dedupe reports without identifying the user.
    """
    fleet_cfg = config_obj.learning.fleet
    window_days = int(since_days if since_days is not None else fleet_cfg.since_days)
    min_calls = int(
        min_calls_per_model
        if min_calls_per_model is not None
        else fleet_cfg.min_calls_per_model
    )

    from nova_ai.analytics.redaction import hash_id
    from nova_ai.telemetry.aggregator import TelemetryAggregator

    hardware = _hardware_payload(config_obj)

    # Stable pseudonym: same machine shape -> same id, nothing reversible.
    gpu_part = ""
    if hardware["gpu"]:
        gpu_part = f"|{hardware['gpu']['vendor']}|{hardware['gpu']['name']}"
    report_id = hash_id(
        f"{hardware['platform']}|{hardware['cpu_count']}"
        f"|{hardware['ram_gb']}{gpu_part}"
    )

    since_ts = time.time() - window_days * 86400
    models: List[Dict[str, Any]] = []
    aggregator = TelemetryAggregator(config_obj.telemetry.db_path)
    try:
        for stats in aggregator.per_model_stats(since=since_ts):
            payload = _model_payload(stats, min_calls)
            if payload is not None:
                models.append(payload)
    except Exception as exc:  # no telemetry table / unreadable db → empty report
        logger.debug("Fleet report telemetry aggregation failed: %s", exc)
    finally:
        aggregator.close()

    models.sort(key=lambda m: (-m["call_count"], m["model_id"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "report_id": report_id,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "window_days": window_days,
        "hardware": hardware,
        "models": models,
    }


__all__ = ["SCHEMA_VERSION", "build_report"]

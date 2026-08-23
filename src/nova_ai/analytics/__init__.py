"""External anonymous usage analytics.

Sends anonymized events to PostHog so the NOVA AI team can measure
setup success, retention, feature usage, and churn — without ever
collecting chat content, prompts, file paths, emails, IPs, or hardware
identifiers.

Distinct from :mod:`nova_ai.telemetry`, which stores local FLOPs and
energy metrics in a SQLite DB and never leaves the machine.

Disable: set ``[analytics] enabled = false`` in ``~/.nova_ai/config.toml``.
"""

from nova_ai.analytics.aggregator import SessionAggregator
from nova_ai.analytics.bridge import EventBridge
from nova_ai.analytics.client import AnalyticsClient
from nova_ai.analytics.identity import (
    get_or_create_anon_id,
    is_analytics_enabled,
    reset_anon_id,
)
from nova_ai.analytics.redaction import hash_id, redact

__all__ = [
    "AnalyticsClient",
    "EventBridge",
    "SessionAggregator",
    "get_or_create_anon_id",
    "is_analytics_enabled",
    "reset_anon_id",
    "redact",
    "hash_id",
]

"""External-framework subprocess backends (Hermes Agent, OpenClaw)."""

from nova_ai.evals.backends.external.hermes_agent import HermesBackend
from nova_ai.evals.backends.external.openclaw import OpenClawBackend

__all__ = ["HermesBackend", "OpenClawBackend"]

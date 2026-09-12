"""Shared retry policy with exponential backoff + jitter.

Fixture from PROJECT_IMPROVEMENTS_EXTENDED.md §10.
Generalizes the per-operator ``max_consecutive_failures`` circuit-breaker
pattern into one reusable helper for jobs, connectors, and engine calls.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class RetryPolicy:
    attempts: int = 3
    base_ms: int = 200
    factor: float = 2.0
    jitter_ms: int = 50


def run_with_retry(
    fn: Callable[[], T],
    policy: RetryPolicy | None = None,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    """Run ``fn`` with exponential-backoff retry.

    Re-raises the last exception after ``policy.attempts`` failures.
    """
    policy = policy or RetryPolicy()
    last_exc: BaseException | None = None
    for i in range(policy.attempts):
        try:
            return fn()
        except retry_on as exc:  # noqa: BLE001 — caller chooses retry_on
            last_exc = exc
            if i == policy.attempts - 1:
                raise
            delay = policy.base_ms / 1000 * policy.factor**i + random.uniform(
                0, policy.jitter_ms / 1000
            )
            logger.debug("retry %d/%d after %.2fs: %s", i + 1, policy.attempts, delay, exc)
            time.sleep(delay)
    assert last_exc is not None  # for type-checkers
    raise last_exc

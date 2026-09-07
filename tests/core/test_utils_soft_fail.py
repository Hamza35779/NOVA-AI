"""Tests for nova_ai.core.utils.soft_fail."""

from __future__ import annotations

import logging

import pytest

from nova_ai.core.utils import soft_fail


@pytest.fixture()
def caplog_debug(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.DEBUG):
        yield caplog


def test_soft_fail_logs_debug_by_default(caplog_debug):
    logger = logging.getLogger("test.soft_fail.default")
    try:
        raise ValueError("boom")
    except ValueError as exc:
        soft_fail(logger, exc, "loading widget")

    assert len(caplog_debug.records) == 1
    record = caplog_debug.records[0]
    assert record.levelno == logging.DEBUG
    assert "loading widget" in record.getMessage()
    assert "ValueError: boom" in record.getMessage()


def test_soft_fail_respects_level(caplog_debug):
    logger = logging.getLogger("test.soft_fail.level")
    try:
        raise RuntimeError("nope")
    except RuntimeError as exc:
        soft_fail(logger, exc, "optional feature", level="warning")

    record = caplog_debug.records[0]
    assert record.levelno == logging.WARNING


def test_soft_fail_includes_exception_type(caplog_debug):
    logger = logging.getLogger("test.soft_fail.type")
    try:
        raise KeyError("missing_key")
    except KeyError as exc:
        soft_fail(logger, exc, "probe")

    assert "KeyError" in caplog_debug.records[0].getMessage()


def test_soft_fail_is_safe_with_chained_exceptions(caplog_debug):
    logger = logging.getLogger("test.soft_fail.chain")
    try:
        try:
            raise OSError("inner")
        except OSError as inner:
            raise ValueError("outer") from inner
    except ValueError as exc:
        soft_fail(logger, exc, "nested")

    assert "ValueError: outer" in caplog_debug.records[0].getMessage()


def test_soft_fail_unknown_level_falls_back_to_debug(caplog_debug):
    """A typo'd level must not raise from inside the never-propagate helper."""
    logger = logging.getLogger("test.soft_fail.badlevel")
    try:
        raise ValueError("boom")
    except ValueError as exc:
        soft_fail(logger, exc, "typo path", level="warn")  # not a level name

    assert len(caplog_debug.records) == 2
    assert all(r.levelno == logging.DEBUG for r in caplog_debug.records)
    assert "typo path" in caplog_debug.records[-1].getMessage()

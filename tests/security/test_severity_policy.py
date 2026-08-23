from __future__ import annotations


def test_severity_policy_block():
    from nova_ai.security.severity_policy import SeverityPolicy
    from nova_ai.security.types import ThreatLevel

    policy = SeverityPolicy()
    assert policy.action_for(ThreatLevel.CRITICAL) == "block"


def test_severity_policy_warn():
    from nova_ai.security.severity_policy import SeverityPolicy
    from nova_ai.security.types import ThreatLevel

    policy = SeverityPolicy()
    assert policy.action_for(ThreatLevel.HIGH) == "warn"


def test_severity_policy_sanitize():
    from nova_ai.security.severity_policy import SeverityPolicy
    from nova_ai.security.types import ThreatLevel

    policy = SeverityPolicy()
    assert policy.action_for(ThreatLevel.MEDIUM) == "sanitize"


def test_severity_policy_log():
    from nova_ai.security.severity_policy import SeverityPolicy
    from nova_ai.security.types import ThreatLevel

    policy = SeverityPolicy()
    assert policy.action_for(ThreatLevel.LOW) == "log"

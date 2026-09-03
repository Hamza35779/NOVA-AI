"""Fleet Oracle — anonymized hardware/performance reports, pooled via git.

``learning.fleet.report`` builds the report (fixed field list, nothing
else ever leaves the machine), ``learning.fleet.push`` syncs it to a
git-hosted dataset, and ``learning.fleet.oracle`` answers "best model
for my hardware" questions from the pooled data. Sharing is opt-in by
construction: ``learning.fleet.share_reports`` defaults to false.
"""

from nova_ai.learning.fleet.oracle import FleetAnswer, query_fleet, vram_bucket
from nova_ai.learning.fleet.push import (
    FleetPushError,
    load_reports,
    pull_reports,
    push_report,
)
from nova_ai.learning.fleet.report import SCHEMA_VERSION, build_report

__all__ = [
    "FleetAnswer",
    "FleetPushError",
    "SCHEMA_VERSION",
    "build_report",
    "load_reports",
    "pull_reports",
    "push_report",
    "query_fleet",
    "vram_bucket",
]

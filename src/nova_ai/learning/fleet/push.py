"""Fleet Oracle — git-hosted dataset sync (push / pull).

The dataset is an ordinary git repo of small JSON files::

    reports/<report_id>.json

Pushing is a plain git clone/pull/commit/push cycle (subprocess git —
the same pattern as ``skills/sources/github.py``). There is no server:
any git remote works, and reads are just a clone/pull.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class FleetPushError(RuntimeError):
    """Raised when a git operation on the dataset repo fails."""


def default_cache_dir() -> Path:
    from nova_ai.core.paths import get_config_dir

    return get_config_dir() / "fleet" / "cache"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command inside the dataset clone."""
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=check,
    )
    return result


def _sync_clone(repo_url: str, cache_dir: Path) -> Path:
    """Clone or update the dataset repo, returning the clone path."""
    if cache_dir.exists() and (cache_dir / ".git").exists():
        try:
            _git(cache_dir, "pull", "--ff-only")
        except subprocess.CalledProcessError as exc:
            # Diverged local clone (or unreachable remote) — surface as a
            # clean fleet error instead of a raw git traceback.
            raise FleetPushError(
                f"git pull failed: {(exc.stderr or '').strip()}"
            ) from exc
    else:
        cache_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(  # noqa: S603
                ["git", "clone", repo_url, str(cache_dir)],  # noqa: S607
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise FleetPushError(
                f"git clone failed: {(exc.stderr or '').strip()}"
            ) from exc
    return cache_dir


def push_report(
    report: Dict[str, Any],
    repo_url: str,
    *,
    cache_dir: Optional[Path] = None,
) -> Path:
    """Write ``reports/<report_id>.json`` into the dataset repo and push.

    The commit is authored as the generic "NOVA Fleet" identity so no
    git-config name/email leaks. Requires the repo to accept the push
    (credentials come from the user's existing git setup).
    """
    if not repo_url:
        raise ValueError("dataset_repo is not configured")
    cache = Path(cache_dir) if cache_dir else default_cache_dir()
    _sync_clone(repo_url, cache)

    reports_dir = cache / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_id = str(report.get("report_id", "")).strip()
    if not report_id:
        raise ValueError("report is missing report_id")
    out_path = reports_dir / f"{report_id}.json"
    out_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    _git(cache, "add", "reports")
    _git(
        cache,
        "-c",
        "user.name=NOVA Fleet",
        "-c",
        "user.email=nova-fleet@localhost",
        "commit",
        "-m",
        f"fleet report {report_id}",
        check=False,  # nothing to commit is fine (identical report)
    )
    try:
        _git(cache, "push", "origin", "HEAD")
    except subprocess.CalledProcessError as exc:
        raise FleetPushError(
            f"git push failed: {(exc.stderr or '').strip()}"
        ) from exc
    return out_path


def pull_reports(
    repo_url: str,
    *,
    cache_dir: Optional[Path] = None,
) -> Path:
    """Clone/update the dataset repo and return the clone path."""
    if not repo_url:
        raise ValueError("dataset_repo is not configured")
    cache = Path(cache_dir) if cache_dir else default_cache_dir()
    _sync_clone(repo_url, cache)
    return cache


def load_reports(
    repo_url: str,
    *,
    cache_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Pull the dataset and load every report JSON from it."""
    cache = pull_reports(repo_url, cache_dir=cache_dir)
    reports: List[Dict[str, Any]] = []
    reports_dir = cache / "reports"
    if not reports_dir.is_dir():
        return reports
    for path in sorted(reports_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.debug("Skipping unreadable fleet report %s: %s", path, exc)
            continue
        if isinstance(data, dict):
            reports.append(data)
    return reports


__all__ = ["FleetPushError", "load_reports", "pull_reports", "push_report"]

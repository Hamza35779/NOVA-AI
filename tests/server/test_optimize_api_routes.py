"""Tests for the /v1/optimize API routes.

Covers the A1 audit item: POST /v1/optimize/runs must create a real,
pollable optimization run (pre-registered in the store, executed in a
background thread) instead of returning a fake
``{"status": "started", "run_id": "placeholder"}``.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import nova_ai.server.api_routes as routes  # noqa: E402
from nova_ai.learning.optimize.llm_optimizer import LLMOptimizer  # noqa: E402
from nova_ai.learning.optimize.optimizer import OptimizationEngine  # noqa: E402
from nova_ai.learning.optimize.search_space import DEFAULT_SEARCH_SPACE  # noqa: E402
from nova_ai.learning.optimize.store import OptimizationStore  # noqa: E402
from nova_ai.learning.optimize.trial_runner import TrialRunner  # noqa: E402


class _InstantFailTrialRunner(TrialRunner):
    """TrialRunner whose trials fail immediately (no LLM, no benchmark)."""

    def __init__(self) -> None:
        super().__init__(
            benchmark="unit-test", max_samples=1, output_dir="results/optimize/"
        )

    def run_trial(self, config):
        raise RuntimeError("no backend in unit test")


class TestOptimizeRunEndpoint(unittest.TestCase):
    """POST /v1/optimize/runs starts a real, pollable run."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "optimize.db"

        # The handlers import DEFAULT_CONFIG_DIR inside the function bodies,
        # so patch the module-level constant: every exists() check and store
        # path then resolves into the isolated temp dir.
        import nova_ai.core.config as config_mod

        self._cfg_patcher = mock.patch.object(
            config_mod, "DEFAULT_CONFIG_DIR", Path(self._tmp.name)
        )
        self._cfg_patcher.start()

        app = FastAPI()
        app.include_router(routes.optimize_router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self._cfg_patcher.stop()
        # Background optimize threads hold sqlite handles; give them a short
        # grace period, then remove the temp dir best-effort (Windows locks
        # open files, and a leaked daemon thread must not fail the test).
        deadline = time.time() + 10
        while time.time() < deadline:
            if not any(t.name.startswith("optimize-") and t.is_alive() for t in threading.enumerate()):
                break
            time.sleep(0.2)
        for _ in range(3):
            try:
                self._tmp.cleanup()
                break
            except PermissionError:
                time.sleep(0.5)

    def test_post_returns_real_run_id_immediately_pollable(self) -> None:
        resp = self.client.post(
            "/v1/optimize/runs",
            json={
                "benchmark": "unit-test",
                "max_trials": 1,
                "optimizer_model": "test-model",
                "max_samples": 1,
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "started")
        run_id = body["run_id"]
        self.assertNotEqual(run_id, "placeholder")
        self.assertEqual(len(run_id), 16)

        # Pre-registered row must be pollable right away.
        got = self.client.get(f"/v1/optimize/runs/{run_id}")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.json()["run_id"], run_id)
        self.assertIn(got.json()["status"], {"running", "failed"})

    def test_background_failure_is_recorded_on_the_run(self) -> None:
        # The trial runner is never reached in the happy path test; here we
        # drive the failure path directly: an engine whose run_trial raises
        # must flip the pre-registered run to "failed" via the store.
        store = OptimizationStore(self.db_path)
        engine = OptimizationEngine(
            search_space=DEFAULT_SEARCH_SPACE,
            llm_optimizer=LLMOptimizer(
                search_space=DEFAULT_SEARCH_SPACE, optimizer_model="test-model"
            ),
            trial_runner=_InstantFailTrialRunner(),
            store=store,
            max_trials=1,
            run_id="preset-id",
        )
        with self.assertRaises(Exception):
            engine.run()
        run = store.get_run("preset-id")
        self.assertIsNotNone(run)
        self.assertEqual(run.status, "failed")
        store.close()

    def test_engine_generates_run_id_when_not_presets(self) -> None:
        # No optimizer backend -> run() raises, but the failure is recorded
        # on a freshly generated 16-char run id so the run never stays
        # "running" forever.
        store = OptimizationStore(self.db_path)
        engine = OptimizationEngine(
            search_space=DEFAULT_SEARCH_SPACE,
            llm_optimizer=LLMOptimizer(
                search_space=DEFAULT_SEARCH_SPACE, optimizer_model="test-model"
            ),
            trial_runner=_InstantFailTrialRunner(),
            store=store,
            max_trials=1,
        )
        with self.assertRaises(Exception):
            engine.run()
        failed_runs = [r for r in store.list_runs(limit=10)]
        self.assertTrue(failed_runs)
        recorded = failed_runs[0]
        self.assertEqual(recorded.get("status"), "failed")
        self.assertEqual(len(recorded.get("run_id", "")), 16)
        store.close()

    def test_no_placeholder_regression(self) -> None:
        import inspect

        src = inspect.getsource(routes.start_optimize_run)
        self.assertNotIn('"placeholder"', src)


if __name__ == "__main__":
    unittest.main()

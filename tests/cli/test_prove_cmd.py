"""Tests for ``nova prove`` CLI commands.

Uses the safe patcher pattern (bind patcher objects, start and stop the
SAME objects) — see the NOTE in test_train_cmd.py for the leak this avoids.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from nova_ai.cli import cli
from nova_ai.core.config import LearningConfig, ProvingConfig
from nova_ai.learning.proving.store import ProvingRunStore


def _proving_cfg(enabled: bool = True) -> LearningConfig:
    return LearningConfig(proving=ProvingConfig(enabled=enabled, min_samples=10))


def _patch_proving(tmp_path: Path, *, enabled: bool = True):
    """Patch home-dir resolution and config for isolated CLI tests."""
    config = mock.MagicMock()
    config.learning = _proving_cfg(enabled=enabled)
    return [
        mock.patch("nova_ai.cli.prove_cmd.load_config", return_value=config),
        mock.patch(
            "nova_ai.cli.prove_cmd._proving_root",
            return_value=tmp_path / "learning" / "proving",
        ),
        mock.patch("nova_ai.core.paths.get_config_dir", return_value=tmp_path),
    ]


class _Invoke:
    """Start patches, invoke, stop the SAME patchers."""

    def __init__(self, tmp_path: Path, *, enabled: bool = True) -> None:
        self._patches = _patch_proving(tmp_path, enabled=enabled)

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()
        return False


def _seed_run(tmp_path: Path, run_id: str = "prove_r1", **overrides) -> dict:
    root = tmp_path / "learning" / "proving"
    store = ProvingRunStore(root / "runs.db")
    store.start_run(run_id, trigger="manual", candidate="cand-model",
                    incumbent="inc-model")
    per_class = {
        "code": {"candidate_acc": 0.9, "incumbent_acc": 0.6, "delta": 0.3,
                 "winner": "cand-model", "total": 6},
        "math": {"candidate_acc": 0.5, "incumbent_acc": 0.9, "delta": -0.4,
                 "winner": "inc-model", "total": 6},
    }
    store.finish_run(
        run_id, status=overrides.get("status", "completed"), samples=12,
        per_class=per_class,
    )
    store.close()
    return per_class


class TestProveGroup:
    def test_subcommands_exist_in_help(self) -> None:
        result = CliRunner().invoke(cli, ["prove", "--help"])
        assert result.exit_code == 0
        for sub in ("run", "status", "list", "roster", "adopt", "revert", "watch"):
            assert sub in result.output

    def test_registered_in_top_level_cli(self) -> None:
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "prove" in result.output


class TestStatus:
    def test_no_runs_message(self, tmp_path: Path) -> None:
        with _Invoke(tmp_path):
            result = CliRunner().invoke(cli, ["prove", "status"])
        assert result.exit_code == 0
        assert "No proving runs yet" in result.output

    def test_shows_latest_run_with_scorecard(self, tmp_path: Path) -> None:
        _seed_run(tmp_path)
        with _Invoke(tmp_path):
            result = CliRunner().invoke(cli, ["prove", "status"])
        assert result.exit_code == 0
        assert "prove_r1" in result.output
        assert "cand-model" in result.output
        assert "Scorecard" in result.output
        assert "code" in result.output

    def test_shows_error_for_failed_run(self, tmp_path: Path) -> None:
        _seed_run(tmp_path, status="failed")
        root = tmp_path / "learning" / "proving"
        store = ProvingRunStore(root / "runs.db")
        store.finish_run("prove_r1", status="failed", error="boom")
        store.close()
        with _Invoke(tmp_path):
            result = CliRunner().invoke(cli, ["prove", "status"])
        assert result.exit_code == 0
        assert "boom" in result.output


class TestList:
    def test_lists_runs(self, tmp_path: Path) -> None:
        _seed_run(tmp_path, "prove_a")
        _seed_run(tmp_path, "prove_b")
        with _Invoke(tmp_path):
            result = CliRunner().invoke(cli, ["prove", "list"])
        assert result.exit_code == 0
        assert "prove_a" in result.output
        assert "prove_b" in result.output

    def test_empty(self, tmp_path: Path) -> None:
        with _Invoke(tmp_path):
            result = CliRunner().invoke(cli, ["prove", "list"])
        assert result.exit_code == 0
        assert "No proving runs yet" in result.output


class TestRoster:
    def test_empty(self, tmp_path: Path) -> None:
        with _Invoke(tmp_path):
            result = CliRunner().invoke(cli, ["prove", "roster"])
        assert result.exit_code == 0
        assert "No proven adoptions yet" in result.output

    def test_shows_policy_map(self, tmp_path: Path) -> None:
        root = tmp_path / "learning" / "proving"
        root.mkdir(parents=True)
        (root / "policy_map.json").write_text(json.dumps({
            "code": {"model": "cand-model", "run_id": "prove_r1",
                     "margin": 0.3, "adopted_at": "2026-01-01T00:00:00"},
        }))
        with _Invoke(tmp_path):
            result = CliRunner().invoke(cli, ["prove", "roster"])
        assert result.exit_code == 0
        assert "code" in result.output
        assert "cand-model" in result.output
        assert "prove_r1" in result.output


class TestAdopt:
    def test_unknown_run_errors(self, tmp_path: Path) -> None:
        with _Invoke(tmp_path):
            result = CliRunner().invoke(cli, ["prove", "adopt", "nope"])
        assert result.exit_code == 1
        assert "Unknown run" in result.output

    def test_non_completed_run_rejected(self, tmp_path: Path) -> None:
        _seed_run(tmp_path, status="failed")
        with _Invoke(tmp_path):
            result = CliRunner().invoke(cli, ["prove", "adopt", "prove_r1"])
        assert result.exit_code == 1
        assert "failed" in result.output

    def test_adopt_writes_policy_map(self, tmp_path: Path) -> None:
        _seed_run(tmp_path)
        with _Invoke(tmp_path):
            result = CliRunner().invoke(cli, ["prove", "adopt", "prove_r1"])
        assert result.exit_code == 0
        assert "code" in result.output
        root = tmp_path / "learning" / "proving"
        pm = json.loads((root / "policy_map.json").read_text())
        assert pm["code"]["model"] == "cand-model"
        # incumbent winner must NOT be adopted
        assert "math" not in pm
        # recorded in the run record
        store = ProvingRunStore(root / "runs.db")
        try:
            assert store.get_run("prove_r1")["adopted"] == {"code": "cand-model"}
        finally:
            store.close()

    def test_adopt_class_filter(self, tmp_path: Path) -> None:
        _seed_run(tmp_path)
        with _Invoke(tmp_path):
            result = CliRunner().invoke(
                cli, ["prove", "adopt", "prove_r1", "--class", "code"]
            )
        assert result.exit_code == 0
        root = tmp_path / "learning" / "proving"
        pm = json.loads((root / "policy_map.json").read_text())
        assert set(pm) == {"code"}

    def test_adopt_unknown_class_warns(self, tmp_path: Path) -> None:
        _seed_run(tmp_path)
        with _Invoke(tmp_path):
            result = CliRunner().invoke(
                cli, ["prove", "adopt", "prove_r1", "--class", "nope"]
            )
        assert result.exit_code == 0
        assert "nope" in result.output  # "Not in run" warning

    def test_adopt_margin_gate_blocks(self, tmp_path: Path) -> None:
        # candidate won by 0.02 < min_margin=0.05 → nothing to adopt
        _seed_run(tmp_path)
        root = tmp_path / "learning" / "proving"
        store = ProvingRunStore(root / "runs.db")
        store.finish_run(
            "prove_r1", status="completed", samples=12,
            per_class={"code": {"candidate_acc": 0.62, "incumbent_acc": 0.60,
                                 "delta": 0.02, "winner": "cand-model", "total": 6}},
        )
        store.close()
        with _Invoke(tmp_path):
            result = CliRunner().invoke(cli, ["prove", "adopt", "prove_r1"])
        assert result.exit_code == 0
        assert "Nothing to adopt" in result.output
        assert not (root / "policy_map.json").exists()


class TestRevert:
    def test_revert_existing(self, tmp_path: Path) -> None:
        root = tmp_path / "learning" / "proving"
        root.mkdir(parents=True)
        (root / "policy_map.json").write_text(
            json.dumps({"code": {"model": "cand-model", "run_id": "r",
                                  "margin": 0.1, "adopted_at": "t"}})
        )
        with _Invoke(tmp_path):
            result = CliRunner().invoke(cli, ["prove", "revert", "code"])
        assert result.exit_code == 0
        assert json.loads((root / "policy_map.json").read_text()) == {}

    def test_revert_missing_errors(self, tmp_path: Path) -> None:
        with _Invoke(tmp_path):
            result = CliRunner().invoke(cli, ["prove", "revert", "code"])
        assert result.exit_code == 1
        assert "No adoption found" in result.output


class TestRunCommand:
    def test_disabled_guard(self, tmp_path: Path) -> None:
        with _Invoke(tmp_path, enabled=False):
            result = CliRunner().invoke(cli, ["prove", "run", "some-model"])
        assert result.exit_code == 1
        assert "disabled" in result.output

    def test_in_flight_guard(self, tmp_path: Path) -> None:
        root = tmp_path / "learning" / "proving"
        store = ProvingRunStore(root / "runs.db")
        store.start_run("prove_running", trigger="manual", candidate="a",
                        incumbent="b")
        store.close()
        with _Invoke(tmp_path):
            result = CliRunner().invoke(cli, ["prove", "run", "some-model"])
        assert result.exit_code == 1
        assert "already in flight" in result.output


class TestWatch:
    def test_no_new_models(self, tmp_path: Path, monkeypatch) -> None:
        with _Invoke(tmp_path):
            # watch() imports inside the function body from the watcher
            # module, so patch the source names there.
            monkeypatch.setattr(
                "nova_ai.learning.proving.watcher.list_local_models",
                lambda cfg: ["m1"],
            )
            monkeypatch.setattr(
                "nova_ai.learning.proving.watcher.detect_new_models",
                lambda *, state_path, models: [],
            )
            result = CliRunner().invoke(cli, ["prove", "watch"])
        assert result.exit_code == 0
        assert "No new models" in result.output

    def test_detects_and_reports_new(self, tmp_path: Path, monkeypatch) -> None:
        with _Invoke(tmp_path):
            monkeypatch.setattr(
                "nova_ai.learning.proving.watcher.list_local_models",
                lambda cfg: ["m1"],
            )
            monkeypatch.setattr(
                "nova_ai.learning.proving.watcher.detect_new_models",
                lambda *, state_path, models: ["brand-new"],
            )
            result = CliRunner().invoke(cli, ["prove", "watch"])
        assert result.exit_code == 0
        assert "brand-new" in result.output

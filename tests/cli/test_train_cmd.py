"""Tests for the ``nova train`` CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from nova_ai.cli import cli
from nova_ai.learning.training.store import TrainingRunStore


def _training_cfg(enabled: bool = True):
    from nova_ai.core.config import LearningConfig, TrainingConfig

    # Real config objects (not MagicMock attrs) so boolean checks like
    # `if not cfg.enabled` behave truthiness-correctly through the whole
    # load_config().learning.training_effective chain.
    learning_cfg = LearningConfig(
        training=TrainingConfig(
            enabled=enabled,
            min_pairs=10,
            deploy_targets=["adapter"],
        ),
    )
    return learning_cfg


def _patch_training(tmp_path: Path, *, enabled: bool = True):
    """Patch home-dir resolution and config for isolated CLI tests."""
    learning_cfg = _training_cfg(enabled=enabled)
    config = mock.MagicMock()
    config.learning = learning_cfg

    patches = [
        mock.patch("nova_ai.cli.train_cmd.load_config", return_value=config),
        mock.patch(
            "nova_ai.cli.train_cmd._training_root",
            return_value=tmp_path / "learning" / "training",
        ),
        mock.patch("nova_ai.core.paths.get_config_dir", return_value=tmp_path),
    ]
    return patches


class TestTrainGroup:
    def test_subcommands_exist_in_help(self) -> None:
        result = CliRunner().invoke(cli, ["train", "--help"])
        assert result.exit_code == 0
        for sub in ("run", "status", "list", "deploy", "export-traces"):
            assert sub in result.output

    def test_registered_in_top_level_cli(self) -> None:
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "train" in result.output


class TestTrainStatus:
    def test_no_runs_message(self, tmp_path: Path) -> None:
        # NOTE: start and stop must use the SAME patcher objects — stopping
        # fresh patchers silently leaves the started ones active, leaking a
        # global get_config_dir() patch into every later test.
        patches = _patch_training(tmp_path)
        for p in patches:
            p.start()
        try:
            result = CliRunner().invoke(cli, ["train", "status"])
            assert result.exit_code == 0
            assert "No training runs yet" in result.output
        finally:
            for p in patches:
                p.stop()

    def test_shows_latest_run(self, tmp_path: Path) -> None:
        root = tmp_path / "learning" / "training"
        store = TrainingRunStore(root / "runs.db")
        store.start_run("train_r1", trigger="manual", base_model="qwen3:8b")
        store.finish_run(
            "train_r1", status="pending_review", pairs=80, avg_loss=0.4
        )
        store.close()

        patches = _patch_training(tmp_path)
        for p in patches:
            p.start()
        try:
            result = CliRunner().invoke(cli, ["train", "status"])
            assert result.exit_code == 0
            assert "train_r1" in result.output
            assert "pending_review" in result.output
        finally:
            for p in patches:
                p.stop()


class TestTrainList:
    def test_lists_runs(self, tmp_path: Path) -> None:
        root = tmp_path / "learning" / "training"
        store = TrainingRunStore(root / "runs.db")
        store.start_run("train_a", trigger="scheduled")
        store.start_run("train_b", trigger="manual")
        store.close()

        patches = _patch_training(tmp_path)
        for p in patches:
            p.start()
        try:
            result = CliRunner().invoke(cli, ["train", "list"])
            assert result.exit_code == 0
            assert "train_a" in result.output
            assert "train_b" in result.output
            assert "scheduled" in result.output
        finally:
            for p in patches:
                p.stop()


class TestTrainRun:
    def test_disabled_exits_nonzero(self, tmp_path: Path) -> None:
        patches = _patch_training(tmp_path, enabled=False)
        for p in patches:
            p.start()
        try:
            result = CliRunner().invoke(cli, ["train", "run"])
            assert result.exit_code == 1
            assert "disabled" in result.output
        finally:
            for p in patches:
                p.stop()

    def test_background_spawns_process(self, tmp_path: Path) -> None:
        patches = _patch_training(tmp_path)
        spawn = mock.patch(
            "nova_ai.cli.train_cmd._spawn_background", return_value=None
        )
        for p in patches:
            p.start()
        try:
            with spawn:
                result = CliRunner().invoke(cli, ["train", "run"])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0
        assert "background" in result.output.lower()


class TestTrainExportTraces:
    def test_export_writes_jsonl(self, tmp_path: Path) -> None:
        out = tmp_path / "pairs.jsonl"
        pairs = [
            {"input": "q1", "output": "a1", "query_class": "math",
             "model": "qwen3:8b", "feedback": 0.9},
            {"input": "q2", "output": "a2", "query_class": "code",
             "model": "qwen3:8b", "feedback": 0.8},
        ]

        patches = [
            mock.patch(
                "nova_ai.core.paths.get_config_dir", return_value=tmp_path
            ),
            mock.patch(
                "nova_ai.learning.training.data.TrainingDataMiner.extract_sft_pairs",
                return_value=pairs,
            ),
        ]
        for p in patches:
            p.start()
        try:
            result = CliRunner().invoke(
                cli, ["train", "export-traces", "--out", str(out)]
            )
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        assert "Exported 2" in result.output
        lines = out.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["input"] == "q1"

    def test_export_empty(self, tmp_path: Path) -> None:
        out = tmp_path / "pairs.jsonl"
        patches = [
            mock.patch(
                "nova_ai.core.paths.get_config_dir", return_value=tmp_path
            ),
            mock.patch(
                "nova_ai.learning.training.data.TrainingDataMiner.extract_sft_pairs",
                return_value=[],
            ),
        ]
        for p in patches:
            p.start()
        try:
            result = CliRunner().invoke(
                cli, ["train", "export-traces", "--out", str(out)]
            )
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0
        assert "Exported 0" in result.output
        assert "No qualifying traces" in result.output


class TestTrainDeploy:
    def test_unknown_run_errors(self, tmp_path: Path) -> None:
        patches = _patch_training(tmp_path)
        for p in patches:
            p.start()
        try:
            result = CliRunner().invoke(
                cli, ["train", "deploy", "ghost-run"]
            )
            assert result.exit_code == 1
            assert "Unknown run" in result.output
        finally:
            for p in patches:
                p.stop()

    def test_deploy_promotes_pending_run(self, tmp_path: Path) -> None:
        root = tmp_path / "learning" / "training"
        adapter_dir = tmp_path / "adapters" / "train_r1"
        adapter_dir.mkdir(parents=True)

        store = TrainingRunStore(root / "runs.db")
        store.start_run("train_r1", trigger="manual", base_model="qwen3:8b")
        store.finish_run(
            "train_r1",
            status="pending_review",
            pairs=50,
            adapter_path=str(adapter_dir),
        )
        store.close()

        deploy_report = mock.MagicMock()
        deploy_report.results = [
            mock.MagicMock(ok=True, target="adapter", detail=str(adapter_dir))
        ]
        deploy_report.to_list.return_value = [
            {"target": "adapter", "ok": True, "detail": str(adapter_dir)}
        ]

        patches = _patch_training(tmp_path)
        patches.append(
            mock.patch(
                "nova_ai.learning.training.pipeline.deploy",
                return_value=deploy_report,
            )
        )
        patches.append(
            mock.patch(
                "nova_ai.learning.training.deploy.deploy",
                return_value=deploy_report,
            )
        )
        for p in patches:
            p.start()
        try:
            result = CliRunner().invoke(
                cli,
                ["train", "deploy", "train_r1", "--target", "adapter"],
            )
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        # Run promoted to completed
        store = TrainingRunStore(root / "runs.db")
        record = store.get_run("train_r1")
        assert record["status"] == "completed"
        # active.json points at the adapter
        pointer = root / "active.json"
        assert pointer.exists()
        data = json.loads(pointer.read_text(encoding="utf-8"))
        assert data["run_id"] == "train_r1"

"""Tests for the cloud J/token energy estimate (audit item A3).

Covers the ``_cloud_energy`` module (factors, env controls, row/summary
estimation) and the ``_write_summary`` wiring that reports the estimate
separately from the NVML-measured ``energy_j_total``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nova_ai.agents.hybrid import _cloud_energy
from nova_ai.agents.hybrid.runner import _write_summary


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Keep estimate controls deterministic per test."""
    monkeypatch.delenv("NOVA_AI_CLOUD_ENERGY", raising=False)
    monkeypatch.delenv("NOVA_AI_CLOUD_ENERGY_J_PER_TOKEN", raising=False)


class TestFactors:
    def test_default_factor_for_known_providers(self):
        for provider in ("anthropic", "openai", "google"):
            assert _cloud_energy.j_per_token(provider) == 2.0e-3

    def test_unknown_provider_falls_back_to_default(self):
        assert (
            _cloud_energy.j_per_token("vendor-x") == _cloud_energy.DEFAULT_J_PER_TOKEN
        )

    def test_case_insensitive_provider(self):
        assert _cloud_energy.j_per_token("Anthropic") == 2.0e-3

    def test_env_override_applies_to_all_providers(self, monkeypatch):
        monkeypatch.setenv("NOVA_AI_CLOUD_ENERGY_J_PER_TOKEN", "1.5e-2")
        assert _cloud_energy.j_per_token("anthropic") == 1.5e-2
        assert _cloud_energy.j_per_token("") == 1.5e-2

    def test_malformed_override_disables_estimate(self, monkeypatch, capsys):
        monkeypatch.setenv("NOVA_AI_CLOUD_ENERGY_J_PER_TOKEN", "not-a-float")
        assert _cloud_energy.j_per_token("openai") == 0.0
        assert "Invalid" in capsys.readouterr().out

    def test_enabled_switch(self, monkeypatch):
        assert _cloud_energy.enabled() is True
        monkeypatch.setenv("NOVA_AI_CLOUD_ENERGY", "0")
        assert _cloud_energy.enabled() is False


class TestEstimation:
    def test_row_estimate(self):
        row = {"tokens_cloud": 1000, "cloud_provider": "anthropic"}
        assert _cloud_energy.estimate_row_energy_j(row) == pytest.approx(2.0)

    def test_row_without_cloud_tokens_is_zero(self):
        assert _cloud_energy.estimate_row_energy_j({"tokens_cloud": 0}) == 0.0
        assert _cloud_energy.estimate_row_energy_j({}) == 0.0

    def test_row_provider_read_from_traces(self):
        row = {"tokens_cloud": 1000, "traces": {"cloud_provider": "openai"}}
        assert _cloud_energy.estimate_row_energy_j(row) == pytest.approx(2.0)

    def test_disabled_env_zeroes_estimate(self, monkeypatch):
        monkeypatch.setenv("NOVA_AI_CLOUD_ENERGY", "0")
        row = {"tokens_cloud": 1000}
        assert _cloud_energy.estimate_row_energy_j(row) == 0.0
        assert _cloud_energy.estimate_summary_energy_j([row, row]) == 0.0

    def test_summary_sums_rows(self):
        rows = [
            {"tokens_cloud": 1000},
            {"tokens_cloud": 500, "cloud_provider": "google"},
            {"tokens_local": 999},  # local-only row contributes nothing
        ]
        expected = 1000 * 2e-3 + 500 * 2e-3
        assert _cloud_energy.estimate_summary_energy_j(rows) == pytest.approx(expected)

    def test_summary_note_mentions_estimate(self):
        assert "estimate" in _cloud_energy.summary_note().lower()


class TestSummaryWiring:
    @staticmethod
    def _write(tmp_path: Path, rows) -> dict:
        out_dir = tmp_path / "cell"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "results.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
        )
        cell = {"method": "hybrid", "bench": "unit", "n": len(rows)}
        tasks = [{"task_id": f"t{i}"} for i in range(len(rows))]
        _write_summary(out_dir, "unit-cell", cell, tasks, t_start=0.0)
        return json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))

    def test_estimate_reported_separately(self, tmp_path):
        rows = [
            {
                "task_id": "t0",
                "score": {"success": True},
                "tokens_local": 10,
                "tokens_cloud": 1000,
                "cost_usd": 0.01,
            },
            {
                "task_id": "t1",
                "score": {"success": False},
                "tokens_local": 0,
                "tokens_cloud": 500,
                "cost_usd": 0.0,
            },
        ]
        summary = self._write(tmp_path, rows)
        expected = (1000 + 500) * 2e-3
        assert summary["energy_j_cloud_estimated"] == pytest.approx(expected)
        # Measured GPU energy untouched by the estimate (0 without NVML).
        assert summary["energy_j_total"] == 0.0
        assert summary["energy_j_total_with_cloud_estimate"] == pytest.approx(expected)
        assert "estimate" in summary["cloud_energy_note"].lower()

    def test_disabled_env_zeroes_summary_fields(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOVA_AI_CLOUD_ENERGY", "0")
        rows = [{"task_id": "t0", "tokens_cloud": 1000, "score": {"success": True}}]
        summary = self._write(tmp_path, rows)
        assert summary["energy_j_cloud_estimated"] == 0.0
        assert summary["energy_j_total_with_cloud_estimate"] == 0.0
        assert "disabled" in summary["cloud_energy_note"].lower()

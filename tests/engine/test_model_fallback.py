"""Tests for the shared model-reachability fallback helpers (audit FP-A)."""

from __future__ import annotations

from nova_ai.engine._model_fallback import (
    missing_model_hint,
    model_reachable,
    model_reachable_in_list,
    pick_fallback_from_engine_models,
    pick_reachable_fallback,
    unreachable_model_notice,
)


class TestModelReachableInList:
    def test_empty_list_assumes_reachable(self) -> None:
        """Empty/unknown lists must never turn into a hard gate."""
        assert model_reachable_in_list([], "anything") is True
        assert model_reachable_in_list(None, "anything") is True

    def test_membership(self) -> None:
        assert model_reachable_in_list(["a", "b"], "a") is True
        assert model_reachable_in_list(["a", "b"], "c") is False


class TestModelReachable:
    def test_unknown_engine_assumes_reachable(self) -> None:
        assert model_reachable({}, "ollama", "x") is True

    def test_snapshot_membership(self) -> None:
        assert model_reachable({"ollama": ["a"]}, "ollama", "a") is True
        assert model_reachable({"ollama": ["a"]}, "ollama", "b") is False


class TestPickFallbackFromEngineModels:
    def test_reachable_model_returns_none(self) -> None:
        assert pick_fallback_from_engine_models(["a", "b"], "a") is None

    def test_prefers_configured_fallback_model(self) -> None:
        result = pick_fallback_from_engine_models(
            ["a", "b"], "ghost", fallback_model="b"
        )
        assert result == "b"

    def test_falls_back_to_first_installed_model(self) -> None:
        assert pick_fallback_from_engine_models(["a", "b"], "ghost") == "a"

    def test_no_alternative_returns_none(self) -> None:
        """Configured model is the only one installed -> keep it."""
        assert pick_fallback_from_engine_models(["ghost"], "ghost") is None

    def test_empty_list_returns_none(self) -> None:
        """Discovery useless -> keep the configured model, never gate."""
        assert pick_fallback_from_engine_models([], "ghost") is None
        assert pick_fallback_from_engine_models(None, "ghost") is None


class TestPickReachableFallback:
    def test_discovery_snapshot_delegates(self) -> None:
        assert pick_reachable_fallback({"ollama": ["a"]}, "ollama", "b") == "a"
        assert pick_reachable_fallback({"ollama": ["a"]}, "ollama", "a") is None

    def test_empty_snapshot_returns_none(self) -> None:
        assert pick_reachable_fallback({}, "ollama", "ghost") is None


class TestUnreachableModelNotice:
    def test_notice_names_both_models_and_the_fix(self) -> None:
        notice = unreachable_model_notice("qwen3.5:4b", "qwen2.5:0.5b")
        assert "qwen3.5:4b" in notice
        assert "qwen2.5:0.5b" in notice
        assert "nova model pull qwen3.5:4b" in notice


class TestMissingModelHint:
    """Post-recovery hint for the fresh-install zero-models 404 case."""

    def test_missing_model_error_returns_pull_hint(self) -> None:
        hint = missing_model_hint(
            RuntimeError("Ollama returned 404: model 'qwen3.5:4b' not found"),
            "ollama",
            "qwen3.5:4b",
        )
        assert hint is not None
        assert "nova model pull qwen3.5:4b" in hint
        assert "ollama" in hint

    def test_unrelated_error_returns_none(self) -> None:
        assert (
            missing_model_hint(RuntimeError("connection reset"), "ollama", "x")
            is None
        )

    def test_cloud_engine_gets_no_pull_advice(self) -> None:
        hint = missing_model_hint(
            RuntimeError("404: model not found"),
            "cloud",
            "gpt-4o",
            is_cloud=True,
        )
        assert hint is not None
        assert "pull" not in hint
        assert "nova model list" in hint

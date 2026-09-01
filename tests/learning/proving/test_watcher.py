"""Tests for new-model detection and auto-prove gating."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nova_ai.core.config import ProvingConfig
from nova_ai.learning.proving import watcher as watcher_mod
from nova_ai.learning.proving.store import ProvingRunStore
from nova_ai.learning.proving.watcher import (
    KNOWN_MODELS_FILENAME,
    detect_new_models,
    list_local_models,
    maybe_auto_prove,
)


class TestDetectNewModels:
    def test_all_new_on_first_run(self, tmp_path: Path) -> None:
        state = tmp_path / KNOWN_MODELS_FILENAME
        new = detect_new_models(state_path=state, models=["a", "b"])
        assert sorted(new) == ["a", "b"]

    def test_no_new_on_unchanged(self, tmp_path: Path) -> None:
        state = tmp_path / KNOWN_MODELS_FILENAME
        detect_new_models(state_path=state, models=["a", "b"])
        assert detect_new_models(state_path=state, models=["a", "b"]) == []

    def test_detects_added_model(self, tmp_path: Path) -> None:
        state = tmp_path / KNOWN_MODELS_FILENAME
        detect_new_models(state_path=state, models=["a"])
        assert detect_new_models(state_path=state, models=["a", "b"]) == ["b"]

    def test_removed_then_repulled_counts_as_new(self, tmp_path: Path) -> None:
        state = tmp_path / KNOWN_MODELS_FILENAME
        detect_new_models(state_path=state, models=["a", "b"])
        detect_new_models(state_path=state, models=["a"])  # b removed
        assert detect_new_models(state_path=state, models=["a", "b"]) == ["b"]

    def test_state_file_round_trip(self, tmp_path: Path) -> None:
        state = tmp_path / KNOWN_MODELS_FILENAME
        detect_new_models(state_path=state, models=["a", "b"])
        data = json.loads(state.read_text())
        assert set(data["models"]) == {"a", "b"}
        assert "first_seen" in data["models"]["a"]

    def test_corrupt_state_treated_as_empty(self, tmp_path: Path) -> None:
        state = tmp_path / KNOWN_MODELS_FILENAME
        state.write_text("{not json")
        new = detect_new_models(state_path=state, models=["a"])
        assert new == ["a"]


class TestListLocalModels:
    def test_union_sorted(self, monkeypatch) -> None:
        import nova_ai.engine._discovery as discovery

        monkeypatch.setattr(
            discovery, "discover_engines", lambda config: [("a", object()), ("b", object())]
        )
        monkeypatch.setattr(
            discovery,
            "discover_models",
            lambda engines: {"a": ["m2", "m1"], "b": ["m1", "m3"]},
        )
        assert list_local_models(object()) == ["m1", "m2", "m3"]

    def test_discovery_failure_returns_empty(self, monkeypatch) -> None:
        import nova_ai.engine._discovery as discovery

        def boom(config):
            raise RuntimeError("down")

        monkeypatch.setattr(discovery, "discover_engines", boom)
        assert list_local_models(object()) == []


@pytest.fixture()
def run_store(tmp_path: Path) -> ProvingRunStore:
    s = ProvingRunStore(tmp_path / "runs.db")
    yield s
    s.close()


class TestMaybeAutoProve:
    def test_disabled_skips(self, tmp_path: Path, run_store: ProvingRunStore) -> None:
        result = maybe_auto_prove(
            trace_store=object(),
            config=ProvingConfig(enabled=False, auto_trigger=True),
            run_store=run_store,
            proving_root=tmp_path,
        )
        assert result == [{"status": "skipped", "reason": "proving disabled"}]

    def test_auto_trigger_off_skips(
        self, tmp_path: Path, run_store: ProvingRunStore
    ) -> None:
        result = maybe_auto_prove(
            trace_store=object(),
            config=ProvingConfig(enabled=True, auto_trigger=False),
            run_store=run_store,
            proving_root=tmp_path,
        )
        assert result == [{"status": "skipped", "reason": "auto_trigger disabled"}]

    def test_run_in_flight_skips(
        self, tmp_path: Path, run_store: ProvingRunStore
    ) -> None:
        run_store.start_run("prove_block", trigger="manual", candidate="a",
                            incumbent="b")
        result = maybe_auto_prove(
            trace_store=object(),
            config=ProvingConfig(enabled=True, auto_trigger=True),
            run_store=run_store,
            proving_root=tmp_path,
        )
        assert result[0]["status"] == "skipped"
        assert "in flight" in result[0]["reason"]

    def test_no_new_models_skips(
        self, tmp_path: Path, run_store: ProvingRunStore, monkeypatch
    ) -> None:
        monkeypatch.setattr(watcher_mod, "list_local_models", lambda cfg: ["a"])
        state = tmp_path / KNOWN_MODELS_FILENAME
        detect_new_models(state_path=state, models=["a"])  # pre-seed snapshot
        result = maybe_auto_prove(
            trace_store=object(),
            config=ProvingConfig(enabled=True, auto_trigger=True),
            run_store=run_store,
            proving_root=tmp_path,
        )
        assert result == [{"status": "skipped", "reason": "no new models"}]

    def test_new_model_triggers_run_proving(
        self, tmp_path: Path, run_store: ProvingRunStore, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            watcher_mod, "list_local_models", lambda cfg: ["new-model"]
        )
        calls: dict[str, object] = {}

        def fake_run_proving(**kwargs):
            calls.update(kwargs)
            return {"id": "prove_x", "status": "completed", "adopted": {}}

        monkeypatch.setattr(
            "nova_ai.learning.proving.pipeline.run_proving", fake_run_proving
        )
        result = maybe_auto_prove(
            trace_store=object(),
            config=ProvingConfig(enabled=True, auto_trigger=True),
            run_store=run_store,
            proving_root=tmp_path,
        )
        assert result == [
            {"candidate": "new-model", "status": "completed",
             "run_id": "prove_x", "adopted": {}}
        ]
        assert calls["candidate"] == "new-model"
        assert calls["trigger"] == "auto"

    def test_run_proving_exception_isolated(
        self, tmp_path: Path, run_store: ProvingRunStore, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            watcher_mod, "list_local_models", lambda cfg: ["bad-model"]
        )

        def boom(**kwargs):
            raise RuntimeError("gpu on fire")

        monkeypatch.setattr(
            "nova_ai.learning.proving.pipeline.run_proving", boom
        )
        result = maybe_auto_prove(
            trace_store=object(),
            config=ProvingConfig(enabled=True, auto_trigger=True),
            run_store=run_store,
            proving_root=tmp_path,
        )
        assert result == [
            {"candidate": "bad-model", "status": "failed", "error": "gpu on fire"}
        ]

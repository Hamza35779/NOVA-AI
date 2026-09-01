"""Tests for the proving pipeline — verdicts, guards, adoption seam.

All tests inject fake generation/judge backends; no Ollama or network is
needed. The fakes implement the two backend surfaces EvalRunner touches:
``generate_full`` (candidate generation) and ``generate`` (the judge).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nova_ai.core.config import ProvingConfig
from nova_ai.core.types import Trace
from nova_ai.learning.proving import watcher as watcher_mod
from nova_ai.learning.proving.pipeline import MIN_SCORED_PER_CLASS, run_proving
from nova_ai.learning.proving.store import ProvingRunStore
from nova_ai.learning.routing._utils import classify_query
from nova_ai.traces.store import TraceStore

CAND = "cand-model"
INC = "inc-model"


# ---------------------------------------------------------------------------
# Fixtures and fakes
# ---------------------------------------------------------------------------


@pytest.fixture()
def seeded_store(tmp_path: Path) -> TraceStore:
    """TraceStore with 3 distinct high-feedback traces per query class.

    Queries differ within their first 50 chars because the synthesizer
    dedups on (agent, first-50-chars).
    """
    store = TraceStore(tmp_path / "traces.db")
    queries = [
        "please fix the bug in `def f(): pass` snippet one",
        "please fix the bug in `def g(): pass` snippet two",
        "please fix the bug in `def h(): pass` snippet three",
        "solve the integral of x^2 dx problem one",
        "solve the integral of x^3 dx problem two",
        "solve the integral of x^4 dx problem three",
        "architecture deep dive number one: " + "alpha " * 100,
        "architecture deep dive number two: " + "alpha " * 100,
        "architecture deep dive number three: " + "alpha " * 100,
        "tell me about dogs and their long history in europe with breeding",
        "tell me about cats and their long history in asia with domesticati",
        "tell me about birds and their long migration across africa yearly",
    ]
    classes = {classify_query(q) for q in queries}
    assert classes == {"code", "math", "long", "general"}, classes
    for i, q in enumerate(queries):
        store.save(Trace(trace_id=f"t{i}", query=q, agent="coder",
                         result=f"answer {i}", feedback=1.0))
    return store


class _Backend:
    """Shared backend body: answers GOOD/BAD depending on the model."""

    good_model: str = CAND

    def generate_full(self, prompt, *, model, system=None, temperature=0.0,
                      max_tokens=1024):
        good = model == self.good_model
        return {"content": "GOOD" if good else "BAD", "usage": {},
                "latency_seconds": 0.1}

    def generate(self, prompt, *, model, system=None, temperature=0.0,
                 max_tokens=1024):
        # The judge scores answer content: GOOD matches the reference.
        good = "Candidate answer:\nGOOD" in prompt
        return "YES\nmatches" if good else "NO\nworse"


class CandidateWinsBackend(_Backend):
    good_model = CAND


class IncumbentWinsBackend(_Backend):
    good_model = INC


@pytest.fixture()
def run_store(tmp_path: Path) -> ProvingRunStore:
    s = ProvingRunStore(tmp_path / "runs.db")
    yield s
    s.close()


@pytest.fixture()
def patched_discovery(monkeypatch):
    """Discovery claims both models exist (no Ollama in tests)."""
    monkeypatch.setattr(
        watcher_mod, "list_local_models", lambda cfg: [CAND, INC]
    )


@pytest.fixture()
def proving_root(tmp_path: Path) -> Path:
    return tmp_path / "proving"


def _run(seeded_store, run_store, proving_root, backend_cls=CandidateWinsBackend,
         config=None, **kwargs):
    cfg = config or ProvingConfig(enabled=True, min_samples=10, max_samples=60)
    return run_proving(
        candidate=kwargs.pop("candidate", CAND),
        trace_store=seeded_store,
        config=cfg,
        run_store=run_store,
        incumbent=kwargs.pop("incumbent", INC),
        proving_root=proving_root,
        backend_factory=backend_cls,
        judge_backend=backend_cls(),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("patched_discovery")
class TestHappyPath:
    def test_completed_with_per_class_winners(
        self, seeded_store, run_store, proving_root
    ) -> None:
        record = _run(seeded_store, run_store, proving_root)
        assert record["status"] == "completed", record
        assert record["samples"] == 12
        assert set(record["per_class"]) == {"code", "math", "long", "general"}
        for v in record["per_class"].values():
            assert v["candidate_acc"] == 1.0
            assert v["incumbent_acc"] == 0.0
            assert v["delta"] == pytest.approx(1.0)
            assert v["winner"] == CAND

    def test_no_adoption_by_default(
        self, seeded_store, run_store, proving_root
    ) -> None:
        record = _run(seeded_store, run_store, proving_root)
        assert record["adopted"] == {}
        assert not (proving_root / "policy_map.json").exists()

    def test_incumbent_wins_when_better(
        self, seeded_store, run_store, proving_root
    ) -> None:
        record = _run(
            seeded_store, run_store, proving_root, backend_cls=IncumbentWinsBackend
        )
        assert record["status"] == "completed"
        winners = {v["winner"] for v in record["per_class"].values()}
        assert winners == {INC}

    def test_run_record_persisted(self, seeded_store, run_store, proving_root) -> None:
        record = _run(seeded_store, run_store, proving_root)
        stored = run_store.get_run(record["id"])
        assert stored is not None
        assert stored["status"] == "completed"

    def test_trigger_recorded(self, seeded_store, run_store, proving_root) -> None:
        record = _run(seeded_store, run_store, proving_root, trigger="scheduled")
        assert record["trigger"] == "scheduled"


class TestQClassDataset:
    def test_subject_is_query_class(self, seeded_store, tmp_path) -> None:
        from nova_ai.learning.optimize.personal.synthesizer import (
            PersonalBenchmarkSynthesizer,
        )
        from nova_ai.learning.proving.pipeline import _QClassDataset

        benchmark = PersonalBenchmarkSynthesizer(seeded_store).synthesize(
            min_feedback=0.7, max_samples=60
        )
        dataset = _QClassDataset(benchmark)
        dataset.load()
        subjects = {r.subject for r in dataset._inner._records}
        assert subjects <= {"code", "math", "long", "general"}
        assert len(list(dataset.iter_records())) == dataset.size()

    def test_min_scored_per_class_constant(self) -> None:
        assert MIN_SCORED_PER_CLASS == 3


# ---------------------------------------------------------------------------
# Adoption seam
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("patched_discovery")
class TestAdoption:
    def test_adopt_true_writes_policy_map(
        self, seeded_store, run_store, proving_root
    ) -> None:
        record = _run(seeded_store, run_store, proving_root, adopt=True)
        assert set(record["adopted"].values()) == {CAND}
        assert (proving_root / "policy_map.json").exists()
        import json

        pm = json.loads((proving_root / "policy_map.json").read_text())
        assert pm["code"]["model"] == CAND
        assert pm["code"]["run_id"] == record["id"]

    def test_auto_adopt_config_respected(
        self, seeded_store, run_store, proving_root
    ) -> None:
        config = ProvingConfig(enabled=True, min_samples=10, auto_adopt=True)
        record = _run(seeded_store, run_store, proving_root, config=config)
        assert record["adopted"]

    def test_adopt_false_overrides_auto_adopt(
        self, seeded_store, run_store, proving_root
    ) -> None:
        config = ProvingConfig(enabled=True, min_samples=10, auto_adopt=True)
        record = _run(seeded_store, run_store, proving_root, config=config,
                      adopt=False)
        assert record["adopted"] == {}

    def test_margin_gate_blocks_adoption(
        self, seeded_store, run_store, proving_root
    ) -> None:
        # Delta is exactly 1.0 here, so the margin must exceed it to gate.
        config = ProvingConfig(enabled=True, min_samples=10, min_margin=1.5)
        record = _run(seeded_store, run_store, proving_root, config=config,
                      adopt=True)
        assert all(v["winner"] is None for v in record["per_class"].values())
        assert record["adopted"] == {}


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("patched_discovery")
class TestGuards:
    def test_candidate_equals_incumbent_fails(
        self, seeded_store, run_store, proving_root
    ) -> None:
        record = _run(seeded_store, run_store, proving_root, candidate=INC,
                      incumbent=INC)
        assert record["status"] == "failed"
        assert "incumbent" in record["error"]

    def test_not_enough_samples_fails(
        self, tmp_path, run_store, proving_root
    ) -> None:
        empty = TraceStore(tmp_path / "empty.db")
        config = ProvingConfig(enabled=True, min_samples=10)
        record = _run(empty, run_store, proving_root, config=config)
        assert record["status"] == "failed"
        assert "min_samples" in record["error"]

    def test_unknown_model_fails(self, seeded_store, run_store, proving_root) -> None:
        record = _run(seeded_store, run_store, proving_root, candidate="ghost-model")
        assert record["status"] == "failed"
        assert "ghost-model" in record["error"]
        assert "available" in record["error"]

    def test_run_in_flight_fails(self, seeded_store, run_store, proving_root) -> None:
        run_store.start_run("manual-block", trigger="manual", candidate="a",
                            incumbent="b")
        record = _run(seeded_store, run_store, proving_root)
        assert record["status"] == "failed"
        assert "in flight" in record["error"]

    def test_failed_runs_are_marked_terminal(
        self, seeded_store, run_store, proving_root
    ) -> None:
        _run(seeded_store, run_store, proving_root, candidate=INC, incumbent=INC)
        assert run_store.is_running() is False


# ---------------------------------------------------------------------------
# Judge config
# ---------------------------------------------------------------------------


class TestJudgeConfig:
    def test_judge_model_defaults_to_incumbent(
        self, seeded_store, run_store, proving_root, monkeypatch
    ) -> None:
        seen: dict[str, str] = {}

        class RecordingBackend(CandidateWinsBackend):
            def generate(self, prompt, *, model, system=None, temperature=0.0,
                         max_tokens=1024):
                seen["judge_model"] = model
                return super().generate(prompt, model=model, system=system,
                                        temperature=temperature,
                                        max_tokens=max_tokens)

        monkeypatch.setattr(
            watcher_mod, "list_local_models", lambda cfg: [CAND, INC]
        )
        run_proving(
            candidate=CAND,
            trace_store=seeded_store,
            config=ProvingConfig(enabled=True, min_samples=10),
            run_store=run_store,
            incumbent=INC,
            proving_root=proving_root,
            backend_factory=RecordingBackend,
            judge_backend=RecordingBackend(),
        )
        assert seen["judge_model"] == INC

    def test_config_judge_model_overrides(
        self, seeded_store, run_store, proving_root, monkeypatch
    ) -> None:
        seen: dict[str, str] = {}

        class RecordingBackend(CandidateWinsBackend):
            def generate(self, prompt, *, model, system=None, temperature=0.0,
                         max_tokens=1024):
                seen["judge_model"] = model
                return super().generate(prompt, model=model, system=system,
                                        temperature=temperature,
                                        max_tokens=max_tokens)

        monkeypatch.setattr(
            watcher_mod, "list_local_models", lambda cfg: [CAND, INC]
        )
        config = ProvingConfig(enabled=True, min_samples=10, judge_model="judge-x")
        run_proving(
            candidate=CAND,
            trace_store=seeded_store,
            config=config,
            run_store=run_store,
            incumbent=INC,
            proving_root=proving_root,
            backend_factory=RecordingBackend,
            judge_backend=RecordingBackend(),
        )
        assert seen["judge_model"] == "judge-x"

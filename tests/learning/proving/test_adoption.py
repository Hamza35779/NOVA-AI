"""Tests for the policy map — write/load, margin enforcement, revert."""

from __future__ import annotations

from pathlib import Path

import pytest

from nova_ai.learning.proving.adoption import (
    POLICY_MAP_FILENAME,
    adopt_winners,
    load_policy_map,
    proven_model_for,
    revert_class,
    save_policy_map,
)


@pytest.fixture()
def proving_root(tmp_path: Path) -> Path:
    return tmp_path / "proving"


def _per_class(**overrides):
    base = {
        "code": {"candidate_acc": 0.9, "incumbent_acc": 0.6, "delta": 0.3,
                 "winner": "cand-model", "total": 10},
        "math": {"candidate_acc": 0.5, "incumbent_acc": 0.9, "delta": -0.4,
                 "winner": "inc-model", "total": 10},
        "general": {"candidate_acc": 0.5, "incumbent_acc": 0.5, "delta": 0.0,
                    "winner": None, "total": 10},
    }
    base.update(overrides)
    return base


class TestPolicyMapIo:
    def test_missing_map_is_empty(self, proving_root: Path) -> None:
        assert load_policy_map(proving_root) == {}

    def test_save_creates_root(self, proving_root: Path) -> None:
        path = save_policy_map({"code": {"model": "m"}}, proving_root)
        assert path == proving_root / POLICY_MAP_FILENAME
        assert path.exists()

    def test_round_trip(self, proving_root: Path) -> None:
        pm = {"code": {"model": "m", "margin": 0.2}}
        save_policy_map(pm, proving_root)
        assert load_policy_map(proving_root) == pm

    def test_corrupt_map_is_empty(self, proving_root: Path) -> None:
        proving_root.mkdir(parents=True)
        (proving_root / POLICY_MAP_FILENAME).write_text("{oops")
        assert load_policy_map(proving_root) == {}


class TestAdoptWinners:
    def test_only_candidate_winners_adopted(self, proving_root: Path) -> None:
        adopted = adopt_winners(
            run_id="prove_r1",
            per_class=_per_class(),
            min_margin=0.05,
            proving_root=proving_root,
        )
        assert adopted == {"code": "cand-model"}
        pm = load_policy_map(proving_root)
        assert set(pm) == {"code"}
        assert pm["code"]["model"] == "cand-model"
        assert pm["code"]["run_id"] == "prove_r1"
        assert pm["code"]["margin"] == pytest.approx(0.3)
        assert pm["code"]["adopted_at"]

    def test_margin_enforced(self, proving_root: Path) -> None:
        per_class = _per_class(
            code={"candidate_acc": 0.62, "incumbent_acc": 0.60, "delta": 0.02,
                  "winner": "cand-model", "total": 10},
        )
        adopted = adopt_winners(
            run_id="prove_r1", per_class=per_class, min_margin=0.05,
            proving_root=proving_root,
        )
        assert adopted == {}

    def test_custom_margin(self, proving_root: Path) -> None:
        per_class = _per_class(
            code={"candidate_acc": 0.62, "incumbent_acc": 0.60, "delta": 0.02,
                  "winner": "cand-model", "total": 10},
        )
        adopted = adopt_winners(
            run_id="prove_r1", per_class=per_class, min_margin=0.01,
            proving_root=proving_root,
        )
        assert adopted == {"code": "cand-model"}

    def test_incumbent_winner_not_adopted(self, proving_root: Path) -> None:
        per_class = _per_class(
            code=_per_class()["math"],  # incumbent wins this class
        )
        adopted = adopt_winners(
            run_id="prove_r1", per_class=per_class, min_margin=0.05,
            proving_root=proving_root,
        )
        assert adopted == {}

    def test_merge_with_existing_map(self, proving_root: Path) -> None:
        save_policy_map(
            {"long": {"model": "old-model", "run_id": "prove_old",
                      "margin": 0.1, "adopted_at": "t"}},
            proving_root,
        )
        adopt_winners(
            run_id="prove_r1", per_class=_per_class(), min_margin=0.05,
            proving_root=proving_root,
        )
        pm = load_policy_map(proving_root)
        assert pm["long"]["model"] == "old-model"  # untouched
        assert pm["code"]["model"] == "cand-model"

    def test_no_adopted_means_no_file(self, proving_root: Path) -> None:
        # Incumbent winner / no winner / margin-too-small only → no write.
        per_class = {
            "math": {"candidate_acc": 0.5, "incumbent_acc": 0.9, "delta": -0.4,
                     "winner": "inc-model", "total": 10},
            "general": {"candidate_acc": 0.5, "incumbent_acc": 0.5, "delta": 0.0,
                        "winner": None, "total": 10},
            "code": {"candidate_acc": 0.62, "incumbent_acc": 0.60, "delta": 0.02,
                     "winner": "cand-model", "total": 10},
        }
        adopt_winners(
            run_id="prove_r1", per_class=per_class, min_margin=0.05,
            proving_root=proving_root,
        )
        assert not (proving_root / POLICY_MAP_FILENAME).exists()


class TestRevert:
    def test_revert_removes_entry(self, proving_root: Path) -> None:
        adopt_winners(
            run_id="prove_r1", per_class=_per_class(), min_margin=0.05,
            proving_root=proving_root,
        )
        assert revert_class("code", proving_root=proving_root) is True
        assert load_policy_map(proving_root) == {}

    def test_revert_missing_returns_false(self, proving_root: Path) -> None:
        assert revert_class("code", proving_root=proving_root) is False


class TestProvenModelFor:
    def test_returns_model(self, proving_root: Path) -> None:
        save_policy_map(
            {"code": {"model": "cand-model", "run_id": "r", "margin": 0.1,
                      "adopted_at": "t"}},
            proving_root,
        )
        assert proven_model_for("code", proving_root=proving_root) == "cand-model"

    def test_missing_class_none(self, proving_root: Path) -> None:
        assert proven_model_for("math", proving_root=proving_root) is None

    def test_missing_root_none(self, tmp_path: Path) -> None:
        assert (
            proven_model_for("code", proving_root=tmp_path / "nothing") is None
        )

    def test_empty_model_none(self, proving_root: Path) -> None:
        save_policy_map({"code": {"model": "", "run_id": "r"}}, proving_root)
        assert proven_model_for("code", proving_root=proving_root) is None

"""Tests for race_models — sibling generation, judging, preference recording."""

from __future__ import annotations

import pytest

from nova_ai.conversations.racer import _extract_content, race_models
from nova_ai.conversations.store import ConversationStore


class FakeEngine:
    engine_id = "fake"

    def __init__(self, answers=None) -> None:
        self.answers = answers or {}
        self.calls = []

    def generate(self, messages, *, model, temperature=0.7, max_tokens=1024, **kw):
        self.calls.append(model)
        content = self.answers.get(model, f"answer from {model}")
        return {"content": content}


class BoomEngine:
    engine_id = "boom"

    def generate(self, messages, *, model, **kw):
        raise RuntimeError("engine down")


class FakeJudge:
    def __init__(self, verdict="YES") -> None:
        self.verdict = verdict
        self.calls = 0

    def generate(self, prompt, model="", system="", **kw):
        self.calls += 1
        return f"{self.verdict}\nshort reason"


@pytest.fixture()
def store(tmp_path):
    s = ConversationStore(tmp_path / "c.db")
    conv = s.create_conversation("racing")
    root = s._conn.execute(
        "SELECT id FROM conv_nodes WHERE conversation_id = ?",
        (conv["id"],),
    ).fetchone()[0]
    user = s.add_message(conv["id"], root, "user", "what is 2+2?")
    yield s, conv["id"], user
    s.close()


class TestExtractContent:
    def test_dict_content(self):
        assert _extract_content({"content": "hi"}) == "hi"

    def test_message_dict(self):
        assert _extract_content({"message": {"content": "m"}}) == "m"

    def test_raw_string(self):
        assert _extract_content("raw") == "raw"

    def test_unknown_shape(self):
        assert _extract_content({"weird": 1}) == ""


class TestRaceModels:
    def test_generates_one_sibling_per_model(self, store):
        s, conv_id, user = store
        engine = FakeEngine()
        result = race_models(
            store=s, parent_node_id=user, models=["m1", "m2"], engine=engine
        )
        assert len(result["candidates"]) == 2
        kids = s.children(user)
        assert len(kids) == 2
        assert all(k["role"] == "assistant" for k in kids)

    def test_winner_is_first_without_judge(self, store):
        s, conv_id, user = store
        result = race_models(
            store=s, parent_node_id=user, models=["m1", "m2"], engine=FakeEngine()
        )
        assert result["winner_model"] == "m1"

    def test_judge_yes_keeps_first(self, store):
        s, conv_id, user = store
        result = race_models(
            store=s,
            parent_node_id=user,
            models=["m1", "m2"],
            engine=FakeEngine(),
            judge=FakeJudge("YES"),
        )
        assert result["winner_model"] == "m1"

    def test_judge_no_flips_winner(self, store):
        s, conv_id, user = store
        result = race_models(
            store=s,
            parent_node_id=user,
            models=["m1", "m2"],
            engine=FakeEngine(),
            judge=FakeJudge("NO"),
        )
        assert result["winner_model"] == "m2"

    def test_preference_pair_recorded(self, store):
        s, conv_id, user = store
        result = race_models(
            store=s,
            parent_node_id=user,
            models=["m1", "m2"],
            engine=FakeEngine(),
            judge=FakeJudge("NO"),
        )
        pairs = s.list_preference_pairs()
        assert len(pairs) == 1
        assert pairs[0]["chosen_id"] == result["winner_node_id"]
        assert pairs[0]["source"] == "race"
        assert pairs[0]["prompt_path"][0]["content"] == "what is 2+2?"

    def test_failed_generation_recorded_as_failed(self, store):
        s, conv_id, user = store
        result = race_models(
            store=s, parent_node_id=user, models=["m1", "m2"], engine=BoomEngine()
        )
        assert all("[generation failed" in c["content"] for c in result["candidates"])
        kids = s.children(user)
        assert all(k["metadata"].get("success") is False for k in kids)

    def test_unknown_parent_raises(self, store):
        s, _conv_id, _user = store
        with pytest.raises(ValueError, match="unknown parent"):
            race_models(store=s, parent_node_id="nope", models=["m1"], engine=FakeEngine())

    def test_single_model_skips_judge(self, store):
        s, conv_id, user = store
        judge = FakeJudge("NO")
        result = race_models(
            store=s, parent_node_id=user, models=["m1"], engine=FakeEngine(), judge=judge
        )
        assert judge.calls == 0
        assert result["winner_model"] == "m1"

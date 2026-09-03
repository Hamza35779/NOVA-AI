"""Tests for the conversation tree REST API (fork / regen / race / pick)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from nova_ai.core import paths as paths_mod
    from nova_ai.server import conversation_routes as conv_mod

    monkeypatch.setattr(paths_mod, "get_config_dir", lambda: tmp_path)
    monkeypatch.setattr(conv_mod, "get_config_dir", lambda: tmp_path)

    from nova_ai.server.app import create_app

    app = create_app(engine=None, model="dummy")
    return TestClient(app)


def _create_conv(client, title="Fork test"):
    res = client.post("/api/conversations", json={"title": title})
    assert res.status_code == 200
    return res.json()


def _add_message(client, conv_id, parent_id, role, content, **kw):
    res = client.post(
        f"/api/conversations/{conv_id}/messages",
        json={"role": role, "content": content, "parent_id": parent_id, **kw},
    )
    assert res.status_code == 200
    return res.json()["node_id"]


class TestConversationAPI:
    def test_create_and_list(self, client):
        conv = _create_conv(client)
        assert conv["root_id"]
        listing = client.get("/api/conversations").json()
        assert listing["conversations"][0]["id"] == conv["id"]

    def test_add_message_default_parent_is_root(self, client):
        conv = _create_conv(client)
        res = client.post(
            f"/api/conversations/{conv['id']}/messages",
            json={"role": "user", "content": "hi"},
        )
        assert res.status_code == 200
        assert res.json()["parent_id"] == conv["root_id"]

    def test_tree_endpoint(self, client):
        conv = _create_conv(client)
        _add_message(client, conv["id"], conv["root_id"], "user", "hello")
        tree = client.get(f"/api/conversations/{conv['id']}/tree").json()
        assert len(tree["nodes"]) == 2
        assert conv["root_id"] in tree["children"]

    def test_tree_unknown_conversation_404(self, client):
        assert client.get("/api/conversations/conv_nope/tree").status_code == 404

    def test_add_message_bad_parent_404(self, client):
        conv = _create_conv(client)
        res = client.post(
            f"/api/conversations/{conv['id']}/messages",
            json={"role": "user", "content": "x", "parent_id": "node_nope"},
        )
        assert res.status_code == 404

    def test_fork_creates_sibling(self, client):
        conv = _create_conv(client)
        root = conv["root_id"]
        user = _add_message(client, conv["id"], root, "user", "hello")
        a1 = _add_message(client, conv["id"], user, "assistant", "first answer")
        res = client.post(
            f"/api/conversations/{conv['id']}/fork",
            json={"node_id": a1},
        )
        assert res.status_code == 200
        fork_id = res.json()["fork_node_id"]
        # The fork is a sibling of the original, not a child.
        fork_node = client.get(f"/api/conversations/{conv['id']}/tree").json()
        nodes = {n["id"]: n for n in fork_node["nodes"]}
        assert nodes[fork_id]["parent_id"] == user
        assert nodes[fork_id]["metadata"].get("fork_of") == a1

    def test_regen_without_engine_503(self, client):
        conv = _create_conv(client)
        root = conv["root_id"]
        user = _add_message(client, conv["id"], root, "user", "q")
        _add_message(client, conv["id"], user, "assistant", "a")
        res = client.post(
            f"/api/conversations/{conv['id']}/regenerate", json={}
        )
        assert res.status_code == 503

    def test_race_requires_two_models(self, client):
        conv = _create_conv(client)
        res = client.post(
            f"/api/conversations/{conv['id']}/race",
            json={"models": ["only-one"]},
        )
        assert res.status_code == 400

    def test_race_with_fake_engine(self, client, monkeypatch):
        """Full race flow with a stubbed app.state.engine."""
        conv = _create_conv(client)
        root = conv["root_id"]
        _add_message(client, conv["id"], root, "user", "pick one")

        class FakeEngine:
            engine_id = "fake"

            def generate(self, messages, *, model, **kw):
                return {"content": f"answer-{model}"}

        from nova_ai.server import conversation_routes as conv_mod

        monkeypatch.setattr(
            conv_mod, "_build_judge", lambda request: None
        )
        # Inject the engine into app state via the TestClient's app.
        client.app.state.engine = FakeEngine()
        res = client.post(
            f"/api/conversations/{conv['id']}/race",
            json={"models": ["m1", "m2"]},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["winner_model"] == "m1"
        pairs = client.get("/api/conversations/preference-pairs").json()
        assert pairs["total"] == 1
        assert pairs["pairs"][0]["chosen_id"] == body["winner_node_id"]

    def test_pick_records_preference(self, client):
        conv = _create_conv(client)
        root = conv["root_id"]
        user = _add_message(client, conv["id"], root, "user", "hello")
        a1 = _add_message(client, conv["id"], user, "assistant", "left")
        a2 = _add_message(client, conv["id"], user, "assistant", "right")
        res = client.post(
            f"/api/conversations/nodes/{a2}/pick",
            json={"chosen_node_id": a2, "source": "regen"},
        )
        assert res.status_code == 200
        assert res.json()["chosen"] == a2
        assert res.json()["rejected"] == [a1]

    def test_pick_without_siblings_400(self, client):
        conv = _create_conv(client)
        root = conv["root_id"]
        user = _add_message(client, conv["id"], root, "user", "hello")
        only = _add_message(client, conv["id"], user, "assistant", "only")
        res = client.post(
            f"/api/conversations/nodes/{only}/pick",
            json={"chosen_node_id": only},
        )
        assert res.status_code == 400

    def test_node_feedback(self, client):
        conv = _create_conv(client)
        root = conv["root_id"]
        user = _add_message(client, conv["id"], root, "user", "hello")
        res = client.post(
            f"/api/conversations/nodes/{user}/feedback", json={"score": 1.0}
        )
        assert res.status_code == 200
        assert client.post(
            "/api/conversations/nodes/node_nope/feedback", json={"score": 1.0}
        ).status_code == 404

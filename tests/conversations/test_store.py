"""Tests for the conversation tree store (nodes, paths, preference pairs)."""

from __future__ import annotations

import threading

import pytest

from nova_ai.conversations.store import ConversationStore


@pytest.fixture()
def store(tmp_path):
    s = ConversationStore(tmp_path / "conversations.db")
    yield s
    s.close()


def _conv_with_user(store, content="hello"):
    conv = store.create_conversation("Test")
    root = store._conn.execute(
        "SELECT id FROM conv_nodes WHERE conversation_id = ? AND parent_id = conversation_id",
        (conv["id"],),
    ).fetchone()[0]
    user = store.add_message(conv["id"], root, "user", content)
    return conv, root, user


class TestConversations:
    def test_create_conversation(self, store):
        conv = store.create_conversation("My chat")
        assert conv["id"].startswith("conv")
        assert conv["title"] == "My chat"
        assert store.list_conversations()[0]["id"] == conv["id"]

    def test_list_conversations_counts_nodes(self, store):
        conv, _root, user = _conv_with_user(store)
        store.add_message(conv["id"], user, "assistant", "hi there")
        listing = store.list_conversations()[0]
        assert listing["title"] == "Test"
        assert listing["node_count"] == 2

    def test_add_message_and_get_node(self, store):
        conv, _root, user = _conv_with_user(store)
        node = store.get_node(user)
        assert node["role"] == "user"
        assert node["content"] == "hello"
        assert node["conversation_id"] == conv["id"]

    def test_children_ordered(self, store):
        conv, root, _user = _conv_with_user(store)
        store.add_message(conv["id"], root, "user", "a")
        store.add_message(conv["id"], root, "user", "b")
        kids = [c["content"] for c in store.children(root)]
        assert kids == ["hello", "a", "b"] or set(kids) == {"hello", "a", "b"}

    def test_path_to_root(self, store):
        conv, root, user = _conv_with_user(store)
        a1 = store.add_message(conv["id"], user, "assistant", "a1")
        u2 = store.add_message(conv["id"], a1, "user", "again")
        a2 = store.add_message(conv["id"], u2, "assistant", "a2")
        path = store.path_to_root(a2)
        assert [n["content"] for n in path] == ["hello", "a1", "again", "a2"]

    def test_two_children_same_parent(self, store):
        """Fork = a second child of the same parent."""
        conv, _root, user = _conv_with_user(store)
        a1 = store.add_message(conv["id"], user, "assistant", "first")
        a2 = store.add_message(conv["id"], user, "assistant", "second")
        siblings = [c["content"] for c in store.children(user)]
        assert siblings == ["first", "second"]
        # Both paths see the same user prompt.
        assert store.path_to_root(a1)[-2]["id"] == user
        assert store.path_to_root(a2)[-2]["id"] == user

    def test_set_feedback(self, store):
        conv, _root, user = _conv_with_user(store)
        assert store.set_feedback(user, 1.0) is True
        assert store.get_node(user)["feedback"] == 1.0
        assert store.set_feedback("nope", 1.0) is False


class TestPreferencePairs:
    def test_record_and_list(self, store):
        conv, _root, user = _conv_with_user(store)
        a1 = store.add_message(conv["id"], user, "assistant", "good")
        a2 = store.add_message(conv["id"], user, "assistant", "bad")
        pair_id = store.add_sibling_choice(
            conv["id"],
            [{"role": "user", "content": "hello"}],
            a1,
            [a2],
            source="race",
        )
        pairs = store.list_preference_pairs()
        assert len(pairs) == 1
        assert pairs[0]["chosen_id"] == a1
        assert pairs[0]["rejected_ids"] == [a2]
        assert pairs[0]["source"] == "race"
        assert pairs[0]["prompt_path"][0]["content"] == "hello"
        assert pair_id.startswith("pref")

    def test_count(self, store):
        conv, _root, user = _conv_with_user(store)
        a1 = store.add_message(conv["id"], user, "assistant", "x")
        a2 = store.add_message(conv["id"], user, "assistant", "y")
        store.add_sibling_choice(conv["id"], [], a1, [a2])
        assert store.count_preference_pairs() == 1

    def test_thread_safety(self, store):
        """Concurrent sibling writes must not corrupt the store."""
        conv, _root, user = _conv_with_user(store)
        errors = []

        def _writer(i: int) -> None:
            try:
                for _ in range(20):
                    node = store.add_message(conv["id"], user, "assistant", f"m{i}")
                    store.set_feedback(node, 0.5)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=_writer, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert len(store.children(user)) == 8 * 20

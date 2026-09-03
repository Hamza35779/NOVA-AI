"""Conversation forking — tree-shaped chats, model races, preference data.

A conversation is a **tree**: forking or regenerating creates a sibling
under the same parent instead of overwriting history. Sibling choices
(chosen vs rejected answers) are recorded as preference pairs — the
training data for the DPO lane (``learning.training.dpo``).
"""

from nova_ai.conversations.racer import race_models
from nova_ai.conversations.store import ConversationStore

__all__ = ["ConversationStore", "race_models"]

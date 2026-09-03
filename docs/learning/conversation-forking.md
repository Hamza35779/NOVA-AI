---
title: Conversation Forking
description: Fork the conversation, race two models on the real query, keep the winner — and every pick becomes DPO training data
---

# Conversation Forking: keep the winner, train on the choice

Most chat apps make you *accept* an answer. NOVA lets you **keep both** — and then asks which one was better. Fork the conversation to get a second branch, regenerate for a fresh sibling answer, race two models head-to-head on the real query. Your pick is recorded as a **preference pair**, and the DPO training lane turns those pairs into a model that answers the way *you* would have chosen.

**The pitch: every fork, regen, and race ends in a pick — and every pick is training data.**

## The preference flywheel

```
   ┌──────────────┐    ┌──────────────────┐    ┌───────────────────┐
   │ Conversation │───▶│ Fork / Regenerate│───▶│ Model race        │
   │ tree (nodes  │    │ = sibling answer │    │ 2+ models, one    │
   │ with parent) │    │ under same prompt│    │ prompt, judged    │
   └──────────────┘    └──────────────────┘    └─────────┬─────────┘
                                                         ▼
   ┌──────────────┐    ┌──────────────────┐    ┌───────────────────┐
   │ nova train   │◀───│ preference_pairs │◀───│ You pick (app /   │
   │ run --lane   │    │ table: chosen vs │    │ auto-judge first- │
   │ dpo          │    │ rejected, source │    │ line YES/NO)      │
   └──────────────┘    └──────────────────┘    └───────────────────┘
```

## How the tree works

Conversations are stored as a **tree of nodes**, not a linear transcript. Every message is a node with a `parent_id`; the visible conversation is one root-to-tip path. A fork is not a copy — it is a **second child of the same parent**, so both branches see the identical history and nothing is duplicated:

```
(root) ── user: "review this patch"
             ├── assistant: "ship it"            ◀ pick this
             └── assistant: "one bug: off-by-1"   (sibling from fork/regen/race)
```

- **Fork** (`POST /api/conversations/{id}/fork`, app Fork button) — creates a sibling of the chosen node carrying the same content with a `fork_of` metadata marker. Continue down either branch.
- **Regenerate** (`POST /api/conversations/{id}/regenerate`) — generates a fresh assistant answer under the same prompt node via the server engine, returning the new sibling and the existing ones. In the app: the Regenerate button under the last assistant message. Cycle through siblings with the «» arrows.
- **Race** (`POST /api/conversations/{id}/race`) — races 2+ models on one prompt node. Each model becomes a sibling assistant node. With `judge: true` (or `nova conversation` auto-judging) a strict judge compares the two strongest candidates with the same first-line YES/NO convention as the [Proving Ground](proving-ground.md); the winner is recorded automatically.

## Recording a pick

Sibling groups only become training data when a **choice** is made — by you or the judge:

- **In the app** — picking a sibling with the arrows records the pair (`source: regen`); racing records it automatically (`source: race`).
- **In the CLI** — `nova conversation pick NODE_ID --source fork` marks one sibling chosen and its sisters rejected.
- **From traces** — the DPO miner also reads the trace store: the same query asked twice with feedback improving (`source: regen`), or a thumbs-down followed by a later better answer (`source: thumbs`).

Each pick writes one `preference_pairs` row: the full `prompt_path`, `chosen_id`, `rejected_ids`, `source` (`fork | regen | race | thumbs`), timestamp. Provenance is complete — you can always ask *why* the model was shown a choice.

## The DPO lane

The pairs feed a second training lane alongside the SFT loop. Where SFT teaches the model *what a good answer looks like*, **DPO (Direct Preference Optimization)** teaches it *which of two answers is better* — exactly the signal forking produces.

```bash
# See how much preference data you have
nova conversation pairs

# Train a DPO adapter (same benchmark gate + pending review as SFT)
nova train run --lane dpo
```

- Config: `[learning.training] dpo_enabled = true`, `dpo_min_pairs = 20`, `dpo_tag_prefix = "nova-dpo"`.
- Adapters land under `adapters/<run_id>/dpo/`, run records carry `lane = "dpo"`, and Ollama deploys tag as `nova-dpo-<model>` — so the [Proving Ground](proving-ground.md) can prove the tuned adapter against the base automatically.
- Scheduling works too: `nova scheduler create "nightly dpo" --cron "0 4 * * *" --metadata '{"kind": "train", "lane": "dpo"}'`.

Details, config, and the trainer's own knobs (β, LoRA rank, epochs): [Self-Training → Preference tuning lane](self-training.md#preference-tuning-lane).

## Quickstart

```bash
# Headless fallback for the app UI
nova conversation list
nova conversation show CONV_ID          # ASCII tree, ◀ marks the active path
nova conversation show CONV_ID --node NODE_ID

# Record a choice between sibling answers
nova conversation pick NODE_ID --source fork

# Count the DPO data you have accrued
nova conversation pairs                 # or --json for scripts
```

## API reference

All endpoints are mounted under `/api/conversations` in the server app:

| Endpoint | Purpose |
|----------|---------|
| `POST /api/conversations` | Create a conversation (`{title}`) → `{id, root_id}` |
| `GET /api/conversations` | List conversations (id, title, node count, last activity) |
| `GET /api/conversations/{id}/tree` | Whole tree: `{nodes, children}` keyed by parent |
| `POST /api/conversations/{id}/messages` | Add a node (`{role, content, parent_id?}`) |
| `POST /api/conversations/{id}/fork` | Sibling fork of a node (`{node_id}`) |
| `POST /api/conversations/{id}/regenerate` | Fresh engine-generated sibling answer |
| `POST /api/conversations/{id}/race` | `{models, prompt_node_id?, judge?}` → per-model candidates + winner |
| `POST /api/conversations/nodes/{id}/feedback` | Attach a thumbs score to a node |
| `POST /api/conversations/nodes/{id}/pick` | `{chosen_node_id, source?}` → preference pair |
| `GET /api/conversations/preference-pairs` | Recorded pairs (the DPO miner's input) |

## Artifacts

| Path | Contents |
|------|----------|
| `~/.nova_ai/conversations.db` | The conversation tree + preference pairs |

## See also

- [Self-Training — Preference tuning lane](self-training.md#preference-tuning-lane) — what happens to the pairs.
- [Model Proving Ground](proving-ground.md) — the same head-to-head + judge discipline, for models instead of answers.
- [Memory Consolidation](memory-consolidation.md) — the other consumer of your conversation history.

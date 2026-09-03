---
title: Memory Consolidation
description: NOVA sleeps on your conversations and wakes up smarter — distilling durable facts into a core memory it injects into every query
---

# Memory Consolidation: NOVA's sleep cycle

Every chat leaves traces, and the useful parts — your stack, your naming conventions, "deploys on Fridays are forbidden", the project you keep circling back to — stay scattered across hundreds of rows. Memory consolidation is a **sleep cycle**: on schedule (or on demand) NOVA replays recent conversations, clusters the related ones, and distills them into a short list of **atomic facts** with provenance. Those facts become a compact **core memory** prepended to every query, so NOVA *stays* knowing you without you re-explaining.

**The pitch: NOVA sleeps on your conversations and wakes up smarter.**

## The cycle

```
   ┌──────────────┐    ┌──────────────────┐    ┌───────────────────┐
   │ Recent traces│───▶│ SessionMiner     │───▶│ Fact extraction   │
   │ (traces.db)  │    │ (class buckets + │    │ (local LLM per    │
   │              │    │  embedding       │    │  cluster → JSON)  │
   └──────────────┘    │  clusters)       │    └─────────┬─────────┘
                       └──────────────────┘              ▼
   ┌──────────────┐    ┌──────────────────┐    ┌───────────────────┐
   │ Core memory  │◀───│ facts.db         │◀───│ Dedup + resolve   │
   │ in every     │    │ (confidence,     │    │ contradictions    │
   │ query        │    │  provenance)     │    │ (recency+conf)    │
   └──────────────┘    └──────────────────┘    └───────────────────┘
```

1. **Mine** — recent traces are bucketed by query class (`code` / `math` / …), then optionally split further by embedding similarity within each class. Clusters smaller than `min_session_messages` are dropped: one-off chats are noise, patterns are signal.
2. **Distill** — each cluster goes to the local model with a strict extraction prompt (JSON array of `{content, topic, confidence}` — no prose). Clusters fail independently; a broken cluster never sinks the run.
3. **Resolve** — new facts are deduplicated against the active fact base (exact/containment match → the old row is *touched*, its `last_seen` refreshed). Contradictions ("prefers tabs" vs "does not prefer tabs") are resolved by **confidence**: a strictly more confident new fact supersedes the old one; an unconfident one is recorded *alongside* and both stay.
4. **Decay** — facts untouched for `decay_days` flip from `active` to `decayed` and stop being served. Memory that isn't reinforced fades — like yours.
5. **Serve** — active facts render as a `## What NOVA knows about you` block (packed under `core_memory_max_chars`, highest confidence first) and are injected as a system message on every query.

## Quickstart

```toml
# ~/.nova_ai/config.toml
[learning.consolidation]
enabled = true
```

```bash
# Run one cycle (background by default, --foreground to watch it work)
nova memory consolidate run --foreground

# Inspect what NOVA learned
nova memory consolidate status      # latest run summary
nova memory consolidate facts       # the fact base as a table

# Something wrong or stale? Remove it — the manual override always wins
nova memory consolidate forget fact_ab12cd34ef56
```

Fact provenance is preserved end-to-end: every fact stores the trace IDs of the conversations it was distilled from, so you can always trace a "fact" back to where NOVA got it.

## Running it nightly

Create a scheduler task with `kind="consolidate"` metadata (requires `[learning.consolidation] enabled = true`):

```bash
nova scheduler create "memory sleep cycle" --cron "30 3 * * *" \
  --metadata '{"kind": "consolidate"}'
```

The scheduled run behaves exactly like a foreground run and logs `[consolidate] run consol_…: completed (facts_added=N, …)` to the task's run log.

## The injection contract

Core-memory injection is **fail-open everywhere**: an empty fact base injects nothing, a broken fact store logs at debug and the query proceeds untouched, and the block is capped at `core_memory_max_chars` so it can never crowd out your actual prompt. It composes with (and runs after) the existing vector-memory context injection — vector memory provides *what you told NOVA before*, core memory provides *what NOVA concluded*.

## Safety model

1. **Off by default** — `enabled = false`; nothing runs until you opt in.
2. **Manual override is supreme** — `forget` removes a fact instantly; a superseded fact keeps its row (status `superseded`, with `superseded_by`) so history is auditable.
3. **Local-only** — extraction uses your configured local engine (`judge_model = ""` → `intelligence.default_model`); no conversation content leaves the machine.
4. **Bounded** — `max_facts_per_run` caps distillation per run; the served block is capped by characters.

## Config reference

```toml
[learning.consolidation]
enabled = false              # master switch
schedule = ""                # cron expression; empty = run manually
min_session_messages = 6     # skip clusters smaller than this
max_facts_per_run = 50       # cap on facts distilled per run
judge_model = ""             # "" uses intelligence.default_model
decay_days = 90              # facts untouched this long stop being served
core_memory_max_chars = 4000 # core-memory block budget
```

## Artifacts

| Path | Contents |
|------|----------|
| `~/.nova_ai/learning/consolidation/facts.db` | Fact base (`nova memory consolidate facts`) |
| `~/.nova_ai/learning/consolidation/runs.db` | Run history (`nova memory consolidate status`) |
| `~/.nova_ai/learning/consolidation/last_run.log` | Background run output |

## CLI reference

| Command | What it does |
|---------|-------------|
| `nova memory consolidate run [--foreground]` | Run one sleep cycle |
| `nova memory consolidate status` | Latest run summary |
| `nova memory consolidate facts [-n N]` | Fact table (confidence, topic, content) |
| `nova memory consolidate forget FACT_ID` | Remove a fact (manual override) |

## See also

- [Model Proving Ground](proving-ground.md) — the same distill→verify→adopt-by-hand discipline, for models.
- [Memory](../user-guide/memory.md) — the vector memory store consolidation composes with.
- [Conversation Forking](conversation-forking.md) — the other way your conversation history becomes training signal.

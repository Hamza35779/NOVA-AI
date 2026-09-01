---
title: Model Proving Ground
description: NOVA A/B-tests new models against your real workloads and only uses them where they win
---

# Model Proving Ground: only adopt models that win on YOUR traces

Pulling a new model today is vibes: a vendor benchmark says it's good, you `ollama pull`, and hope it's better for *your* work. The proving ground replaces hope with measurement. NOVA synthesizes an evaluation set from **your own high-feedback traces**, runs the candidate and your incumbent head-to-head under the **same judge**, and reports a verdict **per query class** (`code` / `math` / `long` / `short` / `general`). Adoption is manual by default and reversible with one command.

**The pitch: pull any new model — NOVA tests it against your real workloads and only uses it where it wins.**

## The gauntlet

```
   ┌──────────────┐    ┌────────────────────┐    ┌──────────────────┐
   │ Your traces  │───▶│ Personal benchmark │───▶│ Head-to-head     │
   │ (feedback    │    │ (query + reference │    │ candidate vs     │
   │  ≥ 0.7)      │    │  per high rating)  │    │ incumbent        │
   └──────────────┘    └────────────────────┘    └────────┬─────────┘
                                                          ▼
   ┌──────────────────┐    ┌────────────────────┐    ┌──────────────────┐
   │ Router serves    │◀───│ policy_map.json    │◀───│ Per-class verdict│
   │ proven models    │    │ (nova prove adopt) │    │ (Δ accuracy per  │
   │ (opt-in)         │    │                    │    │  class, margin)  │
   └──────────────────┘    └────────────────────┘    └──────────────────┘
```

Fairness rules baked in:

- **Same benchmark both sides.** Samples are synthesized once from your traces; both models answer identical questions with identical prompts, temperature 0, and the same seed.
- **Same judge both sides.** The judge defaults to the *incumbent model itself* (`judge_model = ""`), so no third model gets to play favorites. Fully offline.
- **Evidence thresholds.** A class gets a verdict only with ≥ 3 scored samples on both sides; adoption additionally requires the candidate to win by at least `min_margin` (default `0.05`).

## Quickstart

```toml
# ~/.nova_ai/config.toml
[learning.proving]
enabled = true
```

```bash
# Run the gauntlet (background by default, --foreground to stream the scorecard)
nova prove run qwen3:8b --incumbent qwen2.5:7b --foreground

# Inspect results
nova prove status        # latest run + per-class scorecard
nova prove list          # run history

# Adopt winners per class — this is the only mutation, and it's explicit
nova prove adopt prove_20260902_101530_ab12cd
nova prove roster        # what the router would serve per class
nova prove revert code   # undo an adoption any time
```

A scorecard looks like:

```
Per-Query-Class Scorecard
Class     Candidate   Incumbent   Δ      Winner
code           100%         60%   +0.40  qwen3:8b
math            60%         60%   +0.00  —
long            80%         60%   +0.20  qwen3:8b
general         60%         80%   -0.20  qwen2.5:7b
```

`general` shows the incumbent is better — adopting that run takes `code` and `long` only, and your incumbent keeps serving `math` and `general`.

## Serving proven models

Adoption writes `~/.nova_ai/learning/proving/policy_map.json` (`class → model`), but the router does **not** act on it until you opt in:

```toml
# in config.toml — under the section your engine's router reads
proving_adoption = true
```

With `proving_adoption` enabled, SmartRouter classifies the incoming query and serves the proven model for that class when the engine can serve it; anything unservable or unmapped falls back to the normal tier flow. Every failure mode degrades to "keep routing as before" — a corrupt map can never break routing.

## Watch for new models automatically

```bash
nova prove watch            # report newly pulled models
nova prove watch --prove    # prove each new model as it appears
```

The watcher keeps a snapshot at `~/.nova_ai/learning/proving/known_models.json`. A model pulled again after removal counts as new.

To run the check on a schedule, create a scheduler task with `kind="prove"` metadata (the daemon runs it with your cron schedule):

```bash
nova scheduler create "prove new models" --cron "0 4 * * *" \
  --metadata '{"kind": "prove"}'
```

The scheduled task checks for new models and proves them when both `[learning.proving] enabled` **and** `auto_trigger` are true.

## The flywheel with self-training

`nova train deploy --target ollama` creates `nova-tuned-<model>` tags. Those are new models too — the watcher sees them, the gauntlet tests *tuned vs base* per class, and the router adopts tuning only where it actually helped. Closed loop: use NOVA → rate answers → train → prove → route better.

## Safety model

The gauntlet is **read-only** — it burns GPU time, never changes behavior. Adoption is the only mutation, and it's:

1. **Manual by default** (`auto_adopt = false`): winners wait for `nova prove adopt`.
2. **Margin-gated**: a class is adopted only when the candidate won by ≥ `min_margin`.
3. **Reversible**: `nova prove revert <class>` removes an entry instantly.
4. **Off unless opted in at the router too**: even an adopted map is inert until `proving_adoption = true`.

## Config reference

```toml
[learning.proving]
enabled = false             # master switch
auto_trigger = false        # prove automatically when a new model appears
auto_adopt = false          # adopt winners without `nova prove adopt`
min_margin = 0.05           # per-class accuracy margin required to adopt
min_samples = 10            # minimum synthesized benchmark samples per run
max_samples = 60            # cap on benchmark size (bounds GPU time)
schedule = ""               # cron expression (reserved for the prove task)
incumbent = ""              # default opponent; "" → intelligence.default_model
judge_engine = "local"      # "local" | "cloud" — engine backing the judge
judge_model = ""            # "" → judge with the incumbent (same judge both sides)
```

## Artifacts

| Path | Contents |
|------|----------|
| `~/.nova_ai/learning/proving/runs.db` | Run history (`nova prove list`) |
| `~/.nova_ai/learning/proving/policy_map.json` | Adopted per-class routing (`nova prove roster`) |
| `~/.nova_ai/learning/proving/known_models.json` | Watcher snapshot of seen models |
| `~/.nova_ai/learning/proving/last_run.log` | Background run output |

## CLI reference

| Command | What it does |
|---------|-------------|
| `nova prove run <candidate> [--incumbent <m>] [--foreground] [--adopt]` | Run the gauntlet |
| `nova prove status` | Latest run + per-class scorecard |
| `nova prove list [-n N]` | Run history |
| `nova prove roster` | Current adoption map |
| `nova prove adopt <run_id> [--class code,math]` | Adopt winners into the map |
| `nova prove revert <class>` | Remove a class from the map |
| `nova prove watch [--prove] [--foreground]` | New-model check, optionally prove |

## Requirements

A working engine backend for both models (e.g. Ollama running locally with both models pulled) and enough high-feedback traces to synthesize `min_samples` benchmark samples. Rate your NOVA answers (`nova feedback`) to build the evaluation data — the proving ground is only as good as the traces it learns from.

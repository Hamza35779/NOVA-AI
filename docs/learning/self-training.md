---
title: Self-Training
description: NOVA AI fine-tunes itself on your usage traces — offline, gated, and under your control
---

# Self-Training: NOVA learns how *you* use it

NOVA's self-training pipeline turns your recorded interaction traces into a **LoRA adapter** for your local model. The loop is fully offline: mine traces → extract supervised pairs → fine-tune → benchmark gate → deploy. No other local-AI platform does this — most ship a runtime; NOVA ships a feedback loop.

## The loop

```
   ┌────────────┐    ┌──────────────┐    ┌───────────────┐    ┌─────────┐
   │  Traces    │───▶│  SFT pairs   │───▶│  LoRA train   │───▶│  Gate   │
   │ (feedback  │    │ (miner, 0.7+ │    │ (rank 16,     │    │(bench Δ)│
   │  ≥ 0.7)    │    │  quality)    │    │  Qwen default)│    └────┬────┘
   └────────────┘    └──────────────┘    └───────────────┘         │
        ▲                                                          ▼
        │                                              ┌────────────────────┐
        │                                              │ deploy_targets:    │
        └────────────── use NOVA, rate answers ◀────── │ adapter / ollama / │
                                                       │ llamacpp           │
                                                       └────────────────────┘
```

## Quickstart

```toml
# ~/.nova_ai/config.toml
[learning.training]
enabled = true
deploy_targets = ["adapter", "ollama"]
min_pairs = 50
```

```bash
# Export your trace data any time (portable JSONL)
nova train export-traces --out pairs.jsonl

# Start a training run in the background
nova train run

# Check progress / inspect results
nova train status
nova train list
```

When a run finishes with `pending_review`, promote it manually:

```bash
nova train deploy <run-id> --target ollama   # creates nova-tuned-<model>
```

## Safety model

Weight updates are the most invasive edit class in the learning system — the spec-search planner pins `lora_finetune` at **MANUAL** risk tier. Three layers protect you:

1. **Benchmark gate** — after training, both the base and tuned models are scored on the personal benchmark. If the delta is below `learning.min_improvement` (default `0.02`), the run is marked `rolled_back` and the adapter is never activated or deployed.
2. **Pending review by default** — unless `auto_apply = true`, a passing run lands in `pending_review`. `active.json` is untouched; promotion requires an explicit `nova train deploy`.
3. **Auto-trigger is doubly opt-in** — automatic training fires only when *both* `learning.auto_update` and `learning.training.auto_trigger` are true, and scheduled runs (cron) only when `enabled = true`.

## Config reference

```toml
[learning.training]
enabled = false            # master switch
schedule = ""              # cron expression for scheduled (nightly) runs
auto_trigger = false       # train when enough new qualifying traces accrue
auto_apply = false         # deploy without manual review (gate still enforced)
min_pairs = 50             # minimum SFT pairs before a run is worth starting
max_pairs = 5000           # cap per run (bounds training time)
deploy_targets = ["adapter", "ollama"]   # subset: adapter, ollama, llamacpp
ollama_tag_prefix = "nova-tuned"
llamacpp_gguf_script = ""  # path to llama.cpp convert_hf_to_gguf.py
```

Deprecated aliases: `learning.training_enabled` / `learning.training_schedule` still work and fold into `[learning.training]` (`enabled` / `schedule`).

Training hyperparameters (LoRA rank, epochs, learning rate, base model) come from the existing `[learning.intelligence.sft]` section — see `SFTConfig` in `src/nova_ai/core/config.py`.

## Deployment targets

| Target | What it produces | Notes |
|--------|-----------------|-------|
| `adapter` | The PEFT adapter directory (default) | Always available; needed for the other two |
| `ollama` | `ollama create nova-tuned-<model>` | Modelfile (`FROM <base>` + `ADAPTER <dir>`) written into the adapter dir; shows up in `ollama list` and NOVA's model discovery |
| `llamacpp` | Merged model (+ optional GGUF) | `merge_and_unload()` into `~/.nova_ai/learning/training/merged/`; GGUF conversion requires `llamacpp_gguf_script` pointing at llama.cpp's `convert_hf_to_gguf.py` |

Targets are independent — one failing (e.g. no Ollama installed) never aborts the others.

## Triggers

| Trigger | How | Gate |
|---------|-----|------|
| Manual | `nova train run [--foreground]` | benchmark gate + pending review |
| Scheduled | `schedule = "0 3 * * *"` in `[learning.training]`; the daemon's scheduler dispatches a `kind="train"` task | benchmark gate; runs carry the gate even on auto |
| Auto | `auto_trigger = true` **and** `learning.auto_update = true`; fires when ≥ `min_pairs` new qualifying traces accrue since the last successful run | benchmark gate + pending review |

Background runs spawn a detached process (Windows-safe) writing to `~/.nova_ai/learning/training/last_run.log`; progress is in the run store (`nova train status`).

## Artifacts

| Path | Contents |
|------|----------|
| `~/.nova_ai/learning/training/adapters/<run>/` | Trained adapter + `adapter_meta.json` |
| `~/.nova_ai/learning/training/active.json` | Pointer to the active adapter |
| `~/.nova_ai/learning/training/runs.db` | Run history (`nova train list`) |
| `~/.nova_ai/learning/training/merged/<model>/` | Merged models (llamacpp target) |

## Where it plugs into spec-search

The `LoraFinetuneApplier` (`src/nova_ai/learning/spec_search/execute/appliers/lora.py`) implements the `lora_finetune` edit op, so the teacher can propose weight updates when diagnosis shows a skill gap that prompt edits can't fix. In TIERED/MANUAL autonomy it routes to review like any MANUAL-tier edit; with `auto_apply` it trains and activates the adapter directly. The old `LoraStubApplier` remains as the torch-free fallback that refuses the op with a clear message.

## Requirements

Training requires `torch`, `transformers`, and `peft` (install with `pip install torch transformers peft`). Everything else — mining, export, run history, deployment plumbing — works without them; the CLI reports a clear install hint if torch is missing at train time.

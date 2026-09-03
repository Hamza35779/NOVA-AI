---
title: Fleet Oracle
description: "Best 8B model for code on a 4090?" — answered by the fleet, not the vendor
---

# Fleet Oracle: ask the fleet, not the vendor

Vendor benchmarks are marketing. Community leaderboards are outliers. What actually answers "*will this model be fast on my machine?*" is real people running real workloads on real hardware — which is exactly what the Fleet Oracle pools.

NOVA machines can (opt-in) publish a tiny anonymized report of their hardware and per-model performance averages to a shared git repo. Anyone can then query that dataset locally: `nova oracle ask "best 8B model for code on a 4090?"`.

**Everything is local by default. Sharing is OFF until you flip it on.**

## The loop

```
   ┌────────────────┐    ┌──────────────────┐    ┌───────────────────┐
   │ Your telemetry │───▶│ build_report     │───▶│ git push          │
   │ (stays local)  │    │ fixed field list │    │ (only if opt-in)  │
   └────────────────┘    └──────────────────┘    └─────────┬─────────┘
                                                           ▼
   ┌──────────────┐    ┌──────────────────┐    ┌───────────────────┐
   │ nova oracle  │◀───│ query_fleet      │◀───│ shared dataset    │
   │ ask "..."    │    │ buckets + winner │    │ (git repo)        │
   └──────────────┘    └──────────────────┘    └───────────────────┘
```

## Privacy model: a fixed field list, nothing else

The report is not a redaction of something bigger — it is **constructed from a fixed field list**. There is no code path that could leak anything else:

| Field | Value |
|-------|-------|
| `hardware.platform` | `windows` / `linux` / `darwin` |
| `hardware.cpu_count` | core count |
| `hardware.ram_gb` | total RAM (rounded) |
| `hardware.gpu.{vendor,name,vram_gb}` | GPU shape only — no compute capability, no count |
| `models[].model_id` | e.g. `qwen3.5:9b` |
| `models[].engine` | e.g. `ollama` |
| `models[].call_count` | calls in the window |
| `models[].avg_latency_s`, `avg_ttft_s` | latency averages |
| `models[].avg_throughput_tok_per_sec` | throughput |
| `models[].avg_tokens_per_joule` | energy efficiency |
| `models[].total_tokens` | volume in the window |
| `report_id` | `hash_id(platform|cpu|ram|gpu)` — a stable pseudonym for dedupe |

What never leaves the machine: **no prompts, no responses, no file paths, no user IDs, no timestamps** (only the aggregation window length), no IP addresses. Models with fewer calls than `min_calls_per_model` are dropped (k-anonymity) so a personal model can't be fingerprinted.

```toml
# ~/.nova_ai/config.toml
[learning.fleet]
share_reports = false          # opt-in — this is the switch
dataset_repo = ""              # git URL of the shared dataset repo
min_calls_per_model = 5        # k-anonymity threshold
since_days = 30                # aggregation window
```

## Commands

```bash
# Build and preview the report — see exactly what sharing would publish
nova oracle export
nova oracle export -o report.json     # write it to a file instead

# Publish it (refuses unless share_reports = true)
nova oracle push

# Ask the fleet — answered locally from the dataset, no LLM involved
nova oracle ask "best 8B model for code on a 4090?"
nova oracle ask "most energy efficient model on 16 gb?"

# Config + dataset state
nova oracle status
```

## How questions are answered

Deliberately simple and explainable — no LLM in the loop:

1. **Intent** — keyword buckets pick the ranking metric: *fast/latency* → avg latency (lower wins), *throughput/tok/s* → throughput, *energy/efficient/watt* → tokens per joule, *code* → throughput as the quality proxy.
2. **Hardware bucket** — the question's VRAM hint (`"24 gb"` or a known card like `4090`) selects a VRAM bucket (`<=8GB`, `9-16GB`, `17-24GB`, `25-48GB`, `>48GB`).
3. **Winner** — within the bucket, per-model stats are call-weighted across machines; the metric winner is the headline. The full table is printed underneath.

Every answer is inspectable: the table shows machines and call counts behind it, so you can see how much data the answer rests on.

## Running a fleet dataset

The dataset is an ordinary git repo of `reports/<report_id>.json` files — no server, no API. To host one: create a repo, point `dataset_repo` at it for everyone in the group, and merge push requests if you want curation. Any git remote works (GitHub, Gitea, a bare repo on a NAS).

## Artifacts

| Path | Contents |
|------|----------|
| `~/.nova_ai/fleet/cache/` | Local clone of the dataset repo (read + push staging) |

## See also

- [Telemetry](../user-guide/telemetry.md) — the local data the reports are built from.
- [Model Proving Ground](proving-ground.md) — proving candidate models on *your* traces before adopting them.
- [Self-Training](self-training.md) — the other consumer of your local performance data.

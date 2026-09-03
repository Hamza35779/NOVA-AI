---
title: Skill Foundry
description: Show NOVA a task twice — it forges the skill, proves it on your past runs, and installs it only when you say so
---

# Skill Foundry: your repeated workflows become skills

Watch any operator long enough and you'll see it: the same three tool calls, in the same order, on slightly different inputs — search, then summarize, then file it away. The Skill Foundry notices. It mines your traces for **repeated multi-step tool sequences**, asks your local model to write a skill manifest chaining those tools, verifies the candidate against your own past runs in a three-gate gauntlet, and — only when you approve — installs it as a first-class skill.

**The pitch: show NOVA a task three times — it writes the skill and proves it before you ever run it.**

## The forge

```
   ┌──────────────┐    ┌──────────────────┐    ┌───────────────────┐
   │ Your traces  │───▶│ PatternMiner     │───▶│ SkillSynthesizer  │
   │ (TOOL_CALL   │    │ same sequence    │    │ local LLM writes  │
   │  steps)      │    │ ≥ 3x, feedback   │    │ skill.toml against│
   └──────────────┘    │ ≥ 0.7            │    │ the real catalog  │
                       └──────────────────┘    └─────────┬─────────┘
                                                         ▼
   ┌──────────────┐    ┌──────────────────┐    ┌───────────────────┐
   │ Installed    │◀───│ nova forge adopt │◀───│ Gauntlet          │
   │ skill lives  │    │ (the only        │    │ static → replay → │
   │ in generated/│    │  mutation)       │    │ judge             │
   └──────────────┘    └──────────────────┘    └───────────────────┘
```

1. **Mine** — `PatternMiner` extracts ordered tool sequences from `TOOL_CALL` trace steps. Traces are grouped by exact sequence; a pattern qualifies with `min_pattern_count` repetitions and average feedback at least `min_feedback`. Single-tool traces are ignored — one-call "skills" are just tools.
2. **Synthesize** — `SkillSynthesizer` prompts the local model with the observed sequence, the **real tool catalog** (names, descriptions, parameter schemas from the `ToolRegistry`), and worked examples with the actual recorded arguments. The output must parse through the stock `load_skill` and its step tools must match the observed order — anything else gets one retry, then rejection.
3. **Gauntlet** — three sequential gates, each reported by name:
   - **static** — name/description sanity, capability validation, no dangerous capabilities, and every step targets a tool that actually exists.
   - **replay** — each mined example runs through `SkillExecutor` against your real tools; code/shell-shaped steps are forced through the **subprocess sandbox** with `sandbox_timeout`.
   - **judge** — the LLM compares replay output with the trace's known-good result (first line YES/NO, same convention as the proving ground).
4. **Adopt** — candidates wait in `passed` state. `nova forge adopt` writes `~/.nova_ai/skills/generated/<name>/skill.toml` with a provenance block (run id, pattern count, gauntlet report). `nova forge revert <name>` deletes it. Discovery is automatic — adopted skills are ordinary skills.

## Quickstart

```toml
# ~/.nova_ai/config.toml
[learning.skillforge]
enabled = true
```

```bash
# Mine + synthesize + gauntlet (background by default, --foreground to watch)
nova forge run --foreground

# Inspect candidates and their gauntlet reports
nova forge status        # latest run, gate-by-gate
nova forge list          # all candidates

# Your call — install it or reject it
nova forge adopt forge_20260903_ab12cd34
nova forge reject forge_20260903_ef56ab78

# Undo any time
nova forge revert search-and-summarize
```

## Running it on a schedule

```bash
nova scheduler create "forge skills" --cron "0 5 * * *" \
  --metadata '{"kind": "skillforge"}'
```

The scheduled run behaves exactly like a foreground run and logs `[skillforge] run forge_…: completed (patterns=N, passed=N)` to the task's run log.

## Safety model

Generated skills are **step pipelines over audited tools** — there is no arbitrary shell, no new code paths, no tool the registry doesn't already know:

1. **No invention** — every step must name a registered tool; the static gate rejects unknown tools before anything executes.
2. **No dangerous capabilities** — a candidate requiring `shell:execute`, `network:listen`, or `filesystem:write` is refused at the static gate.
3. **Sandboxed replay** — code/shell-shaped steps run through `run_sandboxed` (clean env, process-tree kill, output truncation, timeout).
4. **Manual by default** — `auto_adopt = false`: a passed candidate sits in the store until `nova forge adopt`. `auto_adopt = true` exists for hands-off setups, but the gauntlet still runs first.
5. **Reversible** — `nova forge revert <name>` deletes the skill directory instantly. Adopted skills are plain files in `generated/`.

## Config reference

```toml
[learning.skillforge]
enabled = false              # master switch
auto_trigger = false         # forge automatically when patterns accrue
auto_adopt = false           # install passing skills without `nova forge adopt`
min_pattern_count = 3        # same tool-sequence must appear this often
min_feedback = 0.7           # average trace feedback required to mine a pattern
max_candidates_per_run = 3   # cap on skills synthesized per run
sandbox_timeout = 30.0       # seconds per sandboxed replay step
judge_model = ""             # "" uses intelligence.default_model
```

## Artifacts

| Path | Contents |
|------|----------|
| `~/.nova_ai/learning/skillforge/runs.db` | Run + candidate history (`nova forge list`) |
| `~/.nova_ai/learning/skillforge/last_run.log` | Background run output |
| `~/.nova_ai/skills/generated/<name>/skill.toml` | Adopted skills (auto-discovered) |

## CLI reference

| Command | What it does |
|---------|-------------|
| `nova forge run [--foreground]` | Mine patterns and forge candidates |
| `nova forge status` | Latest run + gate-by-gate gauntlet report |
| `nova forge list [-n N]` | Candidate history |
| `nova forge adopt RUN_ID` | Install a passed candidate |
| `nova forge reject RUN_ID` | Mark a candidate rejected |
| `nova forge revert SKILL_NAME` | Uninstall an adopted skill |

## See also

- [Model Proving Ground](proving-ground.md) — the same gauntlet discipline, applied to models instead of skills.
- [Memory Consolidation](memory-consolidation.md) — the other consumer of your trace history.
- [Fleet Oracle](fleet-oracle.md) — pool anonymized performance data so others can learn from your hardware, too.

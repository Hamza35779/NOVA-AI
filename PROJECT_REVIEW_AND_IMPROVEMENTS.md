# NOVA AI — Proofreading, Code Review & Improvement Plan

**Date:** 2026-09-12
**Scope:** `README.md`, `SETUP_AND_USAGE_GUIDE.md`, `pyproject.toml`, `src/nova_ai/` (~762 files, ~157k LOC), `frontend/`, `desktop/`, `browser-extension/`, `tests/` (~687 files), `configs/`, `scripts/`, `deploy/`, `docs/`, `.github/`, `CHANGELOG.md`, `CONTRIBUTING.md`, `LICENSE`, `mkdocs.yml`, `opencode.json`, `.gitignore`
**Method:** static exploration + manual sampling + cross-check of docs vs code vs configs. No live `pytest` / `npm test` run — commands are provided below to reproduce.
**Related prior work:** `FORENSIC-AUDIT-2026-09-12.md` (untracked, 6.9/10), `REVIEW.md` (43 lines, generic checklist)

---

## 1. Executive Summary

NOVA AI is an ambitious, genuinely impressive local-first personal-AI stack: CLI (`nova` 50+ commands) + SDK + FastAPI server + React+Vite+Tauri frontend + Rust workspace (17 crates) + 50+ tools + connectors + channels + evals/learning loop. Documentation is extensive, Docker/systemd/Windows installers exist, CI has 14 workflows.

It reads as **research-platform scale with production-packaging ambition**, but quality gates have not kept up with scale:

1. **Docs rot faster than code:** `cd NOVA AI` (space path, 24+ hits), version drift `1.2.4 vs 1.2.5`, agent count `eight vs 9`, Docker command missing required env, `desktop/` setup path that cannot work.
2. **Tests exist but don't protect:** Python coverage gate 60%, marker lanes diverge (`pyproject` vs `ci.yml` vs `CONTRIBUTING`), Windows CI only 2 files, frontend has 1 test file and CI never runs `vitest`, extension has 0 tests.
3. **Lint/type/security are advisory:** `E501` ignored repo-wide, `mypy` non-gating with `check_untyped_defs=false`, no `S` (bandit) despite `shell=True` tools, no `gitleaks`/`detect-private-key`, frontend/extension have no eslint/prettier.
4. **Supply-chain + secrets hygiene need hardening:** all Python deps `>=` only, no `uv.lock` committed despite comment saying it is tracked, no `package-lock.json`, `npm audit 36 vulns` reported, `~/.nova_ai/credentials.toml` plaintext + `chmod 0600` no-op on Windows, local `opencode.json` contains a hardcoded API key (see §7 — rotate + move to env).
5. **Architecture debt is concentrated:** god-files (`cli/ask.py:917`, `server/agent_manager_routes.py:2184`), misleading `*/_stubs.py` naming (they are ABCs), scattered `NotImplementedError`/`TODO`, dual Tauri roots (`frontend/src-tauri` real vs `desktop/` stub), dual Vite outDirs undocumented.

**Verdict:** ship-worthy vision, solid bones. Fix P0 docs + test-gate + secret-hygiene items first (§9.1) — ~2-3 days — then P1 hardening. Full checklist in §9.

> Score (opinionated, 10 = prod-ready): **Architecture 8 / Features 9 / Docs 6 / Tests 5 / Security 6 / DX 6.5 / Overall ~6.8**

---

## 2. Proofreading — Language, Typos, Consistency

### 2.1 Critical / breaking (fix now)

| # | Location | Issue | Fix |
|---|----------|-------|-----|
| PR-1 | `README.md:221`, `CONTRIBUTING.md:87`, `docs/getting-started/installation.md:44,64,110,137,155,199`, `docs/downloads.md:20,81,99,119,166,214`, `docs/index.md:47,63`, `user-guide/*.md`, `deployment/*.md` — ~24 hits | `git clone .../NOVA-AI.git` creates dir `NOVA-AI`, but next line says `cd NOVA AI` (space, unquoted). **Fails on Linux/macOS.** | Global replace: `cd NOVA AI` → `cd NOVA-AI`. Verify with: `rg -n "cd NOVA AI" docs README.md CONTRIBUTING.md` must return 0. |
| PR-2 | `README.md:40`, `SETUP_AND_USAGE_GUIDE.md:54` vs `frontend/package.json:4`, `frontend/src-tauri/tauri.conf.json:4` | Installer cited as `NOVA-AI-Setup-1.2.4.exe`, code says `1.2.5` | Single-source version: derive installer name in docs from `frontend/package.json` or add `scripts/check-versions.sh` (fixture §9.4). |
| PR-3 | `README.md:119` | Says `eight built-in agents`, table lists 9 (`morning_digest, deep_research, monitor_operative, orchestrator, native_react, self_healing_react, operative, native_openhands, simple`) | Change to `nine` or remove count entirely — counts rot. Prefer: `Built-in agents include:` with no number. |
| PR-4 | `README.md:43` vs `deploy/docker/docker-compose.yml:14` | `docker compose -f deploy/docker/docker-compose.yml up` omits required `NOVA_AI_API_KEY` (`:?` hard-fail) + `.env.example` not mentioned | Fix snippet to: `cp deploy/docker/.env.example .env  # fill NOVA_AI_API_KEY` + `docker compose -f deploy/docker/docker-compose.yml --env-file .env up` |
| PR-5 | `docs/downloads.md:81`, `docs/getting-started/installation.md:137` | `cd NOVA AI/desktop; npm install; npm run tauri build` — `desktop/` has only `src-tauri/src/overlay.html`, no `package.json`, no `tauri.conf.json`, no `Cargo.toml`. Real project is `frontend/src-tauri/` | Rewrite to `cd frontend && npm install && npm run tauri build`, output `frontend/src-tauri/target/release/bundle/`. Add `desktop/README.md` stub pointer or delete `desktop/` to avoid dual-root confusion. |
| PR-6 | `browser-extension/manifest.json:7` vs `configs/nova_ai/config.toml:114` | `host_permissions: ["http://localhost:8000/*"]` misses default `127.0.0.1:8000` + `ws://` | `"host_permissions": ["http://127.0.0.1:8000/*", "http://localhost:8000/*", "ws://127.0.0.1:8000/*", "ws://localhost:8000/*"]` |
| PR-7 | `SETUP_AND_USAGE_GUIDE.md:172` | Hardcodes Windows `C:\Users\...\.nova_ai\models\` for all OS | Replace with OS table: Windows `%USERPROFILE%\.nova_ai\models`, Linux/macOS `~/.nova_ai/models` |
| PR-8 | `SETUP_AND_USAGE_GUIDE.md:228,274` vs `README.md` Complete Reference | `clip`, `digest` commands documented in setup guide but omitted from README command reference (will rot further — 60+ command dump) | Generate CLI reference: `nova --help` + per-command `--help` into `docs/cli/` via `scripts/gen-cli-docs.py` in CI, link from README instead of hand-maintained list. |

### 2.2 Naming / UX consistency

* `cli/__init__.py:117-118`: `channel` (singular) vs `channels` (plural) both registered. Same for `agent_cmd.py → agents`, `tool_cmd.py vs tools/`, `memory vs memory-wiki` (`memory_wiki_cmd.py:71`), `dev_watch_cmd.py → dev-watch`, `research` alias + `deep-research-setup` double-register `:166-167`. Pick singular-or-plural convention, keep the other as hidden alias with deprecation warning.
* `src/nova_ai/*/_stubs.py` are actually abstract base classes, not stubs. Rename to `_base.py` / `_abc.py` or add header comment `# NB: "stubs" = ABCs, not dead code`. Currently reads as dead code to newcomers + auditors.
* Empty extra `mining-pearl-cpu` in `pyproject.toml:159` — delete or fill.
* `configs/nova_ai/config.toml` is eval-specific (`GLM-4.7-Flash, 8x A100, vLLM, temperature=0.0`), not a generic default. Rename to `configs/nova_ai/examples/eval-a100.toml` and ship minimal `config.toml` (ollama/qwen local defaults matching quickstart).
* `quickstart.sh:139` uses `qwen3:0.6b` vs docs `qwen2.5:7b` / `qwen3:8b`; `quickstart.sh:85` says `Node>=18` vs `CONTRIBUTING.md:82` `Node 22+`. Align to `Node 22+` + one starter model, or document why they differ.

### 2.3 Style nits

* README badges: only `python>=3.10` + `license`. Add CI / coverage / release / docs badges — cheap trust signal.
* `CHANGELOG.md`: `Unreleased` section is huge/undated; notes in-place replacement of `Setup-1.2.4.exe` asset — don't mutate released assets, cut `1.2.5`.
* No root `.editorconfig`. Add (fixture §9.4).
* `mkdocs.yml:137-140` Algolia keys empty — either fill via env or remove block to avoid confusion.
* Junk artifact committed: `MagicMock/load_config().security.audit_log_path/` — looks like accidental mock output. `git rm -r MagicMock/` if not intentional.
* `frontend/tsconfig.json:25` excludes `src/components/Desktop` silently — either delete stale fork or document why excluded.

---

## 3. Architecture Review — What's Good

* **Clear flow:** `CLI/SDK → core/config+registry+EventBus → engine/router → agents → tools → memory/connectors/channels/mcp → server/daemon/scheduler/traces/bench/evals/learning`. Easy to trace from `cli/serve.py:625 → server/app.py:162 create_app()` and `sdk.py:196 _ensure_engine() → engine/_discovery.py:get_engine()`.
* **Engine abstraction done right:** `engine/{ollama,gguf,cloud,litellm,router,multi,task_planner}.py` + `_discovery.py` lets local-first fallback actually work.
* **Server is OpenAI-compatible** with 30+ routers + SPA fallback + `AuthMiddleware` + `ChannelBridge` — good interop choice.
* **Evals treat cost as first-class** (energy/FLOPs/latency/$) — differentiating vs generic agent frameworks.
* **Packaging breadth:** `nova-ai.spec`, `nova-ai-windows-x64.spec`, `start.bat/sh`, `install.bat`, `deploy/{docker,windows,systemd,launchd}`, Tauri bundles. Rare for a research-grade repo.
* **Rust mirror** (17 crates + `_rust_bridge.py`) is forward-looking, though bridge coverage should be documented per-crate.

---

## 4. Code Quality

| Area | Finding | Recommendation |
|------|---------|----------------|
| God-files | `cli/ask.py:917`, `cli/mine_cmd.py:899`, `cli/agent_cmd.py:776`, `server/agent_manager_routes.py:2184`, `server/routes.py:948`, `server/api_routes.py:913` | Split by resource/action; enforce `ruff` + new `C901` (complexity) or `PLR0915` (too-many-statements) + soft file-length check in CI (e.g. fail >800 lines with `wc -l` allowlist). |
| `E501` ignored repo-wide (`pyproject.toml:250-260`) | Hides formatting drift, hurts review | Re-enable `E501` with `line-length=100` (match `ruff format`) or at least enforce on `src/nova_ai/{core,engine,server,security}/`. |
| `mypy` advisory-only, `check_untyped_defs=false`, `no_strict_optional=true`, no `py.typed` | Types don't protect | Flip to `check_untyped_defs=true`, add `py.typed`, gate `mypy src/nova_ai/core src/nova_ai/security src/nova_ai/engine` first, expand incrementally. |
| `ruff` `v0.9.0` in pre-commit vs `ruff>=0.4` dev dep | Stale hook (2026 is 0.12+) | Pin `rev: v0.12.x`, add hooks: `trailing-whitespace`, `end-of-file-fixer`, `check-yaml`, `check-toml`, `detect-private-key`, `gitleaks` (or `trufflehog`). Add `S` (flake8-bandit) ruleset given `shell_exec`, `http_request`, `code_interpreter` tools. |
| `NotImplementedError` / `TODO` scattered | `learning/spec_search/execute/appliers/lora_stub.py:35`, `mining/_stubs.py:52`, `mining/vllm_pearl.py:66`, `agents/hybrid/skillorchestra/stage_router.py:313`, `evals/backends/external/_subprocess_runner.py:167`; `TODO agents/hybrid/_energy.py:27`, `runner.py:662`, `mining/_constants.py:15` | Track as GitHub issues with `todo-breakdown` label; add `scripts/check-todos.sh` that fails if new `TODO` without issue link `TODO(#123)`. |
| `channel-twitter` extra = bare `httpx` | No SDK, likely half-wired | Either vendor minimal client with tests or drop extra + document limitation. |
| Frontend dual output | `frontend/vite.config.ts:37 outDir: ../src/nova_ai/server/static` vs `tauri.conf.json:7 frontendDist: ../dist` + `build:tauri --outDir dist` | Document both targets in `frontend/README.md` (add — missing) + assert in CI that `server/static/index.html` is fresh (or build it in `ci.yml`). |
| `httpx` + `httpx2` confusion, `pynvml` vs `nvidia-ml-py` dual, `datasets/nvidia-ml-py/posthog` in core | Bloat + confusion (also noted in forensic audit) | Move `datasets` → `evals` extra, `nvidia-ml-py` → `gpu` extra, `posthog` → `telemetry` extra with no-op fallback. Dedupe nvml/httpx. Measure `litellm 1.100.0` 9s import tax — lazy-import in `engine/cloud.py`. |

---

## 5. Tests

### 5.1 Python (`tests/`, 40+ suites, good `conftest.py`)

* Gate too low: `ci.yml:72 --cov-fail-under=60`. Raise to 70 now, 80 for `core/security/engine/memory` via `--cov-fail-under` + per-package `--cov=src/nova_ai/{core,security}` overlay.
* Marker lanes diverge — canonicalize in one place:
  * `pyproject.toml:230`: `-m "not live and not cloud and not hub"`
  * `ci.yml:68`: `+ " and not slow"`
  * `CONTRIBUTING.md:210`: says `slow` included
  * `test-windows:125`: `-m "not live and not cloud"` (includes `hub/slow`)
  * **Fix:** define `markers` in `pyproject`, make `ci.yml` + `CONTRIBUTING` + `test-windows` all use `not live and not cloud and not hub and not slow` for default lane, separate `slow`/`hub` nightly job.
* Windows CI runs 2 files only — expand to full default lane on `windows-latest` or document why subset.
* Only `actions/upload-artifact` for `coverage.xml` — add Codecov (or `smoke` + badge) so coverage is visible.
* Missing policy doc: `docs/testing/` has only `agent-qa-runbook.md`. Add `docs/testing/{pytest,coverage,frontend-testing}.md` (1 page each is enough).

### 5.2 Frontend (`frontend/`)

* **1 test total** (`src/lib/api.auth.test.ts`, 85 lines) for whole React19 app. No `vitest.config.*`, no `test:` block in `vite.config.ts`. CI (`frontend.yml:35-37`) runs `npm ci + tsc --noEmit + build` — never `vitest run` despite `package.json:15 "test": "vitest run"`.
* Fixture — add `frontend/vitest.config.ts`:
```ts
import { defineConfig } from 'vitest/config';
export default defineConfig({ test: { environment: 'jsdom', coverage: { provider: 'v8', reporter: ['text','lcov'], lines: 60 } } });
```
  and in `frontend.yml`: `npm run test -- --coverage` + upload. Start with pure-logic coverage (`lib/store.ts`, `lib/sse.ts`, `hooks/useAgentEvents.ts`), then component smoke tests.
* Add `eslint.config.js` + `.prettierrc` (currently none — verified). Minimal:
```js
// eslint.config.js — react + ts + hooks + a11y
```
  gate `npm run lint` in CI. Remove or restore `src/components/Desktop` (currently excluded from `tsconfig`).

### 5.3 Browser extension + scripts

* Extension: no tests/lint/build (`package.json` 6 lines, no scripts, no CI). Add `web-ext lint` + one Playwright smoke (popup → `GET /api/health` mocked) — 30 lines catches manifest regressions like §2.1 PR-6.
* `scripts/`: solid `quickstart.sh` + `install/` but hosted one-liners depend on gh-pages build with no local root copy. Add `scripts/README.md` + `shellcheck` to CI (only `bash-tests.yml` today).

---

## 6. Configs / Deploy / Docs Site

* `configs/`: add `configs/README.md` + JSON-schema (`configs/schema.json`) + `tests/test_config_schema.py` so typos fail fast. Rename eval-specific base config per §2.2.
* `deploy/`: add `deploy/README.md` matrix (Docker / Windows / systemd / launchd / PostHog) + fix README Docker snippet per PR-4. `deploy/systemd/` only has service file — add timer/logrotate example or link.
* `docs/`: fix `cd` bug globally (§2.1), then add `docs/cli/` auto-generated reference (§2.1 PR-8) to stop 60-command dump rotting. Fill or drop Algolia block in `mkdocs.yml`.
* `CONTRIBUTING.md` (270 lines, good) duplicates `docs/development/contributing.md` — keep one canonical, other links to it. Fix `cd NOVA AI` + Node version (`22+`) + marker-lane canonical form.

---

## 7. Security & Secrets — Please Read Carefully

**No live secrets found in git history** (`git ls-files` shows only `deploy/docker/.env.example`; `.gitignore` covers `.env`, `.venv/`, `opencode.json`, `*.sqlite`, `/traces/`). Placeholders only (`sk-ant-...`, `AIza...`, `xoxb-...`). Parameterized SQL, HMAC webhooks, loopback auth gate per forensic audit — agreed.

**Still fix (P0/P1):**

1. **`opencode.json` contains a hardcoded API key** (`provider.b.ai.options.apiKey: "sk-9f...49"`, full value in local file). It is git-ignored (good) but:
   * rotate that key now (it lives in plaintext on disk + may have been pasted into logs/screenshots),
   * move to env: `"apiKey": "{env:B_AI_API_KEY}"` (same pattern already used for `OPENROUTER_API_KEY` in the same file),
   * add `docs/security/secrets.md`: never commit keys, use `B_AI_API_KEY` / `OPENROUTER_API_KEY` / `~/.nova_ai/credentials.toml` (0600) + OS keyring roadmap.
   ```jsonc
   // opencode.json (fixed)
   { "provider": { "b.ai": { "options": { "apiKey": "{env:B_AI_API_KEY}" } } } }
   // powershell
   // $env:B_AI_API_KEY="..."  # or [Environment]::SetEnvironmentVariable(...,[EnvironmentVariableTarget]::User)
   ```
2. **Plaintext `~/.nova_ai/credentials.toml` + `chmod 0600` no-op on Windows** (`core/credentials.py:1-5`). Roadmap: `keyring` lib (Windows Credential Manager / macOS Keychain / Secret Service) with file fallback + warning. At minimum document risk + restrict ACL via `icacls` on Windows.
3. **Exec-surface hardening (open audit items, re-verified):**
   * `tools/shell_exec.py:152 shell=True` + `env_passthrough (:55,111-114)` — default-deny, require explicit `allow_shell + capability_policy`, log full argv.
   * `tools/http_request.py:113 os.path.expandvars` on LLM-controlled headers — remove expansion or allowlist vars.
   * `tools/code_interpreter.py` blocklist sandbox — move toward allowlist + `wasmtime`/`docker` backend (dep already present) for untrusted code.
   * `InjectionScanner` has 0 prod call sites; `capability_policy=None` by default; `CredentialStripper` only covers CLI logs, not `traces/store.py:125-172`. Wire all three into engine/tool path with tests.
4. **`.gitignore` gaps:** add `*.pem`, `*.key`, `*credentials*.toml`, `secrets*.json`, `*.p12`, `.env.*` already covered — extend. Note: comment says `uv.lock is intentionally tracked` but no `uv.lock` exists — either commit it (`uv lock`) for reproducible installs or fix comment.
5. **Supply-chain:** pin with `uv.lock` + upper bounds or at least `pip-compile`; add `package-lock.json` (`npm i --package-lock-only`); run `npm audit fix` (36 vulns: `react-router ^7.13.1`, `vite ^6`, `lodash/js-yaml/nanoid` per audit); add Dependabot + `pip-audit` + `npm audit` + CodeQL to CI.

---

## 8. Enhancement Ideas (Beyond Fixes)

**Highest leverage, smallest cost:**

1. **`nova doctor --fix` as onboarding gate** — already have `doctor`; make it check Python/Node/Ollama/model/config/port/keyring perms and auto-fix with `--fix`. Every setup doc links to it; CI runs `nova doctor` on fresh container.
2. **Auto-generated CLI + config docs** (`scripts/gen-cli-docs.py` + schema) — kills whole class of rot (PR-8, PR-2, PR-7).
3. **Trace-to-learn demo closed loop** — the thesis; ship one `examples/closed-loop/` (chat → trace → `nova eval` cost/quality → `learning/` SFT/GEPA → re-eval chart in dashboard). Best marketing + dogfoods `evals/`, `learning/`, `telemetry/`.
4. **Starter presets that just work:** `configs/examples/{chat-simple,code-assistant,deep-research,morning-digest}.toml` + `nova init --preset <name>` + `nova router status` smoke. E2E test per preset.
5. **Dashboard Build Diagnostics + digest audio** (just shipped per CHANGELOG) — add screenshots to README/docs; untested UI dies quietly.
6. **Rust bridge matrix:** `docs/architecture/rust-bridge.md` table — crate × capability × Python fallback × bench. Prevents "is Rust used?" confusion.
7. **Connector/channel smoke harness:** `nova connect --check-all` + `nova channels --check-all` with redacted diagnostics bundle (`nova doctor --bundle` → zip without secrets via `CredentialStripper`). Cuts support load.
8. **Eval cost leaderboard:** publish `docs/evals/leaderboard.md` generated by CI nightly (accuracy + p50 latency + $/1k + Wh) — embodies "energy as first-class" claim.

**Bigger bets (roadmap):** Tauri auto-updater + signed releases (replaces hand-downloaded EXE), mobile companion via same OpenAI-compat API, MCP registry (`nova registry`), multi-user auth beyond loopback gate, WASM tool sandbox default.

---

## 9. Prioritized Action Plan + Fixtures

### 9.1 P0 — Do this week (breaks users / leaks trust)

- [ ] **P0-1** Global `cd NOVA AI` → `cd NOVA-AI` + `rg` gate in CI.
```powershell
# verify
rg -n "cd NOVA AI" README.md CONTRIBUTING.md docs SETUP_AND_USAGE_GUIDE.md
# fix (powershell)
Get-ChildItem -Recurse -Include *.md | ForEach-Object { (Get-Content $_.FullName) -replace 'cd NOVA AI','cd NOVA-AI' | Set-Content $_.FullName }
```
- [ ] **P0-2** Fix Docker snippet + `desktop/` path + extension `host_permissions` + `C:\...` OS table (§2.1 PR-4–PR-7).
- [ ] **P0-3** Rotate `opencode.json` key → `{env:B_AI_API_KEY}` (§7.1). Delete `MagicMock/` artifact or document it.
- [ ] **P0-4** Commit `uv.lock` (`uv lock`) + `frontend/package-lock.json`, run `npm audit fix`, re-pin Tauri action SHAs.
- [ ] **P0-5** Canonicalize pytest markers to `not live and not cloud and not hub and not slow` everywhere; fix `test-windows` subset.

### 9.2 P1 — Harden (next 2 weeks)

- [ ] **P1-1** Coverage 60→70 (+ per-package floor for `core/security/engine`), Codecov badge, frontend `vitest run --coverage` in CI, extension `web-ext lint` smoke.
- [ ] **P1-2** `ruff` hook `v0.12.x` + `S` rules + extra hooks (`end-of-file-fixer`, `check-yaml`, `detect-private-key`, `gitleaks`), `.editorconfig`, `eslint+prettier` frontend, `shellcheck` scripts.
- [ ] **P1-3** `mypy check_untyped_defs=true` for `core/security/engine` + `py.typed`; lazy-import `litellm`; move `datasets/nvidia-ml-py/posthog` to extras.
- [ ] **P1-4** `configs/README.md` + `schema.json` + `test_config_schema.py`; `scripts/README.md`; `deploy/README.md`; `frontend/README.md` (dual outDir); dedupe `CONTRIBUTING` vs `docs/development/contributing.md`.
- [ ] **P1-5** Wire `InjectionScanner` + `capability_policy` default-deny + `CredentialStripper` into `traces/store.py`; remove `expandvars` on LLM headers; document `credentials.toml` Windows ACL + keyring roadmap.
- [ ] **P1-6** Auto-generate `docs/cli/` from `--help` in CI; version-check script (fixture below).

### 9.3 P2 — Pay down debt (next month)

- [ ] Split god-files, enforce soft 800-line guard; rename `_stubs.py` → `_base.py`; file `NotImplementedError`/`TODO` as issues with `TODO(#id)` convention.
- [ ] Delete or restore `src/components/Desktop`; resolve dual Tauri roots (delete `desktop/` or make it thin pointer); document Vite dual outputs.
- [ ] Eval cost leaderboard nightly + closed-loop example + `nova doctor --fix` + `--check-all` harnesses (§8).

### 9.4 Drop-in fixtures

**`scripts/check-versions.sh` (CI gate for PR-2/PR-3):**
```bash
#!/usr/bin/env bash
set -euo pipefail
PKG=$(node -p "require('./frontend/package.json').version")
echo "frontend version: $PKG"
rg -n "NOVA-AI-Setup-[0-9.]+" README.md SETUP_AND_USAGE_GUIDE.md docs || true
# fail if old version string still present
if rg -q "1\\.2\\.4" README.md SETUP_AND_USAGE_GUIDE.md; then echo "stale 1.2.4 ref found"; exit 1; fi
# agent count guard — remove number instead of bumping forever:
if rg -qi "eight built-in agents" README.md; then echo "stale agent count"; exit 1; fi
```

**`.editorconfig`:**
```ini
root = true
[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 4
[*.{js,ts,tsx,json,yml,yaml}]
indent_size = 2
```

**`.pre-commit-config.yaml` (additions):**
```yaml
- repo: https://github.com/pre-commit/pre-commit-hooks
  rev: v5.0.0
  hooks:
    - id: trailing-whitespace
    - id: end-of-file-fixer
    - id: check-yaml
    - id: check-toml
    - id: detect-private-key
- repo: https://github.com/gitleaks/gitleaks
  rev: v8.24.0
  hooks:
    - id: gitleaks
```

**`frontend/package.json` scripts (add):**
```jsonc
{ "scripts": { "test": "vitest run", "test:coverage": "vitest run --coverage", "lint": "eslint .", "typecheck": "tsc --noEmit" } }
```

**Repro commands:**
```bash
# python default lane (canonical)
pytest -m "not live and not cloud and not hub and not slow" --cov=src/nova_ai --cov-fail-under=60 -q
# frontend
cd frontend && npm ci && npm run typecheck && npm run test -- --coverage && npm run build
# docs link/version guards
rg -n "cd NOVA AI" . ; rg -n "1\\.2\\.4" README.md SETUP_AND_USAGE_GUIDE.md
```

---

## 10. File-by-File Notes (sampling)

* `README.md:1-60` — strong hook + demo reel (`assets/nova_ai_demo_reel.webp` exists) + guide/docs/roadmap links. Fix badges, installer version, Docker line.
* `SETUP_AND_USAGE_GUIDE.md:368L` — most complete doc; needs OS path table + preset alignment + `clip`/`digest` cross-links.
* `pyproject.toml:294L` — good comments (PyPI name rationale, numpy cap #350); needs lockfile + extras slimming + marker canonicalization.
* `src/nova_ai/cli/*:66 files` — broadest surface; needs alias convention + god-file splits + generated docs.
* `src/nova_ai/server/agent_manager_routes.py:2184` — highest split priority.
* `src/nova_ai/{engine,memory,connectors,channels,tools}/` — well-factored domains; add `--check-all` harnesses + redacted bundles.
* `src/nova_ai/evals/:147 files` + `learning/:103 files` — moat; needs closed-loop example + leaderboard to be legible.
* `frontend/` — React19+Vite6+Tailwind4+Tauri2+Zustand modern; needs tests/lint/README/vitest config.
* `tests/` — breadth good; needs higher gate + lane fix + policy docs.
* `.github/workflows/` (14) — strong; add frontend tests, gitleaks, shellcheck, CodeQL, version guards.
* `opencode.json` — functional but leaks key pattern; switch to `{env:...}`.
* `.gitignore` — solid; add `*.pem/*.key/*credentials*.toml/secrets*.json`, resolve `uv.lock` comment vs reality.

---

## 11. What Was NOT Checked

Live test runs, GPU/vLLM paths, Ollama/GGUF inference quality, Windows EXE smoke, Tauri bundle signing, mobile, perf/energy benches. Re-run §9.4 repro commands + `nova doctor` after P0.

---

*Generated by Muse Spark (OpenCode) review — verify each path before committing; paths are absolute to `D:\\My Softwares\\Friday AI\\NOVA AI` in working notes, relative here. Suggested commit: `docs: add project review and improvement plan`.*

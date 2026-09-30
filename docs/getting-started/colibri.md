# Colibrì engine (frontier MoE models on consumer hardware)

[Colibrì](https://github.com/JustVugg/colibri) is a pure-C inference engine
that treats VRAM, RAM, and NVMe as **one memory hierarchy**: the dense part
of a model stays resident while routed experts stream from disk on demand.
That lets it run frontier MoE models (GLM-5.2 744B, Kimi K3 2.8T, DeepSeek
V4…) on machines with no GPU at all — the disk *is* the accelerator, and
speed depends on your drive, not your graphics card.

NOVA AI ships a first-class Colibrì engine
(`nova_ai.engine.openai_compat_engines.ColibriEngine`) that speaks to
`coli serve`'s OpenAI-compatible `/v1` API. This guide covers setup and an
end-to-end check on Windows.

## What each model needs

| Model | Weights on disk | RAM | GPU | Notes |
|---|---|---|---|---|
| **OLMoE 7B** | ~7 GB (int8) | ~8 GB | not needed | ✅ runs on 16 GB machines — recommended starter |
| **Qwen3.6 35B A3B** | ~20 GB (int4-gs64) | 24 GB | optional | best quality-per-GB of the small families |
| **DeepSeek V4 Flash** | ~167 GB | 16–32 GB | optional | CUDA tier speeds prefill up |
| **GLM-5.2 744B** | ~372 GB | 16 GB min | not needed | the reference model; slow but correct on HDD-tier storage |
| **Kimi K3 2.8T** | ~1.6 TB | 32 GB+ | not needed | streams native MXFP4, no conversion |

Full table in the
[Colibrì README](https://github.com/JustVugg/colibri#other-supported-models).

## 1. Install the engine

Download the prebuilt Windows archive (no compiler needed), verify it, and
unzip — e.g. to `D:\colibri`:

```powershell
mkdir D:\colibri; cd D:\colibri
curl.exe -sLO https://github.com/JustVugg/colibri/releases/download/v1.12.1/colibri-v1.12.1-windows-x86_64.zip
curl.exe -sLO https://github.com/JustVugg/colibri/releases/download/v1.12.1/SHA256SUMS.txt
sha256sum colibri-v1.12.1-windows-x86_64.zip   # must match SHA256SUMS.txt
Expand-Archive colibri-v1.12.1-windows-x86_64.zip -DestinationPath .
```

The zip contains one engine binary per model family (`olmoe.exe`,
`qwen36.exe`, `glm53.exe`, …) plus the `coli` launcher. The launcher reads
the model's `config.json` and picks the right binary itself.

## 2. Get a model container

Download a pre-converted container from Hugging Face. For a 16 GB machine,
OLMoE is the one that fits:

```powershell
# ~7 GB, 5 shards — curl -C - resumes if interrupted
mkdir D:\colibri\models\olmoe-i8; cd D:\colibri\models\olmoe-i8
$base = "https://huggingface.co/Krishal/OLMoE-1B-7B-0125-Instruct-Colibri/resolve/main"
foreach ($f in "config.json","generation_config.json","special_tokens_map.json",
               "tokenizer.json","tokenizer_config.json") {
  curl.exe -sLO "$base/$f"
}
foreach ($i in 0,1,2,3,4) {
  curl.exe -sL -C - -o "model-0000$i.safetensors" "$base/model-0000$i.safetensors"
}
```

Larger containers (GLM-5.2, Qwen3.6, …) are linked from the Colibrì README.

## 3. Serve it

```powershell
cd D:\colibri
python coli serve --model D:\colibri\models\olmoe-i8
# or double-click coli.cmd / run: coli.cmd serve --model ...
```

Verify the gateway is up:

```powershell
curl http://127.0.0.1:8000/v1/models
```

> **Port conflict:** NOVA AI's own server also defaults to 8000. Either run
> Colibrì elsewhere (`python coli serve --model ... --port 8010`, then set
> `[engine.colibri] host = "http://localhost:8010"` in
> `~/.nova_ai/config.toml`) or run NOVA AI on another port
> (`nova serve --port 8001`).

## 4. Point NOVA AI at it

Colibrì is auto-discovered: with `coli serve` running, `nova doctor` shows
`Engine: colibri — Reachable`. To make it the default engine:

```toml
# ~/.nova_ai/config.toml
[engine]
default = "colibri"

[engine.colibri]
host = "http://localhost:8000"   # or wherever coli serve listens
```

Environment variables work too: `COLIBRI_HOST` and `COLIBRI_API_KEY` (for
a gateway started with an API key).

## 5. End-to-end check

```powershell
nova doctor                 # Engine: colibri → Reachable
uv run nova ask "Say hello in Italian"
# routes through NOVA AI → Colibrì → OLMoE and streams back the reply
```

## Troubleshooting

- **`SNAP=` then exit** — you ran the engine `.exe` directly. The `.exe`
  files are family engines, not launchers; start via `python coli ...`
  or `coli.cmd`.
- **Slow first token** — expected: the first turn pages experts in from
  disk. Repeated runs warm the `.coli_usage` cache and get faster.
- **Out of RAM** — close memory-heavy apps; OLMoE needs ~8 GB resident.
  `python coli doctor --model <dir>` shows a read-only readiness plan.
- **Python missing** — the launcher needs Python 3 (the engine itself is
  pure C); `uv python install 3.13` works.

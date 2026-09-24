# macOS Install

```bash
curl -fsSL https://raw.githubusercontent.com/Hamza35779/NOVA-AI/main/scripts/install/install.sh | bash
```

Works on Intel and Apple Silicon. The installer auto-detects your CPU/GPU.

## Prerequisites

If you've never run `git` or `curl` on this Mac, macOS will prompt you to install the Xcode Command Line Tools the first time you run them. Accept the prompt; that gives you both.

If you'd rather pre-install:

```bash
xcode-select --install
```

## Walkthrough: Apple Silicon + Ollama

The standard path for a MacBook (M1–M4). Ollama is the easiest engine and uses the Mac's unified memory for GPU-accelerated inference.

### 1. Install Ollama

Download from [ollama.com](https://ollama.com) and drag to Applications, or:

```bash
brew install --cask ollama
```

Start it (the menu-bar app runs it automatically) and verify:

```bash
ollama --version
```

### 2. Install NOVA AI

```bash
curl -fsSL https://raw.githubusercontent.com/Hamza35779/NOVA-AI/main/scripts/install/install.sh | bash
```

### 3. Pull a model that fits your RAM

| Mac | Suggested model | Why |
|---|---|---|
| 8 GB unified memory | `qwen2.5:3b` | Fast, fits alongside your apps |
| 16 GB | `qwen3:8b` | The all-round default |
| 32 GB+ | `qwen2.5:14b` or larger | Noticably better reasoning |

```bash
ollama pull qwen3:8b
```

### 4. First run

```bash
nova init          # accepts detected hardware + Ollama
nova ask "Summarize this folder of notes" 
```

### 5. Optional: the morning digest preset

```bash
nova init --preset morning-digest-mac
nova digest --fresh   # spoken daily briefing
```

## Apple Silicon notes

- The installer picks `mlx` as the recommended engine via the standard hardware-detect path, but the foreground default is still Ollama for compatibility. Switch later with `nova init --force` and pick `mlx` if you've installed `mlx-lm`.
- Unified memory is reported as "VRAM" by the installer — that's intentional; on Apple Silicon, system RAM is what GPU-accelerated models can use.
- Close memory-hungry apps before running larger models: macOS compresses memory aggressively and inference slows down when swapping starts.

## Intel Mac notes

Still fully supported. Pick a smaller model (`qwen2.5:3b`) — Intel Macs have no unified memory, so inference runs CPU-side unless you have an AMD GPU.

## See also

- [Full installer reference](install.md)
- [Quick start](quickstart.md)

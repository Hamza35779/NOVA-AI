# Linux Install

```bash
curl -fsSL https://hamza35779.github.io/NOVA-AI/install.sh | bash
```

Tested on: Ubuntu 22.04 / 24.04, Fedora 40, Debian 12, Arch.

## Prerequisites

Most distros ship `git` and `curl`. If yours doesn't:

```bash
# Debian / Ubuntu
sudo apt install git curl

# Fedora / RHEL
sudo dnf install git curl

# Arch
sudo pacman -S git curl
```

## NVIDIA / AMD GPU

The installer auto-detects via `nvidia-smi` / `rocm-smi`. Datacenter cards (A100, H100, MI300+) get vLLM as the recommended engine; consumer cards get Ollama (NVIDIA) or Lemonade (AMD).

## Walkthrough: Ubuntu 22.04 + NVIDIA + vLLM

For a GPU server (datacenter or a beefy consumer card) that will serve several users or run long research jobs, vLLM gives the best throughput. This is the full path from a fresh VM to a working install.

### 1. NVIDIA driver + toolkit

```bash
sudo apt update
sudo apt install -y nvidia-driver-550 nvidia-container-toolkit
sudo reboot
```

After reboot, verify:

```bash
nvidia-smi   # should print your GPU and driver version
```

### 2. Install NOVA AI

```bash
curl -fsSL https://hamza35779.github.io/NOVA-AI/install.sh | bash
```

The installer detects the NVIDIA card. On datacenter GPUs it proposes **vLLM** as the recommended engine; on consumer cards it proposes Ollama but vLLM works too if you prefer the throughput.

### 3. Install and start vLLM

```bash
# dedicated venv keeps vLLM's heavy deps out of NOVA's
python3 -m venv ~/vllm-env
source ~/vllm-env/bin/activate
pip install vllm
vllm serve Qwen/Qwen2.5-7B-Instruct --port 8000 &
```

vLLM is auto-detected at `http://localhost:8000`. Verify from NOVA:

```bash
nova model list      # should list the served model
nova doctor          # engine health check
```

### 4. First run

```bash
nova init            # confirm the detected engine, or re-run with --force
nova ask "What is 2+2?"
```

!!! tip "Make it survive reboots"
    Use the systemd unit in `deploy/systemd/` to keep `nova serve` and `vllm serve` running: see [deployment/systemd](../deployment/api-server.md).

!!! tip "Best for: datacenter GPUs (A100, H100), multi-user serving"
    Consumer RTX cards are fine with Ollama — simpler to run, still fast for single users.

## Walkthrough: Raspberry Pi 5 (CPU-only)

A $100 entry point for hobbyists. Expect small models (1–3B parameters) at modest speed — good for a home automation brain or a scheduled-digest box, not for interactive chat.

### 1. Prepare the Pi

Use the 64-bit Raspberry Pi OS (Bookworm). 8 GB RAM is the practical minimum; 4 GB works with the smallest models.

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git curl build-essential
```

!!! warning "Cooling"
    Sustained inference throttles without active cooling. A fan or heatsink case is strongly recommended.

### 2. Install NOVA AI

```bash
curl -fsSL https://hamza35779.github.io/NOVA-AI/install.sh | bash
```

The installer detects CPU-only hardware and recommends **llama.cpp** (with a lighter Ollama fallback for serving small models).

### 3. Pull a small model

```bash
ollama serve &
ollama pull qwen2.5:3b     # ~2 GB; use qwen2.5:1.5b on a 4 GB Pi
```

### 4. Verify

```bash
nova doctor                # engine checks pass (slow the first time)
nova ask "Say hello"       # expect a few tokens/second — patience is a virtue
```

### What works well on a Pi

- `morning-digest-minimal` preset — a once-a-day briefing is a perfect fit
- `nova memory` queries against an indexed knowledge base
- Scheduled operators that wake, work, and sleep

Interactive voice and deep research want more horsepower.

## See also

- [Full installer reference](install.md)
- [WSL2 install](wsl2.md) — if this "Linux" is actually inside Windows
- [Native Windows install](windows-native.md)

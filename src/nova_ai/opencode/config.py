"""opencode config template, CLI detection, installer, and merge logic.

Everything here is stdlib-only so ``nova opencode`` works on a bare
interpreter without extra dependencies.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

NOVA_PROVIDER_ID = "nova-ai"
NOVA_MCP_ID = "nova-ai-tools"
DEFAULT_SERVER_URL = "http://127.0.0.1:8000"
FALLBACK_MODELS = ["qwen3:8b"]

SCHEMA_URL = "https://opencode.ai/config.json"

# opencode.json provider key → environment variable holding its secret.
# The generated template only ever references these as {env:...}; raw keys
# must never be written to the file (see `persist_env_var`).
PROVIDER_ENV_VARS: dict[str, str] = {
    "b.ai": "B_AI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

# Provider IDs whose traffic never leaves this machine (loopback servers).
# Everything else in an opencode config is treated as CLOUD for the privacy
# readout in `nova opencode status`.
LOCAL_PROVIDERS = frozenset({"nova-ai", "ollama", "llama.cpp", "lmstudio", "atomic-chat"})


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect_opencode() -> str | None:
    """Return the opencode executable path, or ``None`` when not installed."""
    found = shutil.which("opencode")
    if found:
        return found
    # npm global bin may not be on PATH in GUI-launched terminals; probe it.
    npm = shutil.which("npm")
    if npm:
        try:
            proc = subprocess.run(
                [npm, "root", "-g"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode == 0:
                root = proc.stdout.strip()
                for exe in ("opencode", "opencode.exe", "opencode.cmd"):
                    candidate = str(Path(root) / "opencode-ai" / "bin" / exe)
                    alt = str(Path(root) / ".bin" / exe)
                    for path in (candidate, alt):
                        if Path(path).is_file():
                            return path
        except (OSError, subprocess.SubprocessError) as exc:
            logger.debug("npm global probe failed: %s", exc)
    return None


def opencode_version(exe: str | None = None) -> str | None:
    """Return ``opencode --version`` output, or ``None`` on failure."""
    exe = exe or detect_opencode()
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else "unknown"


def nova_command() -> list[str]:
    """How opencode should invoke this NOVA AI checkout (MCP ``command``).

    Prefers the ``nova`` console script when it resolves on PATH so the
    generated config keeps working outside this checkout; otherwise falls
    back to the current interpreter with ``PYTHONPATH``-independent
    ``-m`` invocation (works from a source tree or ``uv run``).
    """
    if shutil.which("nova"):
        return ["nova", "mcp", "serve"]
    return [sys.executable, "-m", "nova_ai.cli", "mcp", "serve"]


# ---------------------------------------------------------------------------
# Server probing
# ---------------------------------------------------------------------------


def _is_nova_server(base_url: str, timeout: float) -> bool:
    """True when the server identifies as NOVA AI (guards port collisions).

    A plain ``/health`` 2xx is not enough — another app may own the port
    (seen live: a foreign service answering ``/health`` on NOVA's default
    8000). NOVA always serves ``/openapi.json`` with its title.
    """
    try:
        with urllib.request.urlopen(
            f"{base_url.rstrip('/')}/openapi.json", timeout=timeout
        ) as resp:
            if not 200 <= resp.status < 300:
                return False
            info = json.loads(resp.read().decode("utf-8")).get("info", {})
            title = str(info.get("title", ""))
            return "nova" in title.lower()
    except (OSError, ValueError):
        return False


def server_health(base_url: str = DEFAULT_SERVER_URL, timeout: float = 3.0) -> bool:
    """True when ``GET {base}/health`` answers 2xx *on a NOVA AI server*."""
    try:
        with urllib.request.urlopen(
            f"{base_url.rstrip('/')}/health", timeout=timeout
        ) as resp:
            if not 200 <= resp.status < 300:
                return False
    except OSError:
        return False
    return _is_nova_server(base_url, timeout)


def fetch_server_models(
    base_url: str = DEFAULT_SERVER_URL, timeout: float = 5.0
) -> list[str] | None:
    """Return model IDs from ``GET {base}/v1/models`` or ``None``.

    Sends ``NOVA_AI_API_KEY`` as Bearer when set (keyless local servers
    ignore the header). ``None`` means "server unreachable" — callers must
    fall back to :data:`FALLBACK_MODELS`, never to an empty provider.
    """
    url = f"{base_url.rstrip('/')}/v1/models"
    headers = {}
    api_key = os.environ.get("NOVA_AI_API_KEY", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        logger.debug("NOVA server model list unavailable (%s): %s", url, exc)
        return None
    ids = [
        item.get("id")
        for item in payload.get("data", [])
        if isinstance(item, dict) and item.get("id")
    ]
    return ids or None


# ---------------------------------------------------------------------------
# Config template + merge
# ---------------------------------------------------------------------------


def build_config(
    models: list[str] | None,
    *,
    server_url: str = DEFAULT_SERVER_URL,
    with_mcp: bool = True,
    nova_cmd: list[str] | None = None,
    local_only: bool = False,
) -> dict[str, Any]:
    """Build the NOVA-managed slice of ``opencode.json``.

    ``models`` are verbatim ``/v1/models`` IDs (``None`` → starter
    fallback). The slice is designed to be *merged* into the user's file:
    see :func:`merge_config`.
    """
    ids = models or list(FALLBACK_MODELS)
    provider_models = {mid: {"name": f"{mid} (via NOVA AI)"} for mid in ids}
    config: dict[str, Any] = {
        "$schema": SCHEMA_URL,
        "model": f"{NOVA_PROVIDER_ID}/{ids[0]}",
        "small_model": f"{NOVA_PROVIDER_ID}/{ids[0]}",
        "provider": {
            NOVA_PROVIDER_ID: {
                "npm": "@ai-sdk/openai-compatible",
                "name": "NOVA AI (local)",
                "options": {
                    "baseURL": f"{server_url.rstrip('/')}/v1",
                    "apiKey": "{env:NOVA_AI_API_KEY}",
                },
                "models": provider_models,
            }
        },
    }
    if with_mcp:
        config["mcp"] = {
            NOVA_MCP_ID: {
                "type": "local",
                "command": nova_cmd or nova_command(),
                "enabled": True,
            }
        }
    config["instructions"] = ["AGENTS.md"]
    if local_only:
        # Private mode: opencode may only use the loopback NOVA provider
        # (cloud providers stay configured but are never selected), and
        # session sharing (uploads transcripts to opencode.ai) is off.
        config["enabled_providers"] = [NOVA_PROVIDER_ID]
        config["share"] = "disabled"
    return config


def merge_config(existing: dict[str, Any], generated: dict[str, Any]) -> dict[str, Any]:
    """Merge the NOVA slice into an existing config without clobbering.

    - ``provider`` / ``mcp``: NOVA entries are (over)written; every other
      provider/server the user configured is preserved untouched.
    - ``model`` / ``small_model``: kept when the user already set them;
      filled from the generated slice only when missing.
    - ``enabled_providers`` / ``share``: applied when the generated slice
      carries them (``--local-only``); otherwise left untouched.
    - ``instructions``: ``AGENTS.md`` is appended when absent.
    - Everything else (agents, permissions, themes, …) passes through.
    """
    merged = dict(existing)
    providers = dict(merged.get("provider", {}))
    providers.update(generated.get("provider", {}))
    merged["provider"] = providers
    if "mcp" in generated:
        servers = dict(merged.get("mcp", {}))
        servers.update(generated["mcp"])
        merged["mcp"] = servers
    for key in ("model", "small_model"):
        if not merged.get(key) and generated.get(key):
            merged[key] = generated[key]
    for key in ("enabled_providers", "share"):
        if key in generated:
            merged[key] = generated[key]
    instructions = list(merged.get("instructions", []))
    for item in generated.get("instructions", []):
        if item not in instructions:
            instructions.append(item)
    if instructions:
        merged["instructions"] = instructions
    if "$schema" not in merged:
        merged["$schema"] = SCHEMA_URL
    return merged


def read_config(path: Path) -> dict[str, Any]:
    """Read ``opencode.json`` (tolerates missing file and JSONC comments)."""
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Best-effort JSONC: strip // and /* */ comments outside strings.
        data = json.loads(_strip_jsonc_comments(text))
    return data if isinstance(data, dict) else {}


def _strip_jsonc_comments(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def write_project_config(
    directory: Path | str = ".",
    *,
    server_url: str = DEFAULT_SERVER_URL,
    with_mcp: bool = True,
    force_model: bool = False,
    local_only: bool = False,
) -> tuple[Path, bool, list[str] | None]:
    """Write/merge ``opencode.json`` in *directory*.

    Returns ``(path, server_reachable, models_used)``. Never raises on
    server errors — falls back to :data:`FALLBACK_MODELS` with the server
    marked unreachable so callers can print the "start nova serve" hint.
    """
    target = Path(directory) / "opencode.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    models = fetch_server_models(server_url)
    reachable = models is not None
    generated = build_config(
        models, server_url=server_url, with_mcp=with_mcp, local_only=local_only
    )
    existing = read_config(target)
    if force_model:
        existing.pop("model", None)
        existing.pop("small_model", None)
    merged = merge_config(existing, generated)
    target.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return target, reachable, models or list(FALLBACK_MODELS)


def list_configured_models(path: Path | str = "opencode.json") -> list[str]:
    """Model IDs in the NOVA provider slice of an existing config."""
    data = read_config(Path(path))
    providers = data.get("provider", {})
    if not isinstance(providers, dict):
        return []
    nova = providers.get(NOVA_PROVIDER_ID, {})
    models = nova.get("models", {}) if isinstance(nova, dict) else {}
    return [mid for mid in models if isinstance(mid, str)]


def current_default_model(path: Path | str = "opencode.json") -> str | None:
    """The config's default ``model`` value, if any."""
    data = read_config(Path(path))
    model = data.get("model")
    return model if isinstance(model, str) and model else None


def privacy_report(
    path: Path | str = "opencode.json",
) -> dict[str, Any]:
    """Where does this project's opencode data flow?

    Returns ``{"providers": [(id, residency, selectable)], "share": ...,
    "local_only": bool}`` where residency is ``"local"`` (loopback — code
    never leaves the machine) or ``"cloud"``. ``local_only`` is True when
    the allowlist restricts selection to local providers.
    """
    data = read_config(Path(path))
    providers = data.get("provider", {})
    if not isinstance(providers, dict):
        providers = {}
    allow = data.get("enabled_providers")
    deny = set(data.get("disabled_providers", []) or [])
    rows: list[tuple[str, str, bool]] = []
    for pid in providers:
        residency = "local" if pid in LOCAL_PROVIDERS else "cloud"
        selectable = pid not in deny and (allow is None or pid in allow)
        rows.append((str(pid), residency, selectable))
    share = data.get("share", "manual")
    local_only = isinstance(allow, list) and bool(allow) and all(
        p in LOCAL_PROVIDERS for p in allow
    )
    return {"providers": rows, "share": share, "local_only": local_only}


def set_default_model(
    model_id: str, path: Path | str = "opencode.json"
) -> tuple[bool, str]:
    """Point the config's default model at a NOVA model.

    Accepts ``qwen3:8b`` or ``nova-ai/qwen3:8b``. Returns ``(ok, message)``;
    never raises. ``small_model`` follows ``model`` unless the user set a
    non-NOVA small model explicitly (then it is left alone).
    """
    target = Path(path)
    data = read_config(target)
    ref = model_id if "/" in model_id else f"{NOVA_PROVIDER_ID}/{model_id}"
    data["model"] = ref
    small = data.get("small_model")
    if not isinstance(small, str) or small.startswith(f"{NOVA_PROVIDER_ID}/"):
        data["small_model"] = ref
    if "$schema" not in data:
        data["$schema"] = SCHEMA_URL
    try:
        target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        return False, f"could not write {target}: {exc}"
    return True, f"default model → {ref}"


def persist_env_var(name: str, value: str) -> tuple[bool, str]:
    """Persist a secret to the user's environment (never to a file).

    - Windows: ``setx`` (user scope, future terminals) + current process.
    - POSIX: append ``export NAME='…'`` to ``~/.zshrc``/``~/.bashrc``
      (replacing any older line for the same name) + current process.

    Returns ``(ok, message)``; never raises.
    """
    value = value.strip()
    if not value:
        return False, "empty value — nothing stored"
    os.environ[name] = value
    if sys.platform == "win32":
        try:
            proc = subprocess.run(
                ["setx", name, value], capture_output=True, text=True, timeout=30
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return True, (
                f"set for this session only (setx failed: {exc}); "
                f"persist manually via System environment variables"
            )
        if proc.returncode != 0:
            return True, (
                "set for this session only (setx failed); persist manually "
                "via System environment variables"
            )
        return True, (
            f"{name} stored (this session + future terminals; "
            "restart open terminals to pick it up)"
        )
    rc = Path.home() / (".zshrc" if os.environ.get("SHELL", "").endswith("zsh") else ".bashrc")
    line = f"export {name}='{value.replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'"
    try:
        existing = rc.read_text(encoding="utf-8").splitlines() if rc.is_file() else []
        kept = [ln for ln in existing if not ln.strip().startswith(f"export {name}=")]
        kept.append(line)
        rc.write_text("\n".join(kept) + "\n", encoding="utf-8")
    except OSError as exc:
        return True, f"set for this session only ({rc} not writable: {exc})"
    return True, f"{name} stored (this session + {rc})"


# ---------------------------------------------------------------------------
# Installer
# ---------------------------------------------------------------------------


def install_opencode(*, dry_run: bool = False) -> tuple[bool, str]:
    """Install the opencode CLI when missing; no-op when present.

    Returns ``(ok, message)``. ``ok`` is True when opencode is usable
    afterwards. Never raises — every failure becomes guidance text.
    """
    found = detect_opencode()
    if found:
        version = opencode_version(found) or "unknown version"
        return True, f"opencode already installed ({version} at {found})"

    system = platform.system()
    node = shutil.which("node") or shutil.which("nodejs")
    npm = shutil.which("npm")
    steps: list[list[str]] = []
    how = ""
    if system == "Windows":
        if npm:
            steps.append([npm, "install", "-g", "opencode-ai"])
            how = "npm install -g opencode-ai"
        else:
            return False, (
                "opencode not found and no installer available: install Node.js "
                "(https://nodejs.org, includes npm) then run "
                "`npm install -g opencode-ai`, or `choco install opencode` / "
                "`scoop install opencode`."
            )
    else:
        curl = shutil.which("curl")
        bash = shutil.which("bash")
        if curl and bash:
            steps.append(["sh", "-c", "curl -fsSL https://opencode.ai/install | bash"])
            how = "curl -fsSL https://opencode.ai/install | bash"
        elif npm:
            steps.append([npm, "install", "-g", "opencode-ai"])
            how = "npm install -g opencode-ai"
        else:
            return False, (
                "opencode not found and no installer available: install curl "
                "or Node.js, then run `curl -fsSL https://opencode.ai/install "
                "| bash` or `npm install -g opencode-ai`."
            )
    if node is None and system == "Windows":
        logger.warning("Node.js not on PATH; npm-based install may fail")
    if dry_run:
        return False, f"would run: {how}"
    for cmd in steps:
        try:
            proc = subprocess.run(cmd, timeout=600)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"installer failed to start ({exc}); try manually: {how}"
        if proc.returncode == 0 and detect_opencode():
            return True, f"opencode installed via: {how}"
    return False, (
        f"install command failed; try manually: {how} "
        "(https://opencode.ai/docs/)"
    )


__all__ = [
    "DEFAULT_SERVER_URL",
    "FALLBACK_MODELS",
    "NOVA_MCP_ID",
    "NOVA_PROVIDER_ID",
    "PROVIDER_ENV_VARS",
    "SCHEMA_URL",
    "build_config",
    "current_default_model",
    "detect_opencode",
    "fetch_server_models",
    "install_opencode",
    "list_configured_models",
    "merge_config",
    "nova_command",
    "opencode_version",
    "persist_env_var",
    "privacy_report",
    "read_config",
    "server_health",
    "set_default_model",
    "write_project_config",
]

"""Deployment targets for trained LoRA adapters.

Takes an adapter directory produced by the training pipeline and makes it
usable through one or more inference paths:

* **adapter** — keep the PEFT adapter as-is (default; the adapter dir is
  already the artifact).
* **ollama** — write a Modelfile (``FROM <base>`` + ``ADAPTER <dir>``) and
  run ``ollama create``. The resulting tag shows up in Ollama's model list,
  so NOVA's engine discovery picks it up on the next probe.
* **llamacpp** — merge the adapter into the base weights
  (``merge_and_unload``) and convert to GGUF via llama.cpp's
  ``convert_hf_to_gguf.py`` (path configured in ``[learning.training]``).

Each target is independent: a failure in one is logged and returned, never
raised, so a missing Ollama install doesn't abort an otherwise-good run.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VALID_TARGETS = ("adapter", "ollama", "llamacpp")


@dataclass
class DeployResult:
    """Outcome of deploying one adapter to one target."""

    target: str
    ok: bool
    detail: str = ""  # tag / path on success, error message on failure


@dataclass
class DeployReport:
    """Aggregated results across all requested targets."""

    results: list[DeployResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True if at least one target succeeded."""
        return any(r.ok for r in self.results)

    def to_list(self) -> list[dict[str, Any]]:
        """Serialize for persistence in the run store."""
        return [
            {"target": r.target, "ok": r.ok, "detail": r.detail}
            for r in self.results
        ]


def sanitize_model_tag(model: str) -> str:
    """Turn a model name into a tag-safe slug (``qwen3:8b`` → ``qwen3_8b``)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model).strip("_")


def ollama_tag(base_model: str, *, prefix: str = "nova-tuned") -> str:
    """Tag for the Ollama model created from a tuned adapter."""
    return f"{prefix}-{sanitize_model_tag(base_model)}"


def adapter_meta(adapter_dir: Path) -> dict[str, Any]:
    """Load ``adapter_meta.json`` written by the training pipeline."""
    meta_path = Path(adapter_dir) / "adapter_meta.json"
    if not meta_path.exists():
        return {}
    import json

    with open(meta_path, encoding="utf-8") as f:
        return dict(json.load(f))  # type: ignore[arg-type]


def _base_model_for(adapter_dir: Path, base_model: str | None) -> str:
    """Resolve the base model name, preferring explicit over metadata."""
    if base_model:
        return base_model
    meta = adapter_meta(adapter_dir)
    name = meta.get("base_model", "")
    if not name:
        raise ValueError(
            f"No base model: pass base_model explicitly or ensure "
            f"{adapter_dir / 'adapter_meta.json'} has 'base_model'"
        )
    return str(name)


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------


def deploy_adapter_only(adapter_dir: Path, **_kwargs: Any) -> DeployResult:
    """Adapter target: the PEFT adapter directory itself is the artifact."""
    adapter_dir = Path(adapter_dir)
    if not adapter_dir.exists():
        return DeployResult("adapter", False, f"adapter dir missing: {adapter_dir}")
    return DeployResult("adapter", True, str(adapter_dir))


def deploy_ollama(
    adapter_dir: Path,
    base_model: str | None = None,
    *,
    tag: str | None = None,
    tag_prefix: str = "nova-tuned",
) -> DeployResult:
    """Create an Ollama model from the adapter via a Modelfile."""
    adapter_dir = Path(adapter_dir)
    if not adapter_dir.exists():
        return DeployResult("ollama", False, f"adapter dir missing: {adapter_dir}")

    resolved_base = _base_model_for(adapter_dir, base_model)
    model_tag = tag or ollama_tag(resolved_base, prefix=tag_prefix)

    modelfile = adapter_dir / "Modelfile"
    modelfile.write_text(
        f"FROM {resolved_base}\nADAPTER {adapter_dir.resolve().as_posix()}\n",
        encoding="utf-8",
    )

    try:
        create = subprocess.run(
            ["ollama", "create", model_tag, "-f", str(modelfile)],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if create.returncode != 0:
            return DeployResult(
                "ollama",
                False,
                f"ollama create failed: {(create.stderr or create.stdout).strip()}",
            )
        verify = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=60
        )
        if model_tag not in verify.stdout:
            return DeployResult(
                "ollama", False, f"created but {model_tag} not in ollama list"
            )
    except FileNotFoundError:
        return DeployResult(
            "ollama", False, "ollama CLI not found; install Ollama or drop the target"
        )
    except subprocess.TimeoutExpired:
        return DeployResult("ollama", False, "ollama create timed out")

    logger.info("Deployed adapter to Ollama as %s", model_tag)
    return DeployResult("ollama", True, model_tag)


def deploy_llamacpp(
    adapter_dir: Path,
    base_model: str | None = None,
    *,
    gguf_script: str = "",
    merged_root: Path | None = None,
) -> DeployResult:
    """Merge the adapter into base weights and convert to GGUF.

    Requires torch+transformers+peft (merge) and llama.cpp's
    ``convert_hf_to_gguf.py`` (conversion). The GGUF path is returned in
    ``detail`` for use by the llamacpp engine.
    """
    adapter_dir = Path(adapter_dir)
    try:
        from nova_ai.learning.training.lora import HAS_TORCH

        if not HAS_TORCH:
            return DeployResult(
                "llamacpp", False, "torch/transformers/peft not installed"
            )
    except ImportError:
        return DeployResult("llamacpp", False, "training.lora not importable")

    resolved_base = _base_model_for(adapter_dir, base_model)
    tag = sanitize_model_tag(resolved_base)
    merged_root = Path(merged_root) if merged_root else _default_merged_root()
    merged_dir = merged_root / tag

    try:
        merged_dir.mkdir(parents=True, exist_ok=True)
        _merge_adapter(resolved_base, adapter_dir, merged_dir)
    except Exception as exc:
        return DeployResult("llamacpp", False, f"merge failed: {exc}")

    if not gguf_script:
        return DeployResult(
            "llamacpp",
            True,
            str(merged_dir),
            # Merged model usable by transformers-backed engines; GGUF
            # conversion skipped until llamacpp_gguf_script is configured.
        )

    script = Path(gguf_script)
    if not script.exists():
        return DeployResult(
            "llamacpp",
            True,
            f"{merged_dir} (gguf script missing: {script})",
        )

    gguf_out = merged_dir / f"{tag}.gguf"
    try:
        conv = subprocess.run(
            ["python", str(script), str(merged_dir), "--outfile", str(gguf_out)],
            capture_output=True,
            text=True,
            timeout=7200,
        )
        if conv.returncode != 0:
            return DeployResult(
                "llamacpp",
                True,
                f"{merged_dir} (gguf conversion failed: "
                f"{(conv.stderr or conv.stdout).strip()[:300]})",
            )
    except subprocess.TimeoutExpired:
        return DeployResult("llamacpp", True, f"{merged_dir} (gguf conversion timed out)")

    logger.info("Converted merged model to GGUF: %s", gguf_out)
    return DeployResult("llamacpp", True, str(gguf_out))


def _default_merged_root() -> Path:
    """Merged-model root under the NOVA AI home learning dir."""
    from nova_ai.core.paths import get_config_dir

    return get_config_dir() / "learning" / "training" / "merged"


def _merge_adapter(base_model: str, adapter_dir: Path, out_dir: Path) -> None:
    """Load base + adapter, merge, save the merged model."""
    import torch  # noqa: F401  (guarded by HAS_TORCH upstream)
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model = AutoModelForCausalLM.from_pretrained(
        base_model, torch_dtype=torch.bfloat16, device_map="cpu"
    )
    model = PeftModel.from_pretrained(model, str(adapter_dir))
    merged = model.merge_and_unload()

    merged.save_pretrained(str(out_dir))
    tokenizer = AutoTokenizer.from_pretrained(base_model)
    tokenizer.save_pretrained(str(out_dir))

    del model, merged  # free VRAM/RAM before conversion runs

    # Keep metadata with the merged copy so downstream steps know provenance.
    meta = adapter_meta(adapter_dir)
    if meta:
        import json

        with open(out_dir / "adapter_meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def deploy(
    adapter_dir: Path,
    *,
    targets: list[str],
    base_model: str | None = None,
    tag_prefix: str = "nova-tuned",
    gguf_script: str = "",
) -> DeployReport:
    """Deploy an adapter to each requested target.

    Targets are independent: one failing never stops the others. Unknown
    targets are reported as failures rather than silently dropped.
    """
    adapter_dir = Path(adapter_dir)
    report = DeployReport()

    for target in targets:
        if target == "adapter":
            report.results.append(deploy_adapter_only(adapter_dir))
        elif target == "ollama":
            report.results.append(
                deploy_ollama(adapter_dir, base_model, tag_prefix=tag_prefix)
            )
        elif target == "llamacpp":
            report.results.append(
                deploy_llamacpp(
                    adapter_dir, base_model, gguf_script=gguf_script
                )
            )
        else:
            report.results.append(
                DeployResult(
                    target,
                    False,
                    f"unknown target {target!r}; valid: {', '.join(VALID_TARGETS)}",
                )
            )

    return report


def cleanup_merged(merged_dir: Path) -> None:
    """Remove a merged-model directory (used when a run is rolled back)."""
    merged_dir = Path(merged_dir)
    if merged_dir.exists() and "merged" in merged_dir.parts:
        shutil.rmtree(merged_dir, ignore_errors=True)


__all__ = [
    "VALID_TARGETS",
    "DeployReport",
    "DeployResult",
    "adapter_meta",
    "cleanup_merged",
    "deploy",
    "deploy_adapter_only",
    "deploy_llamacpp",
    "deploy_ollama",
    "ollama_tag",
    "sanitize_model_tag",
]

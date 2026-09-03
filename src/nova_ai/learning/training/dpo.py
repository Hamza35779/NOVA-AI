"""DPOTrainer — preference tuning from fork/regen/race sibling choices.

Where SFT teaches the model *what a good answer looks like*, DPO (Direct
Preference Optimization) teaches it *which of two answers is better* —
exactly the signal conversation forking produces: for every fork,
regeneration, or model race the user picks a winner.

Structure mirrors :mod:`nova_ai.learning.training.lora`: a plain-data
config dataclass, optional deps guarded at import time (``HAS_TRL``),
``ImportError`` with an install hint at construction time. The trainer
formats each preference pair as a (prompt, chosen, rejected) triple,
tokenizes, and hands the dataset to ``trl.DPOTrainer`` wrapped in a PEFT
LoRA adapter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Optional imports -----------------------------------------------------------
try:
    import torch

    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    torch = None  # type: ignore[assignment]

from nova_ai.learning.training.lora import _select_device  # noqa: E402

try:
    from transformers import AutoModelForCausalLM, AutoTokenizer

    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False
    AutoModelForCausalLM = None  # type: ignore[assignment,misc]
    AutoTokenizer = None  # type: ignore[assignment,misc]

try:
    from peft import LoraConfig, TaskType, get_peft_model

    HAS_PEFT = True
except ImportError:
    HAS_PEFT = False
    LoraConfig = None  # type: ignore[assignment,misc]
    TaskType = None  # type: ignore[assignment,misc]
    get_peft_model = None  # type: ignore[assignment,misc]

try:
    from trl import DPOConfig
    from trl import DPOTrainer as _TRLTrainer

    HAS_TRL = True
except ImportError:
    HAS_TRL = False
    DPOConfig = None  # type: ignore[assignment,misc]
    _TRLTrainer = None  # type: ignore[assignment,misc]

_TRL_INSTALL_HINT = (
    "trl is required for DPO training. "
    "Install with: pip install 'nova-ai[dpo-training]' "
    "(or pip install trl peft transformers torch)"
)


@dataclass
class DPOTrainingConfig:
    """Configuration for DPO preference tuning."""

    # DPO params
    beta: float = 0.1  # KL penalty: higher = stay closer to the reference
    loss_type: str = "sigmoid"  # sigmoid | hinge | ipo

    # LoRA params (the DPO adapter rides on the same PEFT machinery)
    lora_rank: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    target_modules: List[str] | None = None

    # Training params
    num_epochs: int = 1  # DPO overfits fast; fewer epochs than SFT
    batch_size: int = 2  # each example carries TWO sequences (chosen+rejected)
    gradient_accumulation_steps: int = 8
    learning_rate: float = 5e-6  # 3-10x lower than SFT is the norm
    max_seq_length: int = 1024
    max_prompt_length: int = 512

    # Output
    output_dir: str = "checkpoints/dpo"

    def __post_init__(self) -> None:
        if self.beta <= 0:
            raise ValueError(f"beta must be > 0, got {self.beta}")
        if self.num_epochs < 1:
            raise ValueError(f"num_epochs must be >= 1, got {self.num_epochs}")
        if self.target_modules is None:
            self.target_modules = ["q_proj", "v_proj"]


def format_preference_pairs(pairs: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Normalize raw preference dicts to ``{prompt, chosen, rejected}``.

    Accepts both the miner's schema (``prompt``/``chosen``/``rejected``)
    and TRL's conversational shape; drops incomplete entries.
    """
    out: List[Dict[str, str]] = []
    for pair in pairs:
        prompt = str(pair.get("prompt", "")).strip()
        chosen = str(pair.get("chosen", "")).strip()
        rejected = str(pair.get("rejected", "")).strip()
        if not prompt or not chosen or not rejected or chosen == rejected:
            continue
        out.append({"prompt": prompt, "chosen": chosen, "rejected": rejected})
    return out


class DPOTrainer:
    """Fine-tune a local model with DPO over preference pairs.

    Raises
    ------
    ImportError
        If ``trl`` (or ``torch``) is not installed.
    """

    def __init__(
        self,
        config: DPOTrainingConfig,
        *,
        model_name: str = "Qwen/Qwen3-0.6B",
        device: Optional[str] = None,
    ) -> None:
        if not HAS_TORCH:
            raise ImportError(
                "torch is required for DPOTrainer. "
                "Install with: pip install torch transformers peft trl"
            )
        if not HAS_TRL:
            raise ImportError(_TRL_INSTALL_HINT)

        self.config = config
        self.model_name = model_name
        self.device = _select_device(device)
        self.tokenizer: Any = None
        self.model: Any = None

    # -- Public API ----------------------------------------------------------

    def train(self, pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Run DPO training on the given preference pairs.

        Returns a summary dict mirroring ``LoRATrainer.train``:
        ``status``, ``epochs``, ``avg_loss``, ``adapter_path``,
        ``training_samples``.
        """
        if not pairs:
            return {"status": "skipped", "reason": "no preference data"}

        dataset = format_preference_pairs(pairs)
        if not dataset:
            return {"status": "skipped", "reason": "no valid preference pairs"}

        self._ensure_tokenizer()
        self._load_model()
        self._apply_lora()

        import datasets as hf_datasets

        hf_dataset = hf_datasets.Dataset.from_list(dataset)

        if not HAS_PEFT or LoraConfig is None:
            raise ImportError(
                "peft is required for DPO training. Install with: pip install peft"
            )

        peft_config = LoraConfig(
            task_type=TaskType.CAUSAL_LM,
            r=self.config.lora_rank,
            lora_alpha=self.config.lora_alpha,
            lora_dropout=self.config.lora_dropout,
            target_modules=self.config.target_modules,
        )
        training_args = DPOConfig(
            output_dir=self.config.output_dir,
            per_device_train_batch_size=self.config.batch_size,
            gradient_accumulation_steps=self.config.gradient_accumulation_steps,
            num_train_epochs=self.config.num_epochs,
            learning_rate=self.config.learning_rate,
            beta=self.config.beta,
            loss_type=self.config.loss_type,
            max_length=self.config.max_seq_length,
            max_prompt_length=self.config.max_prompt_length,
            logging_steps=1,
            save_strategy="no",
            report_to=[],
        )
        trainer = _TRLTrainer(
            model=self.model,
            args=training_args,
            train_dataset=hf_dataset,
            tokenizer=self.tokenizer,
            peft_config=peft_config,
        )
        train_result = trainer.train()

        adapter_path = str(Path(self.config.output_dir) / "final")
        out = Path(adapter_path)
        out.mkdir(parents=True, exist_ok=True)
        trainer.save_model(adapter_path)
        if self.tokenizer is not None:
            self.tokenizer.save_pretrained(adapter_path)

        loss = train_result.metrics.get("train_loss", 0.0)
        return {
            "status": "completed",
            "epochs": self.config.num_epochs,
            "avg_loss": float(loss),
            "adapter_path": adapter_path,
            "training_samples": len(dataset),
        }

    # -- Internal helpers ----------------------------------------------------

    def _ensure_tokenizer(self) -> None:
        if self.tokenizer is not None:
            return
        if not HAS_TRANSFORMERS:
            raise ImportError(
                "transformers is required for DPOTrainer. "
                "Install with: pip install transformers"
            )
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

    def _load_model(self) -> None:
        if self.model is not None:
            return
        if not HAS_TRANSFORMERS:
            raise ImportError(
                "transformers is required for DPOTrainer. "
                "Install with: pip install transformers"
            )
        self._ensure_tokenizer()
        model_kwargs: Dict[str, Any] = {"torch_dtype": torch.bfloat16}
        if self.device == "cuda":
            model_kwargs["device_map"] = "auto"
        else:
            model_kwargs["device_map"] = {"": self.device}
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_name, **model_kwargs
        )

    def _apply_lora(self) -> None:
        # The LoRA adapter is applied inside trl.DPOTrainer via peft_config;
        # nothing to do here — kept for symmetry with LoRATrainer.
        return None


__all__ = [
    "DPOTrainer",
    "DPOTrainingConfig",
    "HAS_TRL",
    "format_preference_pairs",
]

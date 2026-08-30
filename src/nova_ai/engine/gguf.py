"""Standalone GGUF inference engine backed by llama-cpp-python.

Runs quantized GGUF models directly in-process — no Ollama, no external
server required. Models are downloaded from Hugging Face Hub and cached
under ``~/.nova_ai/models/``.

Usage example::

    from nova_ai.engine.gguf import GGUFEngine, download_gguf_model

    # One-time download from HF
    local_path = download_gguf_model(
        repo_id="Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        filename="qwen2.5-0.5b-instruct-q4_k_m.gguf",
    )

    engine = GGUFEngine()
    engine.load_model(local_path)

    result = engine.generate(
        [{"role": "user", "content": "Hello!"}],
        model=local_path,
    )
    print(result["content"])
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from nova_ai.core.registry import EngineRegistry
from nova_ai.core.types import Message
from nova_ai.engine._base import InferenceEngine

logger = logging.getLogger(__name__)

# Default model cache directory
_MODELS_DIR = Path.home() / ".nova_ai" / "models"

# Supported models catalog with their HF repo and file details
GGUF_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "qwen2.5-0.5b",
        "name": "Qwen 2.5 0.5B (Q4)",
        "repo_id": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "filename": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "category": "fast",
        "params": "0.5B",
        "size_gb": 0.4,
        "min_ram_gb": 1,
        "description": "Ultra-lightweight for CPU. Instant responses on any machine.",
        "recommended": True,
    },
    {
        "id": "qwen2.5-1.5b",
        "name": "Qwen 2.5 1.5B (Q4)",
        "repo_id": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "category": "fast",
        "params": "1.5B",
        "size_gb": 1.0,
        "min_ram_gb": 2,
        "description": "Compact and fast, great for summarization and quick Q&A.",
        "recommended": True,
    },
    {
        "id": "qwen2.5-7b",
        "name": "Qwen 2.5 7B (Q4)",
        "repo_id": "Qwen/Qwen2.5-7B-Instruct-GGUF",
        "filename": "qwen2.5-7b-instruct-q4_k_m.gguf",
        "category": "general",
        "params": "7B",
        "size_gb": 4.7,
        "min_ram_gb": 6,
        "description": "Best all-rounder for daily use, writing, and analysis.",
        "recommended": True,
    },
    {
        "id": "llama3.2-1b",
        "name": "Llama 3.2 1B (Q4)",
        "repo_id": "bartowski/Llama-3.2-1B-Instruct-GGUF",
        "filename": "Llama-3.2-1B-Instruct-Q4_K_M.gguf",
        "category": "fast",
        "params": "1B",
        "size_gb": 0.7,
        "min_ram_gb": 1,
        "description": "Meta's edge model, ideal for laptops with limited RAM.",
        "recommended": False,
    },
    {
        "id": "llama3.2-3b",
        "name": "Llama 3.2 3B (Q4)",
        "repo_id": "bartowski/Llama-3.2-3B-Instruct-GGUF",
        "filename": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "category": "fast",
        "params": "3B",
        "size_gb": 2.0,
        "min_ram_gb": 3,
        "description": "Meta's balanced small model for chat and reasoning.",
        "recommended": True,
    },
    {
        "id": "phi4-mini",
        "name": "Phi-4 Mini 3.8B (Q4)",
        "repo_id": "bartowski/Phi-4-mini-instruct-GGUF",
        "filename": "Phi-4-mini-instruct-Q4_K_M.gguf",
        "category": "reasoning",
        "params": "3.8B",
        "size_gb": 2.5,
        "min_ram_gb": 4,
        "description": "Microsoft's compact powerhouse for math and reasoning tasks.",
        "recommended": True,
    },
    {
        "id": "deepseek-r1-1.5b",
        "name": "DeepSeek R1 1.5B (Q4)",
        "repo_id": "bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF",
        "filename": "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf",
        "category": "reasoning",
        "params": "1.5B",
        "size_gb": 1.1,
        "min_ram_gb": 2,
        "description": "Chain-of-thought reasoning distilled into a tiny model.",
        "recommended": True,
    },
    {
        "id": "deepseek-r1-7b",
        "name": "DeepSeek R1 7B (Q4)",
        "repo_id": "bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF",
        "filename": "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",
        "category": "reasoning",
        "params": "7B",
        "size_gb": 4.7,
        "min_ram_gb": 6,
        "description": "Advanced reasoning and math problem solving.",
        "recommended": False,
    },
    {
        "id": "mistral-7b",
        "name": "Mistral 7B v0.3 (Q4)",
        "repo_id": "bartowski/Mistral-7B-Instruct-v0.3-GGUF",
        "filename": "Mistral-7B-Instruct-v0.3-Q4_K_M.gguf",
        "category": "general",
        "params": "7B",
        "size_gb": 4.1,
        "min_ram_gb": 6,
        "description": "Reliable instruction-following for general knowledge tasks.",
        "recommended": False,
    },
    {
        "id": "gemma2-2b",
        "name": "Gemma 2 2B (Q4)",
        "repo_id": "bartowski/gemma-2-2b-it-GGUF",
        "filename": "gemma-2-2b-it-Q4_K_M.gguf",
        "category": "fast",
        "params": "2B",
        "size_gb": 1.6,
        "min_ram_gb": 2,
        "description": "Google's compact Gemma 2 for everyday conversations.",
        "recommended": False,
    },
    {
        "id": "smollm2-1.7b",
        "name": "SmolLM2 1.7B (Q4)",
        "repo_id": "bartowski/SmolLM2-1.7B-Instruct-GGUF",
        "filename": "SmolLM2-1.7B-Instruct-Q4_K_M.gguf",
        "category": "fast",
        "params": "1.7B",
        "size_gb": 1.0,
        "min_ram_gb": 1,
        "description": "HuggingFace's ultra-fast, battery-friendly edge model.",
        "recommended": False,
    },
    {
        "id": "qwen2.5-coder-7b",
        "name": "Qwen 2.5 Coder 7B (Q4)",
        "repo_id": "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
        "filename": "qwen2.5-coder-7b-instruct-q4_k_m.gguf",
        "category": "coding",
        "params": "7B",
        "size_gb": 4.7,
        "min_ram_gb": 6,
        "description": "Top-tier code completion in 338 languages.",
        "recommended": True,
    },
]


def get_models_dir() -> Path:
    """Return the local model cache directory, creating it if needed."""
    models_dir = Path(os.environ.get("NOVA_MODELS_DIR", str(_MODELS_DIR)))
    models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir


def get_model_path(model_id: str) -> Optional[Path]:
    """Return the local path for a downloaded model, or None if not present."""
    entry = next((m for m in GGUF_CATALOG if m["id"] == model_id), None)
    if entry is None:
        # Check if model_id is a direct filename
        candidate = get_models_dir() / model_id
        return candidate if candidate.exists() else None
    candidate = get_models_dir() / entry["filename"]
    return candidate if candidate.exists() else None


def list_installed_gguf_models() -> List[str]:
    """Return IDs of GGUF catalog models that are already downloaded."""
    models_dir = get_models_dir()
    installed = []
    for entry in GGUF_CATALOG:
        if (models_dir / entry["filename"]).exists():
            installed.append(entry["id"])
    return installed


def download_gguf_model(
    model_id: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Path:
    """Download a GGUF model from Hugging Face Hub.

    Args:
        model_id: Catalog model ID (e.g. ``"qwen2.5-0.5b"``) or a
            ``repo_id::filename`` string for custom models.
        progress_callback: Optional callable receiving ``(bytes_downloaded, total_bytes)``.

    Returns:
        Local path to the downloaded ``.gguf`` file.

    Raises:
        ValueError: If the model ID is not found in the catalog.
        RuntimeError: If the download fails.
    """
    import httpx

    # Resolve catalog entry
    entry = next((m for m in GGUF_CATALOG if m["id"] == model_id), None)
    if entry is None:
        raise ValueError(
            f"Unknown model ID: {model_id!r}. "
            f"Available: {[m['id'] for m in GGUF_CATALOG]}"
        )

    repo_id: str = entry["repo_id"]
    filename: str = entry["filename"]
    dest = get_models_dir() / filename

    if dest.exists():
        logger.info("Model already cached at %s", dest)
        return dest

    # Build Hugging Face direct download URL
    hf_url = f"https://huggingface.co/{repo_id}/resolve/main/{filename}"

    logger.info("Downloading %s from %s", filename, hf_url)

    try:
        with httpx.stream(
            "GET",
            hf_url,
            follow_redirects=True,
            timeout=None,
            headers={"User-Agent": "nova-ai/1.2.1"},
        ) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            downloaded = 0
            tmp = dest.with_suffix(".tmp")
            try:
                with tmp.open("wb") as fh:
                    for chunk in resp.iter_bytes(chunk_size=1024 * 256):
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total)
                tmp.rename(dest)
            except Exception:
                tmp.unlink(missing_ok=True)
                raise
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Download failed with HTTP {exc.response.status_code}: {hf_url}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Download failed: {exc}") from exc

    logger.info("Model saved to %s (%.1f MB)", dest, dest.stat().st_size / 1_048_576)
    return dest


@EngineRegistry.register("gguf")
class GGUFEngine(InferenceEngine):
    """In-process GGUF inference engine powered by llama-cpp-python.

    Models are loaded on first use and cached in memory. Supports CPU
    and GPU (CUDA/Metal) acceleration automatically.

    No external services required — the engine runs entirely within the
    NOVA AI Python process.
    """

    engine_id = "gguf"

    def __init__(self) -> None:
        self._models: Dict[str, Any] = {}  # path -> llama.Llama instance
        self._lock = threading.Lock()
        self._active_model: Optional[str] = None

    def _llama_available(self) -> bool:
        try:
            import llama_cpp  # noqa: F401

            return True
        except ImportError:
            return False

    def _load(self, model_path: str) -> Any:
        """Load a GGUF model file into memory (cached after first load)."""
        if model_path in self._models:
            return self._models[model_path]

        with self._lock:
            if model_path in self._models:
                return self._models[model_path]

            from llama_cpp import Llama  # type: ignore[import-untyped]

            logger.info("Loading GGUF model: %s", model_path)
            llm = Llama(
                model_path=model_path,
                n_ctx=int(os.environ.get("NOVA_GGUF_CTX", "4096")),
                n_gpu_layers=int(os.environ.get("NOVA_GGUF_GPU_LAYERS", "-1")),
                verbose=False,
                use_mlock=False,
            )
            self._models[model_path] = llm
            self._active_model = model_path
            return llm

    def _resolve_model_path(self, model: str) -> str:
        """Resolve a model ID or path to an absolute file path."""
        # Direct file path
        if os.path.isabs(model) and os.path.isfile(model):
            return model

        # Catalog ID → local cache
        local = get_model_path(model)
        if local and local.exists():
            return str(local)

        # Relative path in the models dir
        candidate = get_models_dir() / model
        if candidate.exists():
            return str(candidate)

        raise FileNotFoundError(
            f"Model not found: {model!r}. "
            f"Download it first via the Model Hub or: nova model download {model}"
        )

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        model_path = self._resolve_model_path(model)
        llm = self._load(model_path)

        chat_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if isinstance(m, dict)
        ]

        response = llm.create_chat_completion(
            messages=chat_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        content = response["choices"][0]["message"]["content"]
        usage = response.get("usage", {})
        return {
            "content": content,
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
        }

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        import asyncio

        model_path = self._resolve_model_path(model)
        llm = self._load(model_path)

        chat_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if isinstance(m, dict)
        ]

        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

        def _run_stream() -> None:
            try:
                for chunk in llm.create_chat_completion(
                    messages=chat_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                ):
                    delta = chunk["choices"][0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        asyncio.run_coroutine_threadsafe(queue.put(token), loop)
            except Exception as exc:
                logger.error("GGUF stream error: %s", exc)
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop)

        thread = threading.Thread(target=_run_stream, daemon=True)
        thread.start()

        while True:
            token = await queue.get()
            if token is None:
                break
            yield token

    def list_models(self) -> List[str]:
        """Return IDs of all locally downloaded GGUF catalog models."""
        return list_installed_gguf_models()

    def health(self) -> bool:
        """Return True if llama-cpp-python is installed and at least one model exists."""
        if not self._llama_available():
            return False
        # Healthy if any catalog model is downloaded, or if a model is already loaded
        return bool(self.list_models()) or bool(self._models)

    def can_serve(self, model: str) -> bool:
        """Return True if the model file is available locally."""
        if not self._llama_available():
            return False
        try:
            self._resolve_model_path(model)
            return True
        except FileNotFoundError:
            return False

    def close(self) -> None:
        with self._lock:
            for llm in self._models.values():
                try:
                    llm.close()
                except Exception:
                    pass
            self._models.clear()


__all__ = [
    "GGUFEngine",
    "GGUF_CATALOG",
    "download_gguf_model",
    "get_model_path",
    "get_models_dir",
    "list_installed_gguf_models",
]

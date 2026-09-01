"""Tests for adapter deployment targets (adapter/ollama/llamacpp)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from nova_ai.learning.training.deploy import (
    DeployReport,
    deploy,
    deploy_adapter_only,
    deploy_llamacpp,
    deploy_ollama,
    ollama_tag,
    sanitize_model_tag,
)


class TestTagHelpers:
    def test_sanitize_colon(self) -> None:
        assert sanitize_model_tag("qwen3:8b") == "qwen3_8b"

    def test_sanitize_slash(self) -> None:
        assert sanitize_model_tag("Qwen/Qwen3-1.7B") == "Qwen_Qwen3-1.7B"

    def test_ollama_tag_default_prefix(self) -> None:
        assert ollama_tag("qwen3:8b") == "nova-tuned-qwen3_8b"

    def test_ollama_tag_custom_prefix(self) -> None:
        assert ollama_tag("llama3:8b", prefix="my") == "my-llama3_8b"


def _adapter_dir(tmp_path: Path, base_model: str = "qwen3:8b") -> Path:
    d = tmp_path / "adapter"
    d.mkdir(exist_ok=True)
    (d / "adapter_meta.json").write_text(
        json.dumps({"base_model": base_model, "pairs": 10})
    )
    return d


class TestAdapterTarget:
    def test_existing_dir_ok(self, tmp_path: Path) -> None:
        d = _adapter_dir(tmp_path)
        result = deploy_adapter_only(d)
        assert result.ok
        assert result.detail == str(d)

    def test_missing_dir_fails(self, tmp_path: Path) -> None:
        result = deploy_adapter_only(tmp_path / "nope")
        assert not result.ok


class TestOllamaTarget:
    def test_writes_modelfile_and_creates(self, tmp_path: Path) -> None:
        d = _adapter_dir(tmp_path)

        fake_run = MagicMock()
        fake_run.returncode = 0
        fake_list = MagicMock()
        fake_list.returncode = 0
        fake_list.stdout = "nova-tuned-qwen3_8b   abc123   4GB   1 hour ago\n"

        with patch(
            "nova_ai.learning.training.deploy.subprocess.run",
            side_effect=[fake_run, fake_list],
        ) as mock_run:
            result = deploy_ollama(d)

        assert result.ok
        assert result.detail == "nova-tuned-qwen3_8b"

        modelfile = d / "Modelfile"
        assert modelfile.exists()
        content = modelfile.read_text(encoding="utf-8")
        assert "FROM qwen3:8b" in content
        assert "ADAPTER" in content

        # First call: ollama create; second: ollama list
        create_cmd = mock_run.call_args_list[0][0][0]
        assert create_cmd[:3] == ["ollama", "create", "nova-tuned-qwen3_8b"]

    def test_ollama_missing_fails_gracefully(self, tmp_path: Path) -> None:
        d = _adapter_dir(tmp_path)
        with patch(
            "nova_ai.learning.training.deploy.subprocess.run",
            side_effect=FileNotFoundError("ollama not found"),
        ):
            result = deploy_ollama(d)
        assert not result.ok
        assert "not found" in result.detail

    def test_create_failure_returns_error(self, tmp_path: Path) -> None:
        d = _adapter_dir(tmp_path)
        fake_fail = MagicMock()
        fake_fail.returncode = 1
        fake_fail.stderr = "model not found locally"
        with patch(
            "nova_ai.learning.training.deploy.subprocess.run",
            return_value=fake_fail,
        ):
            result = deploy_ollama(d)
        assert not result.ok
        assert "ollama create failed" in result.detail


class TestLlamacppTarget:
    def test_no_torch_fails_cleanly(self, tmp_path: Path) -> None:
        d = _adapter_dir(tmp_path)
        with patch("nova_ai.learning.training.lora.HAS_TORCH", False):
            result = deploy_llamacpp(d)
        assert not result.ok
        assert "torch" in result.detail

    def test_no_gguf_script_returns_merged_dir(self, tmp_path: Path) -> None:
        d = _adapter_dir(tmp_path)
        merged_root = tmp_path / "merged"

        fake_model = MagicMock()
        fake_peft_model = MagicMock()
        fake_peft_model.merge_and_unload.return_value = fake_model

        # peft may not be installed in this env — patch the module-level
        # import target through sys.modules so _merge_adapter resolves it.
        from types import SimpleNamespace

        fake_peft_mod = SimpleNamespace(
            PeftModel=SimpleNamespace(from_pretrained=lambda *a, **k: fake_peft_model)
        )
        fake_transformers = SimpleNamespace(
            AutoModelForCausalLM=SimpleNamespace(
                from_pretrained=lambda *a, **k: MagicMock()
            ),
            AutoTokenizer=SimpleNamespace(
                from_pretrained=lambda *a, **k: MagicMock()
            ),
        )
        fake_torch = SimpleNamespace(bfloat16="bfloat16")

        with (
            patch("nova_ai.learning.training.lora.HAS_TORCH", True),
            patch.dict(
                "sys.modules",
                {
                    "peft": fake_peft_mod,
                    "transformers": fake_transformers,
                    "torch": fake_torch,
                },
            ),
            patch(
                "nova_ai.learning.training.deploy._default_merged_root",
                return_value=merged_root,
            ),
        ):
            result = deploy_llamacpp(d)

        assert result.ok
        assert str(merged_root) in result.detail
        # merged dir contains the saved model
        assert (merged_root / "qwen3_8b").exists()


class TestDispatch:
    def test_unknown_target_reported(self, tmp_path: Path) -> None:
        d = _adapter_dir(tmp_path)
        report = deploy(d, targets=["bogus"])
        assert len(report.results) == 1
        assert not report.results[0].ok
        assert "unknown target" in report.results[0].detail

    def test_failure_isolation(self, tmp_path: Path) -> None:
        """One failing target doesn't stop the others."""
        d = _adapter_dir(tmp_path)
        report = deploy(
            d,
            targets=["adapter", "ollama"],
        )
        # adapter target always succeeds; ollama may fail here (no binary)
        assert report.results[0].ok
        assert report.ok  # at least one target succeeded

    def test_report_to_list(self, tmp_path: Path) -> None:
        d = _adapter_dir(tmp_path)
        report = deploy(d, targets=["adapter"])
        serialized = report.to_list()
        assert serialized == [
            {"target": "adapter", "ok": True, "detail": str(d)}
        ]

    def test_empty_report_not_ok(self) -> None:
        assert not DeployReport().ok

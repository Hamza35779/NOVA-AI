"""Tests for the Fleet Oracle: report building, git push/pull, oracle
aggregation, CLI, and config wiring."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

from nova_ai.cli import cli
from nova_ai.core.config import (
    FleetConfig,
    LearningConfig,
    NovaConfig,
    load_config,
)
from nova_ai.core.types import TelemetryRecord
from nova_ai.learning.fleet.oracle import query_fleet, vram_bucket
from nova_ai.learning.fleet.push import FleetPushError, load_reports, push_report
from nova_ai.learning.fleet.report import SCHEMA_VERSION, build_report
from nova_ai.telemetry.aggregator import ModelStats
from nova_ai.telemetry.store import TelemetryStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(tmp_path: Path, *, fleet: FleetConfig | None = None) -> NovaConfig:
    cfg = NovaConfig()
    cfg.learning = LearningConfig(
        fleet=fleet or FleetConfig(min_calls_per_model=5)
    )
    cfg.telemetry.db_path = str(tmp_path / "telemetry.db")
    cfg.hardware.platform = "windows"
    cfg.hardware.cpu_count = 8
    cfg.hardware.ram_gb = 32.0
    return cfg


def _seed_telemetry(db_path: Path, models: list[dict]) -> None:
    """Insert per-model telemetry records with distinct model_ids."""
    store = TelemetryStore(db_path)
    ts = time.time()  # build_report filters on a since-window in epoch seconds
    for spec in models:
        for _ in range(spec.get("calls", 10)):
            store.record(
                TelemetryRecord(
                    timestamp=ts,
                    model_id=spec["model_id"],
                    engine=spec.get("engine", "ollama"),
                    prompt_tokens=100,
                    completion_tokens=200,
                    total_tokens=300,
                    latency_seconds=spec.get("latency", 2.0),
                    ttft=spec.get("ttft", 0.1),
                    throughput_tok_per_sec=spec.get("throughput", 30.0),
                    tokens_per_joule=spec.get("tpj", 5.0),
                )
            )
    store.close()


class _FakeStats(ModelStats):
    """ModelStats already has the right shape — this is just an alias."""


def _stats(**kw) -> ModelStats:
    defaults = dict(
        model_id="m",
        call_count=10,
        total_tokens=3000,
        avg_latency=2.0,
        avg_ttft=0.1,
        avg_throughput_tok_per_sec=30.0,
        avg_tokens_per_joule=5.0,
    )
    defaults.update(kw)
    return ModelStats(**defaults)


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------


class TestBuildReport:
    def test_shape_and_fixed_fields(self, tmp_path: Path) -> None:
        _seed_telemetry(
            tmp_path / "telemetry.db",
            [{"model_id": "qwen3.5:9b", "calls": 12}],
        )
        report = build_report(config_obj=_cfg(tmp_path))
        assert report["schema_version"] == SCHEMA_VERSION
        assert set(report) == {
            "schema_version",
            "report_id",
            "generated_at",
            "window_days",
            "hardware",
            "models",
        }
        assert set(report["hardware"]) == {
            "platform",
            "cpu_count",
            "ram_gb",
            "gpu",
        }
        m = report["models"][0]
        assert set(m) == {
            "model_id",
            "engine",
            "call_count",
            "avg_latency_s",
            "avg_ttft_s",
            "avg_throughput_tok_per_sec",
            "avg_tokens_per_joule",
            "total_tokens",
        }

    def test_no_prompt_or_content_fields(self, tmp_path: Path) -> None:
        _seed_telemetry(
            tmp_path / "telemetry.db",
            [{"model_id": "qwen3.5:9b", "calls": 12}],
        )
        blob = json.dumps(build_report(config_obj=_cfg(tmp_path)))
        for forbidden in ("prompt", "content", "query", "path", "user",
                          "trace", "message", "answer", "response"):
            assert forbidden not in blob, f"leaked field token: {forbidden}"

    def test_k_anonymity_filter(self, tmp_path: Path) -> None:
        _seed_telemetry(
            tmp_path / "telemetry.db",
            [
                {"model_id": "popular", "calls": 12},
                {"model_id": "rare", "calls": 2},
            ],
        )
        report = build_report(config_obj=_cfg(tmp_path))
        ids = [m["model_id"] for m in report["models"]]
        assert "popular" in ids
        assert "rare" not in ids

    def test_override_min_calls(self, tmp_path: Path) -> None:
        _seed_telemetry(tmp_path / "telemetry.db", [{"model_id": "m", "calls": 3}])
        report = build_report(config_obj=_cfg(tmp_path), min_calls_per_model=2)
        assert [m["model_id"] for m in report["models"]] == ["m"]
        empty = build_report(config_obj=_cfg(tmp_path), min_calls_per_model=10)
        assert empty["models"] == []

    def test_report_id_is_stable_hash(self, tmp_path: Path) -> None:
        _seed_telemetry(tmp_path / "telemetry.db", [{"model_id": "m"}])
        r1 = build_report(config_obj=_cfg(tmp_path))
        r2 = build_report(config_obj=_cfg(tmp_path))
        assert r1["report_id"] == r2["report_id"]
        assert len(r1["report_id"]) == 16

    def test_report_id_changes_with_hardware(self, tmp_path: Path) -> None:
        _seed_telemetry(tmp_path / "telemetry.db", [{"model_id": "m"}])
        r1 = build_report(config_obj=_cfg(tmp_path))
        other = _cfg(tmp_path)
        other.hardware.ram_gb = 64.0
        r2 = build_report(config_obj=other)
        assert r1["report_id"] != r2["report_id"]

    def test_report_id_is_hash_id_of_fingerprint(self, tmp_path: Path) -> None:
        from nova_ai.analytics.redaction import hash_id

        cfg = _cfg(tmp_path)
        report = build_report(config_obj=cfg)
        expected = hash_id("windows|8|32.0")
        assert report["report_id"] == expected

    def test_gpu_fields_only(self, tmp_path: Path) -> None:
        from nova_ai.core.config import GpuInfo

        cfg = _cfg(tmp_path)
        cfg.hardware.gpu = GpuInfo(
            vendor="nvidia", name="RTX 4090", vram_gb=24.0,
            compute_capability="8.9", count=1,
        )
        report = build_report(config_obj=cfg)
        assert report["hardware"]["gpu"] == {
            "vendor": "nvidia",
            "name": "RTX 4090",
            "vram_gb": 24.0,
        }
        assert "compute_capability" not in report["hardware"]["gpu"]

    def test_since_window_filters_telemetry(self, tmp_path: Path) -> None:
        db = tmp_path / "telemetry.db"
        store = TelemetryStore(db)
        store.record(
            TelemetryRecord(timestamp=1_000_000.0, model_id="old-model")
        )
        store.close()
        report = build_report(config_obj=_cfg(tmp_path), since_days=30)
        assert report["models"] == []
    def test_telemetry_db_missing(self, tmp_path: Path) -> None:
        # A nonexistent db path: sqlite3.connect creates the file but the
        # telemetry table does not exist — build_report must not crash.
        report = build_report(config_obj=_cfg(tmp_path))
        assert report["models"] == []


# ---------------------------------------------------------------------------
# push / pull / load
# ---------------------------------------------------------------------------


def _git(*args: str, cwd: Path | None = None) -> None:
    cmd = ["git", *args]
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def remote_repo(tmp_path: Path) -> Path:
    """A bare repo acting as the dataset remote."""
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        check=True,
        capture_output=True,
    )
    return bare


def _sample_report(report_id: str = "abcdef1234567890") -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "report_id": report_id,
        "generated_at": "2026-09-01T00:00:00Z",
        "window_days": 30,
        "hardware": {
            "platform": "windows",
            "cpu_count": 8,
            "ram_gb": 32.0,
            "gpu": {"vendor": "nvidia", "name": "RTX 4090", "vram_gb": 24.0},
        },
        "models": [
            {
                "model_id": "qwen3.5:9b",
                "engine": "ollama",
                "call_count": 12,
                "avg_latency_s": 2.0,
                "avg_ttft_s": 0.1,
                "avg_throughput_tok_per_sec": 30.0,
                "avg_tokens_per_joule": 5.0,
                "total_tokens": 3600,
            }
        ],
    }


class TestPushPull:
    def test_push_creates_report_file(self, tmp_path: Path, remote_repo: Path) -> None:
        cache = tmp_path / "cache"
        out = push_report(
            _sample_report(), str(remote_repo), cache_dir=cache
        )
        assert out.exists()
        assert out.parent.name == "reports"
        assert out.name == "abcdef1234567890.json"
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["report_id"] == "abcdef1234567890"

    def test_push_lands_on_remote(self, tmp_path: Path, remote_repo: Path) -> None:
        cache = tmp_path / "cache"
        push_report(_sample_report(), str(remote_repo), cache_dir=cache)
        # A fresh clone must contain the report
        fresh = tmp_path / "fresh"
        _git("clone", str(remote_repo), str(fresh))
        assert (fresh / "reports" / "abcdef1234567890.json").exists()

    def test_push_second_report(self, tmp_path: Path, remote_repo: Path) -> None:
        cache = tmp_path / "cache"
        push_report(_sample_report("a" * 16), str(remote_repo), cache_dir=cache)
        push_report(_sample_report("b" * 16), str(remote_repo), cache_dir=cache)
        reports = load_reports(str(remote_repo), cache_dir=tmp_path / "cache2")
        assert {r["report_id"] for r in reports} == {"a" * 16, "b" * 16}

    def test_load_reports_skips_garbage(
        self, tmp_path: Path, remote_repo: Path
    ) -> None:
        cache = tmp_path / "cache"
        push_report(_sample_report(), str(remote_repo), cache_dir=cache)
        # Add a corrupt JSON file directly and push it
        (cache / "reports" / "garbage.json").write_text("not json{", encoding="utf-8")
        _git("add", ".", cwd=cache)
        _git(
            "-c", "user.name=t", "-c", "user.email=t@t", "commit",
            "-m", "garbage", cwd=cache,
        )
        _git("push", "origin", "HEAD", cwd=cache)
        reports = load_reports(str(remote_repo), cache_dir=tmp_path / "cache2")
        assert len(reports) == 1

    def test_push_requires_repo_url(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            push_report(_sample_report(), "", cache_dir=tmp_path / "c")

    def test_push_bad_remote(self, tmp_path: Path) -> None:
        with pytest.raises(FleetPushError):
            push_report(
                _sample_report(),
                str(tmp_path / "does-not-exist.git"),
                cache_dir=tmp_path / "c",
            )

    def test_push_pull_diverged_cache_fails_clean(
        self, tmp_path: Path, remote_repo: Path
    ) -> None:
        """A diverged local cache surfaces FleetPushError, not a git traceback."""
        cache = tmp_path / "cache"
        push_report(_sample_report("c" * 16), str(remote_repo), cache_dir=cache)
        # Move the remote forward behind the cache's back
        other = tmp_path / "other"
        _git("clone", str(remote_repo), str(other))
        (other / "reports").mkdir(exist_ok=True)
        (other / "reports" / ("d" * 16 + ".json")).write_text("{}", encoding="utf-8")
        _git("add", ".", cwd=other)
        _git(
            "-c", "user.name=t", "-c", "user.email=t@t", "commit",
            "-m", "other machine", cwd=other,
        )
        _git("push", "origin", "HEAD", cwd=other)
        # Make the cache diverge (local commit the remote doesn't have)
        (cache / "reports" / ("e" * 16 + ".json")).write_text("{}", encoding="utf-8")
        _git("add", ".", cwd=cache)
        _git(
            "-c", "user.name=t", "-c", "user.email=t@t", "commit",
            "-m", "local diverge", cwd=cache,
        )
        with pytest.raises(FleetPushError, match="git pull failed"):
            push_report(_sample_report("f" * 16), str(remote_repo), cache_dir=cache)


# ---------------------------------------------------------------------------
# oracle (query_fleet)
# ---------------------------------------------------------------------------


def _report(rid: str, vram: float, models: list[dict]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "report_id": rid,
        "generated_at": "2026-09-01T00:00:00Z",
        "hardware": {
            "platform": "windows",
            "cpu_count": 8,
            "ram_gb": 32.0,
            "gpu": {"vendor": "nvidia", "name": "fake", "vram_gb": vram},
        },
        "models": models,
    }


class TestVramBucket:
    def test_edges(self) -> None:
        assert vram_bucket(8.0) == "<=8GB"
        assert vram_bucket(8.1) == "9-16GB"
        assert vram_bucket(16.0) == "9-16GB"
        assert vram_bucket(24.0) == "17-24GB"
        assert vram_bucket(48.0) == "25-48GB"
        assert vram_bucket(80.0) == ">48GB"
        assert vram_bucket(0.0) == "<=8GB"


class TestQueryFleet:
    def test_winner_by_latency_in_bucket(self) -> None:
        reports = [
            _report("r1", 24.0, [
                {"model_id": "slow", "call_count": 10, "avg_latency_s": 3.0,
                 "avg_throughput_tok_per_sec": 20.0, "avg_tokens_per_joule": 4.0},
                {"model_id": "fast", "call_count": 10, "avg_latency_s": 1.0,
                 "avg_throughput_tok_per_sec": 40.0, "avg_tokens_per_joule": 6.0},
            ]),
        ]
        answer = query_fleet("best fast model on a 4090?", reports)
        assert answer.intent == "latency"
        assert answer.bucket_label == "17-24GB"  # 4090 -> 24 GB
        assert "fast" in answer.headline
        assert answer.buckets[0]["winners"]["avg_latency_s"]["model"] == "fast"

    def test_throughput_intent(self) -> None:
        reports = [
            _report("r1", 24.0, [
                {"model_id": "a", "call_count": 10, "avg_latency_s": 2.0,
                 "avg_throughput_tok_per_sec": 20.0, "avg_tokens_per_joule": 4.0},
                {"model_id": "b", "call_count": 10, "avg_latency_s": 2.5,
                 "avg_throughput_tok_per_sec": 50.0, "avg_tokens_per_joule": 4.0},
            ]),
        ]
        answer = query_fleet("which model has the best throughput?", reports)
        assert answer.intent == "throughput"
        assert answer.buckets[0]["winners"]["avg_throughput_tok_per_sec"]["model"] == "b"

    def test_energy_intent_prefers_tokens_per_joule(self) -> None:
        reports = [
            _report("r1", 8.0, [
                {"model_id": "a", "call_count": 10, "avg_latency_s": 2.0,
                 "avg_throughput_tok_per_sec": 20.0, "avg_tokens_per_joule": 3.0},
                {"model_id": "b", "call_count": 10, "avg_latency_s": 3.0,
                 "avg_throughput_tok_per_sec": 15.0, "avg_tokens_per_joule": 9.0},
            ]),
        ]
        answer = query_fleet("most energy efficient model?", reports)
        assert answer.intent == "energy"
        assert answer.buckets[0]["winners"]["avg_tokens_per_joule"]["model"] == "b"

    def test_no_gpu_reports_landed_in_lowest_bucket(self) -> None:
        reports = [
            {
                "schema_version": SCHEMA_VERSION,
                "report_id": "r1",
                "generated_at": "2026-09-01T00:00:00Z",
                "hardware": {"platform": "linux", "cpu_count": 4,
                             "ram_gb": 16.0, "gpu": None},
                "models": [{"model_id": "m", "call_count": 5,
                            "avg_latency_s": 2.0,
                            "avg_throughput_tok_per_sec": 20.0,
                            "avg_tokens_per_joule": 4.0}],
            },
        ]
        answer = query_fleet("best model?", reports)
        assert answer.buckets[0]["label"] == "<=8GB"

    def test_weighted_averages_across_machines(self) -> None:
        reports = [
            _report("r1", 24.0, [
                {"model_id": "m", "call_count": 10, "avg_latency_s": 1.0,
                 "avg_throughput_tok_per_sec": 10.0, "avg_tokens_per_joule": 1.0},
            ]),
            _report("r2", 24.0, [
                {"model_id": "m", "call_count": 30, "avg_latency_s": 3.0,
                 "avg_throughput_tok_per_sec": 50.0, "avg_tokens_per_joule": 5.0},
            ]),
        ]
        answer = query_fleet("fast model on a 4090?", reports)
        row = answer.buckets[0]["rows"][0]
        # call-weighted: (1*10 + 3*30)/40 = 2.5
        assert row["avg_latency_s"] == pytest.approx(2.5)
        assert row["machines"] == 2

    def test_dedupes_reports_by_id_keeping_newest(self) -> None:
        older = _report("r1", 24.0, [
            {"model_id": "m", "call_count": 5, "avg_latency_s": 1.0,
             "avg_throughput_tok_per_sec": 10.0, "avg_tokens_per_joule": 1.0},
        ])
        newer = dict(older)
        newer["generated_at"] = "2026-09-02T00:00:00Z"
        newer["models"] = [
            {"model_id": "m", "call_count": 7, "avg_latency_s": 2.0,
             "avg_throughput_tok_per_sec": 10.0, "avg_tokens_per_joule": 1.0},
        ]
        answer = query_fleet("best model?", [older, newer])
        assert answer.buckets[0]["rows"][0]["call_count"] == 7

    def test_no_data_headline(self) -> None:
        answer = query_fleet("best model?", [])
        assert answer.headline == "No fleet data matches that question yet."
        assert answer.buckets == []

    def test_intent_code_maps_to_throughput_metric(self) -> None:
        reports = [
            _report("r1", 24.0, [
                {"model_id": "a", "call_count": 10, "avg_latency_s": 1.0,
                 "avg_throughput_tok_per_sec": 20.0, "avg_tokens_per_joule": 4.0},
                {"model_id": "b", "call_count": 10, "avg_latency_s": 5.0,
                 "avg_throughput_tok_per_sec": 80.0, "avg_tokens_per_joule": 4.0},
            ]),
        ]
        answer = query_fleet("best model for code on a 4090?", reports)
        assert answer.intent == "code"
        # code intent ranks by throughput
        assert answer.buckets[0]["winners"]["avg_throughput_tok_per_sec"]["model"] == "b"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _patch_cli(tmp_path: Path, *, share: bool = False, repo: str = ""):
    cfg = _cfg(tmp_path, fleet=FleetConfig(
        share_reports=share,
        dataset_repo=repo,
        min_calls_per_model=5,
        cache_dir=str(tmp_path / "cache"),
    ))
    return [mock.patch("nova_ai.cli.oracle_cmd.load_config", return_value=cfg)]


class _Invoke:
    def __init__(self, tmp_path: Path, **kw) -> None:
        self._patches = _patch_cli(tmp_path, **kw)

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()
        return False


class TestOracleCli:
    def test_registered_in_top_level_cli(self) -> None:
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "oracle" in result.output

    def test_export_previews_report(self, tmp_path: Path) -> None:
        _seed_telemetry(
            tmp_path / "telemetry.db", [{"model_id": "qwen3.5:9b", "calls": 12}]
        )
        with _Invoke(tmp_path):
            result = CliRunner().invoke(cli, ["oracle", "export"])
        assert result.exit_code == 0, result.output
        assert "qwen3.5:9b" in result.output

    def test_export_to_file(self, tmp_path: Path) -> None:
        _seed_telemetry(tmp_path / "telemetry.db", [{"model_id": "m", "calls": 9}])
        out = tmp_path / "report.json"
        with _Invoke(tmp_path):
            result = CliRunner().invoke(cli, ["oracle", "export", "-o", str(out)])
        assert result.exit_code == 0, result.output
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["models"][0]["model_id"] == "m"

    def test_push_refuses_when_share_off(self, tmp_path: Path) -> None:
        with _Invoke(tmp_path, share=False):
            result = CliRunner().invoke(cli, ["oracle", "push"])
        assert result.exit_code == 1
        assert "share_reports" in result.output

    def test_push_refuses_without_repo(self, tmp_path: Path) -> None:
        _seed_telemetry(tmp_path / "telemetry.db", [{"model_id": "m", "calls": 9}])
        with _Invoke(tmp_path, share=True, repo=""):
            result = CliRunner().invoke(cli, ["oracle", "push"])
        assert result.exit_code == 1
        assert "dataset_repo" in result.output

    def test_push_end_to_end_local_repo(
        self, tmp_path: Path, remote_repo: Path
    ) -> None:
        _seed_telemetry(tmp_path / "telemetry.db", [{"model_id": "m", "calls": 9}])
        with _Invoke(tmp_path, share=True, repo=str(remote_repo)):
            result = CliRunner().invoke(cli, ["oracle", "push"])
        assert result.exit_code == 0, result.output
        reports = load_reports(str(remote_repo), cache_dir=tmp_path / "verify")
        assert len(reports) == 1

    def test_ask_requires_repo(self, tmp_path: Path) -> None:
        with _Invoke(tmp_path):
            result = CliRunner().invoke(cli, ["oracle", "ask", "best model?"])
        assert result.exit_code == 1

    def test_ask_answers_from_dataset(
        self, tmp_path: Path, remote_repo: Path
    ) -> None:
        # Seed the remote with one report
        push_report(_sample_report(), str(remote_repo), cache_dir=tmp_path / "seed")
        with _Invoke(tmp_path, repo=str(remote_repo)):
            result = CliRunner().invoke(
                cli, ["oracle", "ask", "best model for code on a 4090?"]
            )
        assert result.exit_code == 0, result.output
        assert "qwen3.5:9b" in result.output

    def test_status(self, tmp_path: Path) -> None:
        with _Invoke(tmp_path, share=True, repo="https://example.com/fleet.git"):
            result = CliRunner().invoke(cli, ["oracle", "status"])
        assert result.exit_code == 0, result.output
        assert "https://example.com/fleet.git" in result.output

    def test_status_empty_cache(self, tmp_path: Path) -> None:
        with _Invoke(tmp_path):
            result = CliRunner().invoke(cli, ["oracle", "status"])
        assert result.exit_code == 0
        assert "0 report(s)" in result.output


# ---------------------------------------------------------------------------
# Config wiring
# ---------------------------------------------------------------------------


class TestFleetConfig:
    def test_defaults_opt_out(self) -> None:
        cfg = FleetConfig()
        assert cfg.share_reports is False
        assert cfg.dataset_repo == ""
        assert cfg.min_calls_per_model == 5

    def test_learning_has_fleet(self) -> None:
        learning = LearningConfig()
        assert learning.fleet.share_reports is False

    def test_toml_load_maps_fleet_section(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            "[learning.fleet]\n"
            'share_reports = true\n'
            'dataset_repo = "https://example.com/fleet.git"\n'
            "min_calls_per_model = 3\n",
            encoding="utf-8",
        )
        with mock.patch(
            "nova_ai.core.config.DEFAULT_CONFIG_DIR", str(tmp_path)
        ):
            cfg = load_config(config_file)
        assert cfg.learning.fleet.share_reports is True
        assert cfg.learning.fleet.dataset_repo == "https://example.com/fleet.git"
        assert cfg.learning.fleet.min_calls_per_model == 3

    def test_default_toml_mentions_fleet(self) -> None:
        from nova_ai.core.config import generate_default_toml

        toml = generate_default_toml(_cfg(Path(".")) .hardware, "ollama")
        assert "[learning.fleet]" in toml
        assert "share_reports" in toml


# ---------------------------------------------------------------------------
# build_report from ModelStats directly (aggregation-path unit test)
# ---------------------------------------------------------------------------


class TestModelPayload:
    def test_k_filter_via_min_calls(self) -> None:
        from nova_ai.learning.fleet.report import _model_payload

        assert _model_payload(_stats(call_count=4), min_calls=5) is None
        payload = _model_payload(_stats(call_count=5), min_calls=5)
        assert payload is not None
        assert payload["call_count"] == 5

    def test_fields_rounded(self) -> None:
        from nova_ai.learning.fleet.report import _model_payload

        payload = _model_payload(_stats(avg_latency=2.123456), min_calls=1)
        assert payload["avg_latency_s"] == 2.123

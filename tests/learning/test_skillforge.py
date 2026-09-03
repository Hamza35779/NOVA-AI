"""Tests for the Skill Foundry: miner, synthesizer, gauntlet, adoption,
pipeline, store, CLI, and scheduler dispatch."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from nova_ai.core.config import SkillForgeConfig
from nova_ai.core.types import StepType, Trace, TraceStep
from nova_ai.learning.skillforge.miner import PatternMiner
from nova_ai.learning.skillforge.store import SkillForgeRunStore
from nova_ai.traces.store import TraceStore

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

TOOL_SEQ = ("web_search", "think")


class _StubTool:
    """Minimal BaseTool stand-in registered so the static gate sees it."""

    def __init__(self, name: str, description: str = "") -> None:
        self._name = name
        self._description = description

    @property
    def spec(self):
        from nova_ai.tools._stubs import ToolSpec

        return ToolSpec(name=self._name, description=self._description)

    def execute(self, **params):
        from nova_ai.core.types import ToolResult

        return ToolResult(tool_name=self._name, content="ok", success=True)


@pytest.fixture(autouse=True)
def _register_stub_tools(monkeypatch):
    """Register the tools the forged skills reference.

    The shared conftest clears ToolRegistry around every test; the forge's
    static gate and synthesizer prompt both read the registry, so these
    stubs stand in for the real web_search/think tools.
    """
    from nova_ai.core.registry import ToolRegistry

    for name in ("web_search", "think"):
        try:
            ToolRegistry.register_value(name, _StubTool(name))
        except ValueError:
            pass
    yield


def _tool_step(tool: str, arguments: Any, success: bool = True) -> TraceStep:
    return TraceStep(
        step_type=StepType.TOOL_CALL,
        timestamp=1_000.0,
        input={"tool": tool, "arguments": arguments},
        output={"success": success, "result": "ok"},
    )


def _trace(query: str, steps: list[TraceStep], feedback: float = 0.9) -> Trace:
    return Trace(query=query, agent="simple", steps=steps, feedback=feedback)


@pytest.fixture()
def trace_store(tmp_path):
    store = TraceStore(tmp_path / "traces.db")
    for i in range(4):
        store.save(
            _trace(
                f"search for thing {i}",
                [
                    _tool_step("web_search", {"query": f"thing {i}"}),
                    _tool_step("think", {"thought": "summarize"}),
                ],
            )
        )
    yield store
    store.close()


@pytest.fixture()
def run_store(tmp_path):
    s = SkillForgeRunStore(tmp_path / "skillforge" / "runs.db")
    yield s
    s.close()


# ---------------------------------------------------------------------------
# PatternMiner
# ---------------------------------------------------------------------------


class TestPatternMiner:
    def test_finds_repeated_sequence(self, trace_store) -> None:
        miner = PatternMiner(trace_store, min_pattern_count=3)
        patterns = miner.mine()
        assert len(patterns) == 1
        assert patterns[0]["sequence"] == ["web_search", "think"]
        assert patterns[0]["count"] == 4
        assert patterns[0]["avg_feedback"] >= 0.7

    def test_below_count_threshold_filtered(self, tmp_path) -> None:
        store = TraceStore(tmp_path / "t.db")
        try:
            store.save(
                _trace(
                    "one off",
                    [_tool_step("a", {}), _tool_step("b", {})],
                )
            )
            miner = PatternMiner(store, min_pattern_count=3)
            assert miner.mine() == []
        finally:
            store.close()

    def test_low_feedback_filtered(self, tmp_path) -> None:
        store = TraceStore(tmp_path / "t.db")
        try:
            for i in range(3):
                store.save(
                    _trace(
                        f"bad result {i}",
                        [_tool_step("a", {}), _tool_step("b", {})],
                        feedback=0.2,
                    )
                )
            miner = PatternMiner(store, min_pattern_count=3, min_feedback=0.7)
            assert miner.mine() == []
        finally:
            store.close()

    def test_no_feedback_still_mined(self, tmp_path) -> None:
        store = TraceStore(tmp_path / "t.db")
        try:
            for i in range(3):
                t = _trace(f"q {i}", [_tool_step("a", {}), _tool_step("b", {})])
                t.feedback = None
                store.save(t)
            miner = PatternMiner(store, min_pattern_count=3)
            assert len(miner.mine()) == 1
        finally:
            store.close()

    def test_single_tool_traces_ignored(self, tmp_path) -> None:
        store = TraceStore(tmp_path / "t.db")
        try:
            for i in range(4):
                store.save(_trace(f"q {i}", [_tool_step("only_tool", {})]))
            miner = PatternMiner(store, min_pattern_count=3)
            assert miner.mine() == []
        finally:
            store.close()

    def test_examples_carry_arguments(self, trace_store) -> None:
        miner = PatternMiner(trace_store, min_pattern_count=3)
        patterns = miner.mine()
        ex = patterns[0]["examples"][0]
        assert ex["arguments"] == {"query": "thing 0"}
        assert patterns[0]["example_trace_ids"]


# ---------------------------------------------------------------------------
# SkillSynthesizer
# ---------------------------------------------------------------------------

GOOD_SKILL_TOML = """\
[skill]
name = "search-and-summarize"
version = "0.1.0"
description = "Search the web and summarize the results."
author = "nova-skillforge"

[[skill.steps]]
tool_name = "web_search"
arguments_template = "{\\"query\\": \\"{query}\\"}"
output_key = "search_results"

[[skill.steps]]
tool_name = "think"
arguments_template = "{\\"thought\\": \\"Summarize: {search_results}\\"}"
output_key = "summary"
"""


class FakeSynthLLM:
    def __init__(self, response: str = GOOD_SKILL_TOML) -> None:
        self.response = response
        self.prompts: list[str] = []
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        return self.response


def _candidate() -> dict[str, Any]:
    return {
        "sequence": ["web_search", "think"],
        "count": 4,
        "avg_feedback": 0.9,
        "successes": 4,
        "example_trace_ids": ["t1", "t2", "t3"],
        "examples": [
            {
                "query": "search for thing 0",
                "arguments": {"query": "thing 0"},
                "calls": [
                    {"tool": "web_search", "arguments": {"query": "thing 0"},
                     "success": True, "result": "res"},
                    {"tool": "think", "arguments": {"thought": "x"},
                     "success": True, "result": "ok"},
                ],
            }
        ],
    }


class TestSkillSynthesizer:
    def test_happy_path_parses_manifest(self) -> None:
        from nova_ai.learning.skillforge.synthesizer import SkillSynthesizer

        llm = FakeSynthLLM()
        manifest = SkillSynthesizer(llm).synthesize(_candidate())
        assert manifest.name == "search-and-summarize"
        assert [s.tool_name for s in manifest.steps] == ["web_search", "think"]
        assert llm.calls == 1

    def test_prompt_contains_tool_catalog(self) -> None:
        from nova_ai.learning.skillforge.synthesizer import SkillSynthesizer

        llm = FakeSynthLLM()
        SkillSynthesizer(llm).synthesize(_candidate())
        # The catalog lists registered tools; prompt must mention the
        # sequence and the observed arguments.
        assert "web_search" in llm.prompts[0]
        assert "thing 0" in llm.prompts[0]

    def test_fenced_toml_tolerated(self) -> None:
        from nova_ai.learning.skillforge.synthesizer import SkillSynthesizer

        llm = FakeSynthLLM("```toml\n" + GOOD_SKILL_TOML + "\n```")
        manifest = SkillSynthesizer(llm).synthesize(_candidate())
        assert manifest.name == "search-and-summarize"

    def test_wrong_sequence_rejected_and_retried(self) -> None:
        from nova_ai.learning.skillforge.synthesizer import SkillSynthesizer

        llm = FakeSynthLLM()
        # Manifest reverses the observed order — must not be accepted.
        llm.response = GOOD_SKILL_TOML.replace(
            'tool_name = "web_search"', 'tool_name = "think"', 1
        ).replace('tool_name = "think"\narguments_template = "{\\"thought\\": \\"Summarize: {search_results}\\"}"',
                  'tool_name = "web_search"\narguments_template = "{\\"query\\": \\"{query}\\"}"')
        with pytest.raises(ValueError, match="sequence"):
            SkillSynthesizer(llm, max_retries=0).synthesize(_candidate())

    def test_retry_recovers_from_bad_output(self) -> None:
        from nova_ai.learning.skillforge.synthesizer import SkillSynthesizer

        class RetryLLM:
            def __init__(self) -> None:
                self.calls = 0

            def generate(self, prompt: str) -> str:
                self.calls += 1
                if self.calls == 1:
                    return "not toml at all [["
                return GOOD_SKILL_TOML

        llm = RetryLLM()
        manifest = SkillSynthesizer(llm).synthesize(_candidate())
        assert manifest.name == "search-and-summarize"
        assert llm.calls == 2

    def test_llm_failure_raises_valueerror(self) -> None:
        from nova_ai.learning.skillforge.synthesizer import SkillSynthesizer

        class Boom:
            def generate(self, prompt: str) -> str:
                raise RuntimeError("ollama down")

        with pytest.raises(ValueError, match="synthesis LLM failed"):
            SkillSynthesizer(Boom()).synthesize(_candidate())

    def test_sanitize_name(self) -> None:
        from nova_ai.learning.skillforge.synthesizer import sanitize_name

        assert sanitize_name("My Cool Skill!") == "my-cool-skill"
        assert sanitize_name("") == "forged-skill"
        assert sanitize_name("--weird--name--") == "weird-name"


# ---------------------------------------------------------------------------
# Gauntlet
# ---------------------------------------------------------------------------


class FakeToolExecutor:
    """Records executed calls; every call succeeds."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, tool_call: Any) -> Any:
        from nova_ai.core.types import ToolResult

        self.calls.append(tool_call.name)
        return ToolResult(tool_name=tool_call.name, content="done", success=True)


class TestGauntlet:
    def _config(self, **overrides):
        defaults = {"sandbox_timeout": 5.0}
        defaults.update(overrides)
        return SkillForgeConfig(**defaults)

    def _manifest(self):
        from nova_ai.learning.skillforge.synthesizer import SkillSynthesizer

        return SkillSynthesizer(FakeSynthLLM()).synthesize(_candidate())

    def test_passes_all_gates(self) -> None:
        from nova_ai.learning.skillforge.gauntlet import run_gauntlet

        report = run_gauntlet(
            self._manifest(),
            _candidate(),
            tool_executor=FakeToolExecutor(),
            config=self._config(),
            judge=None,
        )
        assert report["passed"] is True
        names = [g["name"] for g in report["gates"]]
        assert names == ["static", "replay"]
        assert all(g["passed"] for g in report["gates"])

    def test_unknown_tool_fails_static(self) -> None:
        from nova_ai.learning.skillforge.gauntlet import run_gauntlet

        manifest = self._manifest()
        manifest.steps[0].tool_name = "not_a_real_tool"
        report = run_gauntlet(
            manifest,
            _candidate(),
            tool_executor=FakeToolExecutor(),
            config=self._config(),
        )
        static = report["gates"][0]
        assert static["name"] == "static"
        assert static["passed"] is False
        assert report["passed"] is False
        # Short-circuit: replay never ran.
        assert [g["name"] for g in report["gates"]] == ["static"]

    def test_dangerous_capability_fails_static(self) -> None:
        from nova_ai.learning.skillforge.gauntlet import run_gauntlet

        manifest = self._manifest()
        manifest.required_capabilities = ["shell:execute"]
        report = run_gauntlet(
            manifest,
            _candidate(),
            tool_executor=FakeToolExecutor(),
            config=self._config(),
        )
        assert report["gates"][0]["passed"] is False
        assert "shell:execute" in report["gates"][0]["detail"]

    def test_replay_failure_recorded(self) -> None:
        from nova_ai.core.types import ToolResult
        from nova_ai.learning.skillforge.gauntlet import run_gauntlet

        class FailingExecutor:
            def execute(self, tool_call: Any) -> Any:
                return ToolResult(
                    tool_name=tool_call.name, content="boom", success=False
                )

        report = run_gauntlet(
            self._manifest(),
            _candidate(),
            tool_executor=FailingExecutor(),
            config=self._config(),
        )
        replay = report["gates"][1]
        assert replay["name"] == "replay"
        assert replay["passed"] is False

    def test_judge_gate_runs_and_passes(self) -> None:
        from nova_ai.learning.skillforge.gauntlet import run_gauntlet

        judge = FakeSynthLLM("YES\nThe output matches the task.")
        report = run_gauntlet(
            self._manifest(),
            _candidate(),
            tool_executor=FakeToolExecutor(),
            config=self._config(),
            judge=judge,
        )
        names = [g["name"] for g in report["gates"]]
        assert names == ["static", "replay", "judge"]
        assert report["passed"] is True

    def test_judge_no_rejects(self) -> None:
        from nova_ai.learning.skillforge.gauntlet import run_gauntlet

        judge = FakeSynthLLM("NO\nThe output is off topic.")
        report = run_gauntlet(
            self._manifest(),
            _candidate(),
            tool_executor=FakeToolExecutor(),
            config=self._config(),
            judge=judge,
        )
        assert report["passed"] is False
        judge_gate = report["gates"][-1]
        assert judge_gate["name"] == "judge"
        assert judge_gate["passed"] is False

    def test_judge_failure_fails_gate(self) -> None:
        from nova_ai.learning.skillforge.gauntlet import run_gauntlet

        class BoomJudge:
            def generate(self, prompt: str) -> str:
                raise RuntimeError("judge down")

        report = run_gauntlet(
            self._manifest(),
            _candidate(),
            tool_executor=FakeToolExecutor(),
            config=self._config(),
            judge=BoomJudge(),
        )
        assert report["passed"] is False


# ---------------------------------------------------------------------------
# Adoption
# ---------------------------------------------------------------------------


class TestAdoption:
    def _manifest(self):
        from nova_ai.learning.skillforge.synthesizer import SkillSynthesizer

        return SkillSynthesizer(FakeSynthLLM()).synthesize(_candidate())

    def test_adopt_writes_skill_toml(self, tmp_path) -> None:
        from nova_ai.learning.skillforge.adoption import adopt_skill

        skills_root = tmp_path / "skills"
        path = adopt_skill(
            self._manifest(),
            run_id="forge_abc",
            gauntlet={"passed": True, "gates": []},
            pattern_count=4,
            skills_root=skills_root,
        )
        assert (path / "skill.toml").exists()
        text = (path / "skill.toml").read_text(encoding="utf-8")
        assert "search-and-summarize" in text
        assert "forge_abc" in text  # provenance

    def test_adopt_refuses_failed_gauntlet(self, tmp_path) -> None:
        from nova_ai.learning.skillforge.adoption import adopt_skill

        with pytest.raises(ValueError, match="gauntlet"):
            adopt_skill(
                self._manifest(),
                run_id="forge_x",
                gauntlet={"passed": False, "gates": []},
                pattern_count=4,
                skills_root=tmp_path,
            )

    def test_discover_finds_adopted_skill(self, tmp_path) -> None:
        from nova_ai.learning.skillforge.adoption import adopt_skill
        from nova_ai.skills.loader import discover_skills

        skills_root = tmp_path / "skills"
        adopt_skill(
            self._manifest(),
            run_id="forge_abc",
            gauntlet={"passed": True, "gates": []},
            pattern_count=4,
            skills_root=skills_root,
        )
        manifests = discover_skills(skills_root)
        assert [m.name for m in manifests] == ["search-and-summarize"]

    def test_revert_removes_skill(self, tmp_path) -> None:
        from nova_ai.learning.skillforge.adoption import adopt_skill, revert_skill

        skills_root = tmp_path / "skills"
        adopt_skill(
            self._manifest(),
            run_id="forge_abc",
            gauntlet={"passed": True, "gates": []},
            pattern_count=4,
            skills_root=skills_root,
        )
        assert revert_skill("search-and-summarize", skills_root=skills_root) is True
        assert revert_skill("search-and-summarize", skills_root=skills_root) is False
        from nova_ai.skills.loader import discover_skills

        assert discover_skills(skills_root) == []


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class TestSkillForgeRunStore:
    def test_start_finish_round_trip(self, run_store) -> None:
        run_store.start_run("forge_1", trigger="manual")
        run_store.finish_run(
            "forge_1",
            status="passed",
            skill_name="my-skill",
            pattern_count=5,
            sequence=["a", "b"],
            gauntlet={"passed": True, "gates": [{"name": "static", "passed": True}]},
        )
        record = run_store.get_run("forge_1")
        assert record["status"] == "passed"
        assert record["skill_name"] == "my-skill"
        assert record["sequence"] == ["a", "b"]
        assert record["gauntlet"]["passed"] is True
        assert record["ended_at"] is not None

    def test_latest_and_list(self, run_store) -> None:
        run_store.start_run("forge_1")
        run_store.start_run("forge_2")
        assert run_store.latest_run()["id"] == "forge_2"
        assert [r["id"] for r in run_store.list_runs(limit=5)] == [
            "forge_2",
            "forge_1",
        ]

    def test_list_candidate_runs_filters_status(self, run_store) -> None:
        for i, status in enumerate(["passed", "failed", "passed"]):
            run_store.start_run(f"forge_{i}")
            run_store.finish_run(
                f"forge_{i}", status=status, skill_name=f"skill-{i}"
            )
        passed = run_store.list_candidate_runs(status="passed")
        assert [r["skill_name"] for r in passed] == ["skill-2", "skill-0"]

    def test_is_running(self, run_store) -> None:
        assert run_store.is_running() is False
        run_store.start_run("forge_1")
        assert run_store.is_running() is True
        run_store.finish_run("forge_1", status="failed", error="x")
        assert run_store.is_running() is False

    def test_failed_round_trip(self, run_store) -> None:
        run_store.start_run("forge_9")
        run_store.finish_run("forge_9", status="synthesis_failed", error="bad toml")
        assert run_store.get_run("forge_9")["error"] == "bad toml"

    def test_threads_share_connection(self, tmp_path) -> None:
        store = SkillForgeRunStore(tmp_path / "runs.db")
        try:
            import threading

            def worker(i: int) -> None:
                store.start_run(f"forge_{i}")
                store.finish_run(f"forge_{i}", status="passed")

            threads = [
                threading.Thread(target=worker, args=(i,)) for i in range(8)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            assert len(store.list_runs(limit=20)) == 8
        finally:
            store.close()


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class TestPipeline:
    def _config(self, **overrides):
        defaults = {
            "enabled": True,
            "min_pattern_count": 3,
            "min_feedback": 0.7,
            "max_candidates_per_run": 3,
            "sandbox_timeout": 5.0,
        }
        defaults.update(overrides)
        return SkillForgeConfig(**defaults)

    def test_disabled_fails(self, trace_store, run_store, tmp_path) -> None:
        from nova_ai.learning.skillforge.pipeline import run_skillforge

        result = run_skillforge(
            trace_store=trace_store,
            config=self._config(enabled=False),
            run_store=run_store,
            skills_root=tmp_path / "skills",
            llm=FakeSynthLLM(),
            tool_executor=FakeToolExecutor(),
        )
        assert result["status"] == "failed"
        assert "enabled is false" in result["error"]

    def test_no_executor_fails(self, trace_store, run_store, tmp_path) -> None:
        from nova_ai.learning.skillforge.pipeline import run_skillforge

        result = run_skillforge(
            trace_store=trace_store,
            config=self._config(),
            run_store=run_store,
            skills_root=tmp_path / "skills",
            llm=FakeSynthLLM(),
            tool_executor=None,
        )
        assert result["status"] == "failed"
        assert "tool executor" in result["error"]

    def test_no_patterns_skips(self, tmp_path, run_store) -> None:
        from nova_ai.learning.skillforge.pipeline import run_skillforge

        store = TraceStore(tmp_path / "empty.db")
        try:
            result = run_skillforge(
                trace_store=store,
                config=self._config(),
                run_store=run_store,
                skills_root=tmp_path / "skills",
                llm=FakeSynthLLM(),
                tool_executor=FakeToolExecutor(),
            )
            assert result["status"] == "skipped"
        finally:
            store.close()

    def test_happy_path_passes_and_persists(
        self, trace_store, run_store, tmp_path
    ) -> None:
        from nova_ai.learning.skillforge.pipeline import run_skillforge

        result = run_skillforge(
            trace_store=trace_store,
            config=self._config(),
            run_store=run_store,
            skills_root=tmp_path / "skills",
            llm=FakeSynthLLM(),
            tool_executor=FakeToolExecutor(),
        )
        assert result["status"] == "completed"
        assert result["passed"] == 1
        skill = result["skills"][0]
        assert skill["skill_name"] == "search-and-summarize"
        assert skill["status"] == "passed"
        record = run_store.list_candidate_runs(status="passed")[0]
        assert record["gauntlet"]["passed"] is True
        assert record["gauntlet"]["manifest"]["name"] == "search-and-summarize"

    def test_auto_adopt_installs_skill(
        self, trace_store, run_store, tmp_path
    ) -> None:
        from nova_ai.learning.skillforge.pipeline import run_skillforge
        from nova_ai.skills.loader import discover_skills

        skills_root = tmp_path / "skills"
        result = run_skillforge(
            trace_store=trace_store,
            config=self._config(auto_adopt=True),
            run_store=run_store,
            skills_root=skills_root,
            llm=FakeSynthLLM(),
            tool_executor=FakeToolExecutor(),
        )
        assert result["adopted"] == 1
        names = [m.name for m in discover_skills(skills_root)]
        assert "search-and-summarize" in names

    def test_no_auto_adopt_leaves_nothing_installed(
        self, trace_store, run_store, tmp_path
    ) -> None:
        from nova_ai.learning.skillforge.pipeline import run_skillforge
        from nova_ai.skills.loader import discover_skills

        result = run_skillforge(
            trace_store=trace_store,
            config=self._config(),
            run_store=run_store,
            skills_root=tmp_path / "skills",
            llm=FakeSynthLLM(),
            tool_executor=FakeToolExecutor(),
        )
        assert result["adopted"] == 0
        assert discover_skills(tmp_path / "skills") == []

    def test_synthesis_failure_recorded(self, trace_store, run_store, tmp_path) -> None:
        from nova_ai.learning.skillforge.pipeline import run_skillforge

        result = run_skillforge(
            trace_store=trace_store,
            config=self._config(),
            run_store=run_store,
            skills_root=tmp_path / "skills",
            llm=FakeSynthLLM("this is not toml [["),
            tool_executor=FakeToolExecutor(),
        )
        assert result["status"] == "failed"
        records = run_store.list_runs()
        assert any(r["status"] == "synthesis_failed" for r in records)

    def test_max_candidates_cap(self, tmp_path, run_store) -> None:
        from nova_ai.learning.skillforge.pipeline import run_skillforge

        store = TraceStore(tmp_path / "t.db")
        try:
            # Two distinct repeated patterns over registered stub tools.
            for i in range(3):
                store.save(
                    _trace(
                        f"a {i}",
                        [_tool_step("web_search", {}), _tool_step("think", {})],
                    )
                )
                store.save(
                    _trace(
                        f"b {i}",
                        [_tool_step("calculator", {}), _tool_step("think", {})],
                    )
                )
            result = run_skillforge(
                trace_store=store,
                config=self._config(max_candidates_per_run=1),
                run_store=run_store,
                skills_root=tmp_path / "skills",
                llm=FakeSynthLLM(),
                tool_executor=FakeToolExecutor(),
            )
            assert result["candidates"] == 1
        finally:
            store.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@pytest.fixture()
def nova_home(tmp_path, monkeypatch):
    import nova_ai.cli.forge_cmd as forge_cmd
    import nova_ai.core.config as config_mod
    import nova_ai.core.paths as paths_mod

    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(paths_mod, "get_config_dir", lambda: tmp_path)
    monkeypatch.setattr(forge_cmd, "_skills_root", lambda: tmp_path / "skills")
    monkeypatch.setattr(forge_cmd, "_forge_root", lambda: tmp_path / "learning" / "skillforge")
    return tmp_path


def _invoke(args):
    from click.testing import CliRunner

    from nova_ai.cli import cli

    return CliRunner().invoke(cli, ["forge", *args])


class TestForgeCLI:
    def test_run_disabled_exits_1(self, nova_home) -> None:
        result = _invoke(["run", "--foreground"])
        assert result.exit_code == 1
        assert "enabled is false" in result.output

    def test_run_foreground(self, nova_home, monkeypatch, trace_store) -> None:
        import nova_ai.cli.forge_cmd as forge_cmd

        monkeypatch.setattr(
            forge_cmd,
            "_effective_skillforge_config",
            lambda: SkillForgeConfig(enabled=True),
        )
        monkeypatch.setattr(
            forge_cmd,
            "_run_foreground",
            lambda cfg: {"status": "completed", "skills": [], "passed": 1},
        )
        result = _invoke(["run", "--foreground"])
        assert result.exit_code == 0, result.output
        assert "completed" in result.output

    def test_status_no_runs(self, nova_home) -> None:
        result = _invoke(["status"])
        assert result.exit_code == 0, result.output
        assert "No forge runs yet" in result.output

    def test_status_shows_gates(self, nova_home) -> None:
        import nova_ai.cli.forge_cmd as forge_cmd

        store = forge_cmd._run_store()
        try:
            store.start_run("forge_1")
            store.finish_run(
                "forge_1",
                status="passed",
                skill_name="my-skill",
                sequence=["a", "b"],
                gauntlet={
                    "passed": True,
                    "gates": [{"name": "static", "passed": True, "detail": "ok"}],
                },
            )
        finally:
            store.close()
        result = _invoke(["status"])
        assert result.exit_code == 0, result.output
        assert "my-skill" in result.output
        assert "static" in result.output

    def test_list_candidates(self, nova_home) -> None:
        import nova_ai.cli.forge_cmd as forge_cmd

        store = forge_cmd._run_store()
        try:
            store.start_run("forge_1")
            store.finish_run(
                "forge_1", status="passed", skill_name="my-skill",
                pattern_count=4, sequence=["web_search", "think"],
            )
        finally:
            store.close()
        result = _invoke(["list"])
        assert result.exit_code == 0, result.output
        assert "my-skill" in result.output

    def test_adopt_unknown_run_exits_1(self, nova_home) -> None:
        result = _invoke(["adopt", "forge_nope"])
        assert result.exit_code == 1
        assert "Unknown run" in result.output

    def test_adopt_refuses_failed(self, nova_home) -> None:
        import nova_ai.cli.forge_cmd as forge_cmd

        store = forge_cmd._run_store()
        try:
            store.start_run("forge_bad")
            store.finish_run("forge_bad", status="failed", skill_name="x",
                             gauntlet={"passed": False, "gates": []})
        finally:
            store.close()
        result = _invoke(["adopt", "forge_bad"])
        assert result.exit_code == 1

    def test_adopt_installs_passed_candidate(self, nova_home) -> None:
        import nova_ai.cli.forge_cmd as forge_cmd
        from nova_ai.skills.loader import discover_skills

        store = forge_cmd._run_store()
        try:
            store.start_run("forge_ok")
            store.finish_run(
                "forge_ok",
                status="passed",
                skill_name="search-and-summarize",
                pattern_count=4,
                gauntlet={
                    "passed": True,
                    "gates": [{"name": "static", "passed": True, "detail": "ok"}],
                    "manifest": {
                        "name": "search-and-summarize",
                        "description": "Search and summarize.",
                        "steps": [
                            {"tool_name": "web_search",
                             "arguments_template": '{"query": "{query}"}',
                             "output_key": "r"},
                            {"tool_name": "think",
                             "arguments_template": '{"thought": "{r}"}',
                             "output_key": "s"},
                        ],
                    },
                },
            )
        finally:
            store.close()
        result = _invoke(["adopt", "forge_ok"])
        assert result.exit_code == 0, result.output
        names = [m.name for m in discover_skills(nova_home / "skills")]
        assert "search-and-summarize" in names

    def test_reject_marks_run(self, nova_home) -> None:
        import nova_ai.cli.forge_cmd as forge_cmd

        store = forge_cmd._run_store()
        try:
            store.start_run("forge_1")
            store.finish_run("forge_1", status="passed", skill_name="x",
                             gauntlet={"passed": True, "gates": []})
        finally:
            store.close()
        result = _invoke(["reject", "forge_1"])
        assert result.exit_code == 0, result.output
        store = forge_cmd._run_store()
        try:
            assert store.get_run("forge_1")["status"] == "rejected"
        finally:
            store.close()

    def test_revert_removes_adopted(self, nova_home) -> None:
        from nova_ai.learning.skillforge.adoption import adopt_skill

        adopt_skill(
            _candidate_manifest(),
            run_id="forge_1",
            gauntlet={"passed": True, "gates": []},
            pattern_count=4,
            skills_root=nova_home / "skills",
        )
        result = _invoke(["revert", "search-and-summarize"])
        assert result.exit_code == 0, result.output
        assert not (nova_home / "skills" / "generated" / "search-and-summarize").exists()


def _candidate_manifest():
    from nova_ai.skills.types import SkillManifest, SkillStep

    return SkillManifest(
        name="search-and-summarize",
        description="Search and summarize.",
        steps=[
            SkillStep(tool_name="web_search", arguments_template="{}", output_key="r"),
            SkillStep(tool_name="think", arguments_template="{}", output_key="s"),
        ],
    )


# ---------------------------------------------------------------------------
# Scheduler dispatch
# ---------------------------------------------------------------------------


class TestSkillforgeDispatch:
    def _task(self) -> Any:
        from nova_ai.scheduler.scheduler import ScheduledTask

        return ScheduledTask(
            id="forge-task",
            prompt="",
            schedule_type="cron",
            schedule_value="0 4 * * *",
            metadata={"kind": "skillforge"},
        )

    def _scheduler(self):
        from nova_ai.scheduler.scheduler import TaskScheduler
        from nova_ai.scheduler.store import SchedulerStore

        return TaskScheduler(SchedulerStore(":memory:"), poll_interval=1)

    def test_disabled_config_skips(self) -> None:
        from nova_ai.core.config import LearningConfig

        sched = self._scheduler()
        try:
            sched.set_training_hooks(
                learning_config=LearningConfig(skillforge=SkillForgeConfig(enabled=False)),
                trace_store=MagicMock(),
            )
            result = sched._run_skillforge_task(self._task())
            assert result == (
                "[skillforge] learning.skillforge.enabled is false; skipping"
            )
        finally:
            sched.stop()

    def test_completed_run_formatted(self, monkeypatch) -> None:
        from nova_ai.core.config import LearningConfig

        sched = self._scheduler()
        try:
            sched.set_training_hooks(
                learning_config=LearningConfig(skillforge=SkillForgeConfig(enabled=True)),
                trace_store=MagicMock(),
            )
            monkeypatch.setattr(
                "nova_ai.learning.skillforge.pipeline.run_skillforge",
                lambda **kwargs: {
                    "status": "completed",
                    "run_id": "forge_abc",
                    "patterns_mined": 2,
                    "passed": 1,
                    "skills": [
                        {"skill_name": "my-skill", "status": "passed",
                         "adopted": False, "gauntlet": {}}
                    ],
                },
            )
            result = sched._run_skillforge_task(self._task())
            assert "forge_abc" in result
            assert "my-skill" in result
            assert "patterns=2" in result
        finally:
            sched.stop()

    def test_execute_task_routes_skillforge_kind(self, tmp_path, monkeypatch) -> None:
        import nova_ai.core.config as config_mod
        import nova_ai.scheduler.scheduler as sched_mod
        from nova_ai.core.config import LearningConfig
        from nova_ai.scheduler.scheduler import TaskScheduler
        from nova_ai.scheduler.store import SchedulerStore

        store = SchedulerStore(tmp_path / "sched.db")
        monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_DIR", tmp_path)
        monkeypatch.setattr(
            sched_mod.TaskScheduler,
            "_training_learning_config",
            lambda self: LearningConfig(skillforge=SkillForgeConfig(enabled=False)),
        )
        sched = TaskScheduler(store, system=MagicMock(), poll_interval=1)
        try:
            task = sched.create_task(
                "forge skills",
                "once",
                "2030-01-01T00:00:00+00:00",
                metadata={"kind": "skillforge"},
            )
            sched._execute_task(
                ScheduledTaskFromStore(store, task.id)
            )
            logs = store.get_run_logs(task.id)
            assert len(logs) == 1
            assert logs[0]["success"] == 1
            assert "enabled is false" in logs[0]["result"]
        finally:
            sched.stop()
            store.close()


def ScheduledTaskFromStore(store, task_id):
    from nova_ai.scheduler.scheduler import ScheduledTask

    return ScheduledTask.from_dict(store.get_task(task_id))

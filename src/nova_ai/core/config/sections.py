"""Configuration hierarchy: all config-section dataclasses.

Split out of the original monolithic ``core/config.py``. Re-exported by the
``nova_ai.core.config`` facade. Also hosts ``apply_security_profile`` (the
profile presets only touch SecurityConfig/ServerConfig, so they live beside
their subjects).

Sections order matches the original file: engine/intelligence/learning/
tools/agent/server/telemetry/analytics/traces/channel/security first, then
sandbox through NovaConfig.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nova_ai.core.config.hardware import HardwareInfo
from nova_ai.core.paths import get_config_dir

if TYPE_CHECKING:
    # Only used by type-checkers for the ``NovaConfig.mining`` field
    # annotation. The runtime import is deferred inside
    # ``_parse_mining_section()`` (loader.py) to break the import cycle:
    # ``mining/_stubs.py`` imports ``HardwareInfo`` from this package at its
    # top level.
    from nova_ai.mining._stubs import MiningConfig

# ---------------------------------------------------------------------------
# Configuration hierarchy
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class OllamaEngineConfig:
    """Per-engine config for Ollama."""

    host: str = ""


@dataclass(slots=True)
class VLLMEngineConfig:
    """Per-engine config for vLLM."""

    host: str = "http://localhost:8000"


@dataclass(slots=True)
class SGLangEngineConfig:
    """Per-engine config for SGLang."""

    host: str = "http://localhost:30000"


@dataclass(slots=True)
class LlamaCppEngineConfig:
    """Per-engine config for llama.cpp."""

    host: str = "http://localhost:8080"
    binary_path: str = ""


@dataclass(slots=True)
class MLXEngineConfig:
    """Per-engine config for MLX."""

    host: str = "http://localhost:8080"


@dataclass(slots=True)
class LMStudioEngineConfig:
    """Per-engine config for LM Studio."""

    host: str = "http://localhost:1234"


@dataclass(slots=True)
class ExoEngineConfig:
    """Per-engine config for Exo."""

    host: str = "http://localhost:52415"


@dataclass(slots=True)
class NexaEngineConfig:
    """Per-engine config for Nexa."""

    host: str = "http://localhost:18181"
    device: str = ""


@dataclass(slots=True)
class UzuEngineConfig:
    """Per-engine config for Uzu."""

    host: str = "http://localhost:8000"


@dataclass(slots=True)
class AppleFmEngineConfig:
    """Per-engine config for Apple Foundation Models."""

    host: str = "http://localhost:8079"


@dataclass(slots=True)
class GemmaCppEngineConfig:
    """Per-engine config for gemma.cpp."""

    model_path: str = ""
    tokenizer_path: str = ""
    model_type: str = ""
    num_threads: int = 0


@dataclass(slots=True)
class LemonadeEngineConfig:
    """Per-engine config for Lemonade."""

    host: str = "http://localhost:13305"


@dataclass
class EngineConfig:
    """Inference engine settings with nested per-engine configs."""

    default: str = "ollama"
    ollama: OllamaEngineConfig = field(default_factory=OllamaEngineConfig)
    vllm: VLLMEngineConfig = field(default_factory=VLLMEngineConfig)
    sglang: SGLangEngineConfig = field(default_factory=SGLangEngineConfig)
    llamacpp: LlamaCppEngineConfig = field(default_factory=LlamaCppEngineConfig)
    mlx: MLXEngineConfig = field(default_factory=MLXEngineConfig)
    lmstudio: LMStudioEngineConfig = field(default_factory=LMStudioEngineConfig)
    exo: ExoEngineConfig = field(default_factory=ExoEngineConfig)
    nexa: NexaEngineConfig = field(default_factory=NexaEngineConfig)
    uzu: UzuEngineConfig = field(default_factory=UzuEngineConfig)
    apple_fm: AppleFmEngineConfig = field(default_factory=AppleFmEngineConfig)
    gemma_cpp: GemmaCppEngineConfig = field(default_factory=GemmaCppEngineConfig)
    lemonade: LemonadeEngineConfig = field(default_factory=LemonadeEngineConfig)

    # Backward-compat properties for old flat attribute names
    @property
    def ollama_host(self) -> str:
        """Deprecated: use ``engine.ollama.host``."""
        return self.ollama.host

    @ollama_host.setter
    def ollama_host(self, value: str) -> None:
        self.ollama.host = value

    @property
    def vllm_host(self) -> str:
        """Deprecated: use ``engine.vllm.host``."""
        return self.vllm.host

    @vllm_host.setter
    def vllm_host(self, value: str) -> None:
        self.vllm.host = value

    @property
    def llamacpp_host(self) -> str:
        """Deprecated: use ``engine.llamacpp.host``."""
        return self.llamacpp.host

    @llamacpp_host.setter
    def llamacpp_host(self, value: str) -> None:
        self.llamacpp.host = value

    @property
    def llamacpp_path(self) -> str:
        """Deprecated: use ``engine.llamacpp.binary_path``."""
        return self.llamacpp.binary_path

    @llamacpp_path.setter
    def llamacpp_path(self, value: str) -> None:
        self.llamacpp.binary_path = value

    @property
    def sglang_host(self) -> str:
        """Deprecated: use ``engine.sglang.host``."""
        return self.sglang.host

    @sglang_host.setter
    def sglang_host(self, value: str) -> None:
        self.sglang.host = value

    @property
    def mlx_host(self) -> str:
        """Deprecated: use ``engine.mlx.host``."""
        return self.mlx.host

    @mlx_host.setter
    def mlx_host(self, value: str) -> None:
        self.mlx.host = value

    @property
    def lmstudio_host(self) -> str:
        """Deprecated: use ``engine.lmstudio.host``."""
        return self.lmstudio.host

    @lmstudio_host.setter
    def lmstudio_host(self, value: str) -> None:
        self.lmstudio.host = value

    @property
    def exo_host(self) -> str:
        """Deprecated: use ``engine.exo.host``."""
        return self.exo.host

    @exo_host.setter
    def exo_host(self, value: str) -> None:
        self.exo.host = value

    @property
    def nexa_host(self) -> str:
        """Deprecated: use ``engine.nexa.host``."""
        return self.nexa.host

    @nexa_host.setter
    def nexa_host(self, value: str) -> None:
        self.nexa.host = value

    @property
    def uzu_host(self) -> str:
        """Deprecated: use ``engine.uzu.host``."""
        return self.uzu.host

    @uzu_host.setter
    def uzu_host(self, value: str) -> None:
        self.uzu.host = value

    @property
    def apple_fm_host(self) -> str:
        """Deprecated: use ``engine.apple_fm.host``."""
        return self.apple_fm.host

    @apple_fm_host.setter
    def apple_fm_host(self, value: str) -> None:
        self.apple_fm.host = value

    @property
    def lemonade_host(self) -> str:
        """Deprecated: use ``engine.lemonade.host``."""
        return self.lemonade.host

    @lemonade_host.setter
    def lemonade_host(self, value: str) -> None:
        self.lemonade.host = value


@dataclass(slots=True)
class IntelligenceConfig:
    """The model — identity, paths, quantization, and generation defaults."""

    default_model: str = ""
    fallback_model: str = ""
    model_path: str = ""  # Local weights (HF repo, GGUF file, etc.)
    checkpoint_path: str = ""  # Checkpoint/adapter path
    quantization: str = "none"  # none, fp8, int8, int4, gguf_q4, gguf_q8
    preferred_engine: str = ""  # Override engine for this model (e.g., "vllm")
    provider: str = ""  # local, openai, anthropic, google
    # Generation defaults (overridable per-call)
    temperature: float = 0.7
    max_tokens: int = 1024
    top_p: float = 0.9
    top_k: int = 40
    repetition_penalty: float = 1.0
    stop_sequences: str = ""  # Comma-separated stop strings


@dataclass(slots=True)
class RoutingLearningConfig:
    """Routing sub-policy config within Learning."""

    policy: str = "heuristic"  # heuristic | learned
    min_samples: int = 5  # Min traces before trusting learned routing


@dataclass(slots=True)
class SFTConfig:
    """General-purpose SFT training config. Maps to [learning.intelligence.sft]."""

    model_name: str = "Qwen/Qwen3-1.7B"
    max_seq_length: int = 4096
    num_epochs: int = 3
    batch_size: int = 8
    learning_rate: float = 2e-5
    weight_decay: float = 0.01
    warmup_ratio: float = 0.1
    max_grad_norm: float = 1.0
    gradient_checkpointing: bool = True
    use_lora: bool = True
    lora_rank: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    target_modules: str = "q_proj,v_proj"  # comma-separated for TOML compat
    use_4bit: bool = False
    checkpoint_dir: str = "checkpoints/sft"
    min_pairs: int = 10
    agent_filter: str = ""


@dataclass(slots=True)
class GRPOConfig:
    """General-purpose GRPO training config. Maps to [learning.intelligence.grpo]."""

    model_name: str = "Qwen/Qwen3-1.7B"
    max_seq_length: int = 4096
    max_response_length: int = 2048
    num_epochs: int = 10
    batch_size: int = 16
    learning_rate: float = 1e-6
    max_grad_norm: float = 1.0
    gradient_checkpointing: bool = True
    num_samples_per_prompt: int = 8
    temperature: float = 1.0
    kl_coef: float = 0.0001
    clip_ratio: float = 0.2
    use_8bit_ref: bool = True
    checkpoint_dir: str = "checkpoints/grpo"
    save_every_n_epochs: int = 1
    keep_last_n: int = 3
    min_prompts: int = 10
    agent_filter: str = ""


@dataclass(slots=True)
class DSPyOptimizerConfig:
    """DSPy agent optimizer config. Maps to [learning.agent.dspy]."""

    optimizer: str = "BootstrapFewShotWithRandomSearch"
    task_lm: str = ""
    teacher_lm: str = ""
    max_bootstrapped_demos: int = 4
    max_labeled_demos: int = 4
    num_candidate_programs: int = 10
    max_rounds: int = 1
    optimize_system_prompt: bool = True
    optimize_few_shot: bool = True
    optimize_tool_descriptions: bool = True
    min_traces: int = 20
    metric_threshold: float = 0.7
    agent_filter: str = ""
    config_dir: str = ""


@dataclass(slots=True)
class GEPAOptimizerConfig:
    """GEPA agent optimizer config. Maps to [learning.agent.gepa]."""

    reflection_lm: str = ""
    max_metric_calls: int = 150
    population_size: int = 10
    optimize_system_prompt: bool = True
    optimize_tools: bool = True
    optimize_max_turns: bool = True
    optimize_temperature: bool = True
    min_traces: int = 20
    assessment_batch_size: int = 10
    agent_filter: str = ""
    config_dir: str = ""


@dataclass(slots=True)
class ACEOptimizerConfig:
    """ACE agent optimizer config. Maps to ``[learning.agent.ace]``.

    ACE (Agentic Context Engineering) evolves a *playbook* — annotated
    natural-language strategies that get prepended to the agent's
    context — using a Generator / Reflector / Curator triad. Unlike
    DSPy (few-shot bootstrapping) or GEPA (Pareto-evolutionary prompt
    mutation), ACE writes a textual playbook that the agent reads at
    inference time.

    See https://github.com/ace-agent/ace for the upstream reference.
    Install via ``pip install -e nova_ai[learning-ace]`` once the
    optional dep is available (ACE is not on PyPI as of v1.0.1; the
    extra installs from the upstream git repo).
    """

    # Models for ACE's three roles. Empty string = inherit from the
    # intelligence primitive's default cloud model.
    generator_model: str = ""
    reflector_model: str = ""
    curator_model: str = ""

    # Provider passed to ACE (``sambanova`` | ``together`` | ``openai``
    # | ``commonstack``). We default to ``openai`` since that's what
    # most NOVA AI users have credentials for.
    api_provider: str = "openai"

    # Run parameters. Defaults mirror ACE's offline-mode quickstart.
    num_epochs: int = 1
    max_num_rounds: int = 3
    eval_steps: int = 100
    playbook_token_budget: int = 80_000
    max_tokens: int = 4_096

    # Where ACE writes intermediate playbooks + final_results.json.
    # Empty string defaults to ``~/.nova_ai/learning/ace/<task>/``.
    save_dir: str = ""
    task_name: str = "nova_ai"

    # Standard filter / threshold knobs shared with DSPy / GEPA.
    min_traces: int = 20
    agent_filter: str = ""
    config_dir: str = ""


@dataclass(slots=True)
class IntelligenceLearningConfig:
    """Intelligence sub-policy config within Learning."""

    policy: str = "none"  # none | sft | grpo
    sft: SFTConfig = field(default_factory=SFTConfig)
    grpo: GRPOConfig = field(default_factory=GRPOConfig)


@dataclass(slots=True)
class AgentLearningConfig:
    """Agent sub-policy config within Learning."""

    policy: str = "none"  # none | dspy | gepa | ace
    dspy: DSPyOptimizerConfig = field(default_factory=DSPyOptimizerConfig)
    gepa: GEPAOptimizerConfig = field(default_factory=GEPAOptimizerConfig)
    ace: ACEOptimizerConfig = field(default_factory=ACEOptimizerConfig)


@dataclass(slots=True)
class SkillsLearningConfig:
    """Configuration for the skills learning loop (Plan 2A)."""

    auto_optimize: bool = False  # opt in via config
    optimizer: str = "dspy"  # "dspy" or "gepa"
    min_traces_per_skill: int = 20
    optimization_interval_seconds: int = 86400
    overlay_dir: str = field(
        default_factory=lambda: str(get_config_dir() / "learning" / "skills")
    )


@dataclass(slots=True)
class MetricsConfig:
    """Reward / optimization metric weights."""

    accuracy_weight: float = 0.6
    latency_weight: float = 0.2
    cost_weight: float = 0.1
    efficiency_weight: float = 0.1


@dataclass(slots=True)
class SpecSearchCompositeRewardConfig:
    """Composite reward weights for Intelligence-edit training (paper Eq. 1).

    R(q, y) = alpha * R_acc - beta * E_hat - gamma * L_hat - delta * C_hat
    """

    alpha: float = 0.5
    beta: float = 0.1
    gamma: float = 0.1
    delta: float = 0.3


@dataclass(slots=True)
class SpecSearchLearningConfig:
    """LLM-guided spec search config (paper §3.3, Algorithm 1).

    Maps to ``[learning.spec_search]`` and is consumed by
    ``SpecSearchOrchestrator.from_config`` and ``SpecSearchLoop``.
    """

    enabled: bool = False
    teacher_model: str = "claude-opus-4-6"
    teacher_engine: str = "cloud"  # registry key for the cloud engine
    autonomy_mode: str = "tiered"  # auto | tiered | manual

    # Per-session bounds (one diagnose/plan/execute pass)
    min_traces: int = 20
    max_cost_per_session_usd: float = 5.0
    max_tool_calls_per_diagnosis: int = 30

    # Multi-session loop (paper Algorithm 1)
    stagnation_k: int = 5
    max_total_cost_usd: float = 50.0
    stagnation_eps: float = 0.001  # gate-score delta below this counts as no progress

    # Gate (GateOK predicate)
    max_regression: float = 0.01  # paper default: epsilon = 1%
    min_improvement: float = 0.0
    benchmark_subsample_size: int = 50
    benchmark_version: str = "personal_v1"

    # Composite reward (only used when an Intelligence edit triggers training)
    composite_reward: SpecSearchCompositeRewardConfig = field(
        default_factory=SpecSearchCompositeRewardConfig,
    )


@dataclass(slots=True)
class TrainingConfig:
    """Self-training pipeline config. Maps to ``[learning.training]``.

    Drives the trace→SFT-pairs→LoRA→deploy loop (``nova train``): how much
    data is needed, which deployment targets receive the trained adapter,
    and how much autonomy the pipeline has. Weight updates are the most
    invasive edit class (spec-search pins ``LORA_FINETUNE`` at MANUAL tier),
    so ``auto_apply`` defaults to false and the benchmark gate always runs.
    """

    enabled: bool = False
    schedule: str = ""  # cron expression; empty = no scheduled runs
    auto_trigger: bool = False  # train when enough new qualifying traces accrue
    auto_apply: bool = False  # deploy without manual review (benchmark gate still enforced)
    min_pairs: int = 50  # minimum SFT pairs before a run is worth starting
    max_pairs: int = 5000  # cap on pairs per run (bounds training time)
    deploy_targets: list[str] = field(
        default_factory=lambda: ["adapter", "ollama"]
    )  # subset of: adapter, ollama, llamacpp
    ollama_tag_prefix: str = "nova-tuned"
    llamacpp_gguf_script: str = ""  # path to llama.cpp convert_hf_to_gguf.py

    # DPO preference lane (lane="dpo" on nova train run / scheduler meta)
    dpo_enabled: bool = False  # gate for the preference-tuning lane
    dpo_min_pairs: int = 20  # preference pairs needed before a DPO run starts
    dpo_tag_prefix: str = "nova-dpo"  # Ollama tag for DPO adapters


@dataclass(slots=True)
class ProvingConfig:
    """Model proving ground config. Maps to ``[learning.proving]``.

    Drives the head-to-head gauntlet (``nova prove``): a candidate model is
    evaluated against the incumbent on a benchmark synthesized from the
    user's own traces, per query class. The gauntlet itself is read-only —
    the only mutation is adopting winners into the routing policy map, and
    that requires either ``auto_adopt`` or an explicit ``nova prove adopt``.
    """

    enabled: bool = False
    auto_trigger: bool = False  # prove automatically when a new model appears
    auto_adopt: bool = False  # adopt winners without `nova prove adopt` (gate still applies)
    min_margin: float = 0.05  # per-class accuracy margin required to adopt
    min_samples: int = 10  # minimum synthesized benchmark samples per run
    max_samples: int = 60  # cap on benchmark size (bounds GPU time)
    schedule: str = ""  # cron expression for the watcher/prove task; empty = none
    incumbent: str = ""  # default opponent; "" → intelligence.default_model
    judge_engine: str = "local"  # "local" | "cloud" — engine backing the judge
    judge_model: str = ""  # "" → judge with the incumbent model (same judge both sides)


@dataclass(slots=True)
class ConsolidationConfig:
    """Memory consolidation ("sleep cycle") config. Maps to
    ``[learning.consolidation]``.

    Drives the nightly job (``nova memory consolidate run``): clusters
    episodic traces, distills atomic facts with provenance, resolves
    contradictions by recency + confidence, decays stale memory, and
    promotes hot facts into a compact core-memory block injected into
    every query. Facts are disposable — ``nova memory consolidate
    forget <id>`` removes any of them.
    """

    enabled: bool = False
    schedule: str = ""  # cron expression; empty = no scheduled runs
    min_session_messages: int = 6  # skip clusters smaller than this
    max_facts_per_run: int = 50  # cap on facts distilled per run
    judge_model: str = ""  # "" -> intelligence.default_model (local extraction)
    decay_days: int = 90  # facts untouched this long become 'decayed'
    core_memory_max_chars: int = 4000  # core-memory block budget


@dataclass(slots=True)
class SkillForgeConfig:
    """Skill Foundry config. Maps to ``[learning.skillforge]``.

    Drives ``nova forge``: mine traces for repeated tool sequences, have
    the local model synthesize a skill manifest chaining existing tools,
    and run it through a verification gauntlet (static checks, sandboxed
    replay on past instances, LLM judge). Adoption is manual by default
    and reversible with ``nova forge revert``.
    """

    enabled: bool = False
    auto_trigger: bool = False  # forge automatically when patterns accrue
    auto_adopt: bool = False  # install passing skills without `nova forge adopt`
    min_pattern_count: int = 3  # same tool-sequence must appear this often
    min_feedback: float = 0.7  # average trace feedback required to mine a pattern
    max_candidates_per_run: int = 3  # cap on skills synthesized per run
    sandbox_timeout: float = 30.0  # seconds per sandboxed replay step
    judge_model: str = ""  # "" -> intelligence.default_model (gauntlet judge)


@dataclass(slots=True)
class FleetConfig:
    """Fleet Oracle config. Maps to ``[learning.fleet]``.

    Drives ``nova oracle``: aggregate anonymized hardware + per-model
    performance stats from this machine's telemetry, optionally share them
    via a git-hosted dataset, and answer "best model for my hardware"
    questions from the pooled fleet data. Opt-in by construction — sharing
    is OFF until the user flips ``share_reports``.
    """

    share_reports: bool = False  # opt-in: push anonymized reports to the dataset
    dataset_repo: str = ""  # git URL of the shared fleet dataset repo
    min_calls_per_model: int = 5  # k-anonymity: models below this are dropped
    since_days: int = 30  # aggregation window for report building
    cache_dir: str = ""  # "" -> ~/.nova_ai/fleet/cache (dataset clone)


@dataclass
class LearningConfig:
    """Learning system settings with per-primitive sub-policies."""

    enabled: bool = False
    update_interval: int = 100
    auto_update: bool = False
    routing: RoutingLearningConfig = field(default_factory=RoutingLearningConfig)
    intelligence: IntelligenceLearningConfig = field(
        default_factory=IntelligenceLearningConfig,
    )
    agent: AgentLearningConfig = field(default_factory=AgentLearningConfig)
    skills: SkillsLearningConfig = field(default_factory=SkillsLearningConfig)
    spec_search: SpecSearchLearningConfig = field(
        default_factory=SpecSearchLearningConfig,
    )
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    training: TrainingConfig = field(default_factory=TrainingConfig)
    proving: ProvingConfig = field(default_factory=ProvingConfig)
    consolidation: ConsolidationConfig = field(default_factory=ConsolidationConfig)
    skillforge: SkillForgeConfig = field(default_factory=SkillForgeConfig)
    fleet: FleetConfig = field(default_factory=FleetConfig)

    # Training pipeline
    training_enabled: bool = False
    training_schedule: str = ""
    min_improvement: float = 0.02

    @property
    def training_effective(self) -> TrainingConfig:
        """Training config with deprecated flat fields folded in.

        ``learning.training_enabled`` / ``learning.training_schedule``
        predate the ``[learning.training]`` table; they act as aliases for
        ``training.enabled`` / ``training.schedule`` until removed.
        """
        cfg = self.training
        if self.training_enabled and not cfg.enabled:
            cfg = dataclasses.replace(cfg, enabled=True)
        if self.training_schedule and not cfg.schedule:
            cfg = dataclasses.replace(cfg, schedule=self.training_schedule)
        return cfg

    # Backward-compat properties for old flat field names
    @property
    def default_policy(self) -> str:
        """Deprecated: use ``learning.routing.policy``."""
        return self.routing.policy

    @default_policy.setter
    def default_policy(self, value: str) -> None:
        self.routing.policy = value

    @property
    def intelligence_policy(self) -> str:
        """Deprecated: use ``learning.intelligence.policy``."""
        return self.intelligence.policy

    @intelligence_policy.setter
    def intelligence_policy(self, value: str) -> None:
        self.intelligence.policy = value

    @property
    def agent_policy(self) -> str:
        """Deprecated: use ``learning.agent.policy``."""
        return self.agent.policy

    @agent_policy.setter
    def agent_policy(self, value: str) -> None:
        self.agent.policy = value

    @property
    def reward_weights(self) -> str:
        """Deprecated: use ``learning.metrics.*``."""
        parts = []
        m = self.metrics
        if m.latency_weight:
            parts.append(f"latency={m.latency_weight}")
        if m.cost_weight:
            parts.append(f"cost={m.cost_weight}")
        if m.efficiency_weight:
            parts.append(f"efficiency={m.efficiency_weight}")
        if m.accuracy_weight:
            parts.append(f"accuracy={m.accuracy_weight}")
        return ",".join(parts)

    @reward_weights.setter
    def reward_weights(self, value: str) -> None:
        if not value:
            return
        for part in value.split(","):
            if "=" not in part:
                continue
            key, val = part.strip().split("=", 1)
            key = key.strip()
            fval = float(val.strip())
            if key == "accuracy":
                self.metrics.accuracy_weight = fval
            elif key == "latency":
                self.metrics.latency_weight = fval
            elif key == "cost":
                self.metrics.cost_weight = fval
            elif key == "efficiency":
                self.metrics.efficiency_weight = fval


@dataclass(slots=True)
class StorageConfig:
    """Storage (memory) backend settings."""

    default_backend: str = "sqlite"
    db_path: str = field(default_factory=lambda: str(get_config_dir() / "memory.db"))
    context_top_k: int = 5
    context_min_score: float = 0.0
    context_max_tokens: int = 2048
    chunk_size: int = 512
    chunk_overlap: int = 64


# Backward-compatibility alias
MemoryConfig = StorageConfig


@dataclass(slots=True)
class MCPConfig:
    """MCP (Model Context Protocol) settings."""

    enabled: bool = True
    servers: str = ""  # JSON list of MCP server configs


@dataclass(slots=True)
class BrowserConfig:
    """Browser automation settings (Playwright)."""

    headless: bool = True
    timeout_ms: int = 30000
    viewport_width: int = 1280
    viewport_height: int = 720


@dataclass(slots=True)
class ToolsConfig:
    """Tools primitive settings — wraps storage and MCP configuration."""

    storage: StorageConfig = field(default_factory=StorageConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    enabled: str = ""  # comma-separated default tools


@dataclass
class AgentConfig:
    """Agent harness settings — orchestration, tools, system prompt."""

    default_agent: str = "simple"
    max_turns: int = 10
    tools: str = ""  # comma-separated tool names
    objective: str = ""  # concise purpose for routing/learning/docs
    system_prompt: str = ""  # inline system prompt (takes precedence if set)
    system_prompt_path: str = ""  # path to system prompt file (.txt, .md)
    context_from_memory: bool = True  # inject relevant memory context into prompts
    default_system_prompt: str = (
        "You are NOVA AI, a helpful AI assistant running locally on the "
        "user's own hardware. You are not a cloud service, and you are not "
        "Claude, ChatGPT, Gemini, or any other branded assistant. If asked "
        "who or what you are, identify yourself as NOVA AI. Respond "
        "helpfully, concisely, and accurately."
    )

    # Backward-compat property for old field name
    @property
    def default_tools(self) -> str:
        """Deprecated: use ``agent.tools``."""
        return self.tools

    @default_tools.setter
    def default_tools(self, value: str) -> None:
        self.tools = value


@dataclass(slots=True)
class ServerConfig:
    """API server settings."""

    host: str = "127.0.0.1"
    port: int = 8000
    agent: str = "orchestrator"
    model: str = ""
    workers: int = 1
    cors_origins: list = field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:5174",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5174",
            # Tauri 2 production webview origins.
            # macOS / Linux / iOS use the custom scheme; Windows /
            # Android use http(s)://tauri.localhost. All three must
            # be allowed so the desktop app's chat-completions stream
            # is not blocked by CORS in production builds.
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
        ]
    )


@dataclass(slots=True)
class TelemetryConfig:
    """Telemetry persistence settings."""

    enabled: bool = True
    db_path: str = field(default_factory=lambda: str(get_config_dir() / "telemetry.db"))
    gpu_metrics: bool = False
    gpu_poll_interval_ms: int = 50
    energy_vendor: str = ""  # auto-detect or force "nvidia"/"amd"/"apple"/"cpu_rapl"
    warmup_samples: int = 0
    steady_state_window: int = 5
    steady_state_threshold: float = 0.05


@dataclass(slots=True)
class AnalyticsConfig:
    """External anonymous usage analytics (PostHog).

    Separate concern from :class:`TelemetryConfig`, which stores local
    FLOPs/energy/inference metrics in SQLite. This controls anonymized
    usage events sent to the NOVA AI team's PostHog instance to
    measure setup success, retention, feature usage, and churn.

    No chat content, prompts, model outputs, file paths, emails, IPs,
    or hardware identifiers are ever sent. See ``docs/telemetry.md``.
    """

    enabled: bool = True
    host: str = "https://34.231.106.201.sslip.io"
    key: str = "phc_ysKu72QaxzYNmDpHFcesD2ZZAe68zkdWJEKoYYkc5e3n"
    anon_id_path: str = field(default_factory=lambda: str(get_config_dir() / "anon_id"))
    flush_interval_seconds: int = 30
    flush_at_size: int = 100


@dataclass(slots=True)
class TracesConfig:
    """Trace system settings."""

    enabled: bool = True
    db_path: str = field(default_factory=lambda: str(get_config_dir() / "traces.db"))


@dataclass(slots=True)
class ProactiveConfig:
    """Proactive agent — autonomous action scheduling and approval routing."""

    enabled: bool = False
    schedule: str = "0 5 * * *"  # cron expression (default: 5am daily)
    hours_back: int = 24  # how many hours of unacted items to scan
    timezone: str = "America/Los_Angeles"
    # Channel to send approval notifications and receive yes/no replies.
    # Format: "{type}:{id}", e.g. "imessage:+15551234567" or "telegram:123456789"
    notification_channel: str = ""


@dataclass(slots=True)
class TelegramChannelConfig:
    """Per-channel config for Telegram."""

    bot_token: str = ""
    allowed_chat_ids: str = ""
    parse_mode: str = "Markdown"


@dataclass(slots=True)
class DiscordChannelConfig:
    """Per-channel config for Discord."""

    bot_token: str = ""


@dataclass(slots=True)
class SlackChannelConfig:
    """Per-channel config for Slack."""

    bot_token: str = ""
    app_token: str = ""


@dataclass(slots=True)
class WebhookChannelConfig:
    """Per-channel config for generic webhooks."""

    url: str = ""
    secret: str = ""
    method: str = "POST"


@dataclass(slots=True)
class EmailChannelConfig:
    """Per-channel config for email (SMTP/IMAP)."""

    smtp_host: str = ""
    smtp_port: int = 587
    imap_host: str = ""
    imap_port: int = 993
    username: str = ""
    password: str = ""
    use_tls: bool = True


@dataclass(slots=True)
class WhatsAppChannelConfig:
    """Per-channel config for WhatsApp Cloud API."""

    access_token: str = ""
    phone_number_id: str = ""


@dataclass(slots=True)
class SignalChannelConfig:
    """Per-channel config for Signal (via signal-cli REST API)."""

    api_url: str = ""
    phone_number: str = ""


@dataclass(slots=True)
class GoogleChatChannelConfig:
    """Per-channel config for Google Chat webhooks."""

    webhook_url: str = ""


@dataclass(slots=True)
class IRCChannelConfig:
    """Per-channel config for IRC."""

    server: str = ""
    port: int = 6667
    nick: str = ""
    password: str = ""
    use_tls: bool = False


@dataclass(slots=True)
class WebChatChannelConfig:
    """Per-channel config for in-memory webchat."""

    pass


@dataclass(slots=True)
class TeamsChannelConfig:
    """Per-channel config for Microsoft Teams (Bot Framework)."""

    app_id: str = ""
    app_password: str = ""
    service_url: str = ""


@dataclass(slots=True)
class MatrixChannelConfig:
    """Per-channel config for Matrix."""

    homeserver: str = ""
    access_token: str = ""


@dataclass(slots=True)
class MattermostChannelConfig:
    """Per-channel config for Mattermost."""

    url: str = ""
    token: str = ""


@dataclass(slots=True)
class FeishuChannelConfig:
    """Per-channel config for Feishu (Lark)."""

    app_id: str = ""
    app_secret: str = ""


@dataclass(slots=True)
class BlueBubblesChannelConfig:
    """Per-channel config for BlueBubbles (iMessage bridge)."""

    url: str = ""
    password: str = ""


@dataclass(slots=True)
class WhatsAppBaileysChannelConfig:
    """Per-channel config for WhatsApp via Baileys protocol."""

    auth_dir: str = ""  # Defaults to ~/.nova_ai/whatsapp_auth
    assistant_name: str = "Nova"
    assistant_has_own_number: bool = False


@dataclass
class ChannelConfig:
    """Channel messaging settings."""

    enabled: bool = False
    default_channel: str = ""
    default_agent: str = "simple"
    telegram: TelegramChannelConfig = field(default_factory=TelegramChannelConfig)
    discord: DiscordChannelConfig = field(default_factory=DiscordChannelConfig)
    slack: SlackChannelConfig = field(default_factory=SlackChannelConfig)
    webhook: WebhookChannelConfig = field(default_factory=WebhookChannelConfig)
    email: EmailChannelConfig = field(default_factory=EmailChannelConfig)
    whatsapp: WhatsAppChannelConfig = field(default_factory=WhatsAppChannelConfig)
    signal: SignalChannelConfig = field(default_factory=SignalChannelConfig)
    google_chat: GoogleChatChannelConfig = field(
        default_factory=GoogleChatChannelConfig,
    )
    irc: IRCChannelConfig = field(default_factory=IRCChannelConfig)
    webchat: WebChatChannelConfig = field(default_factory=WebChatChannelConfig)
    teams: TeamsChannelConfig = field(default_factory=TeamsChannelConfig)
    matrix: MatrixChannelConfig = field(default_factory=MatrixChannelConfig)
    mattermost: MattermostChannelConfig = field(default_factory=MattermostChannelConfig)
    feishu: FeishuChannelConfig = field(default_factory=FeishuChannelConfig)
    bluebubbles: BlueBubblesChannelConfig = field(
        default_factory=BlueBubblesChannelConfig,
    )
    whatsapp_baileys: WhatsAppBaileysChannelConfig = field(
        default_factory=WhatsAppBaileysChannelConfig,
    )


@dataclass(slots=True)
class CapabilitiesConfig:
    """RBAC capability system settings."""

    enabled: bool = False
    policy_path: str = ""


@dataclass(slots=True)
class SecurityConfig:
    """Security guardrails settings."""

    enabled: bool = True
    scan_input: bool = True
    scan_output: bool = True
    mode: str = "redact"  # "redact" | "warn" | "block"
    # Redaction-before-cloud (roadmap WS3): scrub secrets/PII from prompts
    # before anything is transmitted to a cloud provider. Independent of
    # ``mode`` — cloud egress always redacts while this is on, even when the
    # general guardrail mode is only "warn".
    redact_before_cloud: bool = True
    secret_scanner: bool = True
    pii_scanner: bool = True
    audit_log_path: str = field(
        default_factory=lambda: str(get_config_dir() / "audit.db")
    )
    enforce_tool_confirmation: bool = True
    merkle_audit: bool = True
    signing_key_path: str = ""
    ssrf_protection: bool = True
    rate_limit_enabled: bool = True
    rate_limit_rpm: int = 60
    rate_limit_burst: int = 10
    local_engine_bypass: bool = False
    local_tool_bypass: bool = False
    profile: str = ""
    vault_key_path: str = field(
        default_factory=lambda: str(get_config_dir() / ".vault_key")
    )
    capabilities: CapabilitiesConfig = field(default_factory=CapabilitiesConfig)



# ---------------------------------------------------------------------------
# Security profile presets
# ---------------------------------------------------------------------------

_SECURITY_PROFILES: dict[str, dict[str, dict[str, Any]]] = {
    "personal": {
        "security": {
            "mode": "redact",
            "rate_limit_enabled": True,
            "local_engine_bypass": False,
            "local_tool_bypass": False,
        },
        "server": {
            "host": "127.0.0.1",
        },
    },
    "shared": {
        "security": {
            "mode": "redact",
            "rate_limit_enabled": True,
            "local_engine_bypass": False,
            "local_tool_bypass": False,
        },
        "server": {
            "host": "127.0.0.1",
        },
    },
    "server": {
        "security": {
            "mode": "block",
            "rate_limit_enabled": True,
            "rate_limit_rpm": 30,
            "rate_limit_burst": 5,
            "local_engine_bypass": False,
            "local_tool_bypass": False,
        },
        "server": {
            "host": "0.0.0.0",
        },
    },
}


def apply_security_profile(
    security_cfg: SecurityConfig,
    server_cfg: ServerConfig | None,
    *,
    overrides: set[str] | None = None,
) -> None:
    """Expand a named security profile into config fields.

    Fields in *overrides* (explicitly set by the user in TOML) are
    not overwritten by the profile.
    """
    profile = security_cfg.profile
    if not profile:
        return

    if profile not in _SECURITY_PROFILES:
        raise ValueError(
            f"Unknown security profile '{profile}'. "
            f"Valid profiles: {', '.join(_SECURITY_PROFILES)}"
        )

    _overrides = overrides or set()
    pdef = _SECURITY_PROFILES[profile]

    for key, value in pdef.get("security", {}).items():
        if key not in _overrides and hasattr(security_cfg, key):
            setattr(security_cfg, key, value)

    if server_cfg is not None:
        for key, value in pdef.get("server", {}).items():
            if key not in _overrides and hasattr(server_cfg, key):
                setattr(server_cfg, key, value)



@dataclass(slots=True)
class SandboxConfig:
    """Container sandbox settings."""

    enabled: bool = False
    image: str = "nova_ai-sandbox:latest"
    timeout: int = 300
    workspace: str = ""
    mount_allowlist_path: str = ""
    max_concurrent: int = 5
    runtime: str = "docker"
    wasm_fuel_limit: int = 1_000_000
    wasm_memory_limit_mb: int = 256


@dataclass(slots=True)
class SchedulerConfig:
    """Task scheduler settings."""

    enabled: bool = False
    poll_interval: int = 60
    db_path: str = ""  # Defaults to ~/.nova_ai/scheduler.db


@dataclass(slots=True)
class WorkflowConfig:
    """Workflow engine settings."""

    enabled: bool = False
    max_parallel: int = 4
    default_node_timeout: int = 300


@dataclass(slots=True)
class SessionConfig:
    """Cross-channel session settings."""

    enabled: bool = False
    max_age_hours: float = 24.0
    consolidation_threshold: int = 100
    db_path: str = field(default_factory=lambda: str(get_config_dir() / "sessions.db"))


@dataclass(slots=True)
class A2AConfig:
    """Agent-to-Agent protocol settings."""

    enabled: bool = False
    # Bearer token required for inbound A2A requests. Empty = unauthenticated
    # (only safe on a trusted network). See ``A2AServer(auth_token=...)``.
    auth_token: str = ""


@dataclass(slots=True)
class OperatorsConfig:
    """Operator lifecycle settings."""

    enabled: bool = False
    manifests_dir: str = field(
        default_factory=lambda: str(get_config_dir() / "operators")
    )
    auto_activate: str = ""  # Comma-separated operator IDs


@dataclass(slots=True)
class SpeechConfig:
    """Speech-to-text settings."""

    backend: str = "auto"  # "auto", "faster-whisper", "openai", "deepgram"
    model: str = "base"  # Whisper model size: tiny, base, small, medium, large-v3
    language: str = ""  # Empty = auto-detect
    device: str = "auto"  # "auto", "cpu", "cuda"
    compute_type: str = "float16"  # "float16", "int8", "float32"


@dataclass(slots=True)
class OptimizeConfig:
    """Configuration optimization settings."""

    max_trials: int = 20
    early_stop_patience: int = 5
    optimizer_model: str = "claude-sonnet-4-6"
    optimizer_provider: str = "anthropic"
    benchmark: str = ""
    max_samples: int = 50
    judge_model: str = "gpt-5-mini-2025-08-07"
    db_path: str = field(default_factory=lambda: str(get_config_dir() / "optimize.db"))


@dataclass(slots=True)
class AgentManagerConfig:
    """Persistent agent manager settings."""

    enabled: bool = True
    db_path: str = field(default_factory=lambda: str(get_config_dir() / "agents.db"))


@dataclass(slots=True)
class MemoryFilesConfig:
    """Persistent memory-file paths and nudge settings."""

    soul_path: str = field(default_factory=lambda: str(get_config_dir() / "SOUL.md"))
    memory_path: str = field(
        default_factory=lambda: str(get_config_dir() / "MEMORY.md")
    )
    user_path: str = field(default_factory=lambda: str(get_config_dir() / "USER.md"))
    nudge_interval: int = 10
    persona_name: str = ""  # named persona dir under <config-dir>/personas/<name>/


@dataclass(slots=True)
class SystemPromptConfig:
    """Limits and strategy for system-prompt assembly."""

    prefix: str = ""
    soul_max_chars: int = 4000
    memory_max_chars: int = 2500
    user_max_chars: int = 1500
    skill_desc_max_chars: int = 60
    truncation_strategy: str = "head_tail"


@dataclass(slots=True)
class CompressionConfig:
    """Configuration for context compression."""

    enabled: bool = True
    threshold: float = 0.50
    strategy: str = "session_consolidation"


@dataclass(slots=True)
class SkillSourceConfig:
    """Configuration for a single skill source (Hermes, OpenClaw, GitHub)."""

    source: str = ""  # "hermes", "openclaw", or "github"
    url: str = ""  # required when source = "github"
    filter: dict[str, Any] = field(default_factory=dict)
    auto_update: bool = False


@dataclass(slots=True)
class SkillsConfig:
    """Configuration for agent-authored procedural skills."""

    enabled: bool = True
    skills_dir: str = field(default_factory=lambda: str(get_config_dir() / "skills"))
    active: str = "*"
    auto_discover: bool = True
    auto_sync: bool = False
    nudge_interval: int = 15
    index_repo: str = "https://github.com/nova_ai/skill-index.git"
    index_dir: str = field(
        default_factory=lambda: str(get_config_dir() / "skill-index")
    )
    max_depth: int = 5
    sandbox_dangerous: bool = True
    sources: list[SkillSourceConfig] = field(default_factory=list)


@dataclass
class DigestSectionConfig:
    """Configuration for a single digest section."""

    sources: list[str] = field(default_factory=list)
    max_items: int = 10
    priority_contacts: list[str] = field(default_factory=list)


@dataclass
class DigestConfig:
    """Configuration for the morning digest feature."""

    enabled: bool = False
    schedule: str = "0 6 * * *"
    timezone: str = "America/Los_Angeles"
    persona: str = "nova"
    sections: list[str] = field(
        default_factory=lambda: ["messages", "calendar", "health", "world"]
    )
    optional_sections: list[str] = field(
        default_factory=lambda: ["github", "financial", "music", "fitness"]
    )
    honorific: str = "sir"
    voice_id: str = ""
    voice_speed: float = 1.0
    tts_backend: str = "cartesia"
    messages: DigestSectionConfig = field(
        default_factory=lambda: DigestSectionConfig(
            sources=["gmail", "slack", "google_tasks"]
        )
    )
    calendar: DigestSectionConfig = field(
        default_factory=lambda: DigestSectionConfig(sources=["gcalendar"])
    )
    health: DigestSectionConfig = field(
        default_factory=lambda: DigestSectionConfig(sources=["oura", "apple_health"])
    )
    world: DigestSectionConfig = field(
        default_factory=lambda: DigestSectionConfig(sources=[])
    )


@dataclass
class NovaConfig:
    """Top-level configuration for NOVA AI."""

    installed_at: str = ""
    installer_version: str = ""
    hardware: HardwareInfo = field(default_factory=HardwareInfo)
    engine: EngineConfig = field(default_factory=EngineConfig)
    intelligence: IntelligenceConfig = field(default_factory=IntelligenceConfig)
    learning: LearningConfig = field(default_factory=LearningConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    analytics: AnalyticsConfig = field(default_factory=AnalyticsConfig)
    traces: TracesConfig = field(default_factory=TracesConfig)
    channel: ChannelConfig = field(default_factory=ChannelConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    workflow: WorkflowConfig = field(default_factory=WorkflowConfig)
    sessions: SessionConfig = field(default_factory=SessionConfig)
    a2a: A2AConfig = field(default_factory=A2AConfig)
    operators: OperatorsConfig = field(default_factory=OperatorsConfig)
    speech: SpeechConfig = field(default_factory=SpeechConfig)
    optimize: OptimizeConfig = field(default_factory=OptimizeConfig)
    agent_manager: AgentManagerConfig = field(default_factory=AgentManagerConfig)
    memory_files: MemoryFilesConfig = field(default_factory=MemoryFilesConfig)
    system_prompt: SystemPromptConfig = field(default_factory=SystemPromptConfig)
    compression: CompressionConfig = field(default_factory=CompressionConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    digest: DigestConfig = field(default_factory=DigestConfig)
    proactive: ProactiveConfig = field(default_factory=ProactiveConfig)
    mining: MiningConfig | None = None

    @property
    def memory(self) -> StorageConfig:
        """Backward-compatible accessor — canonical location is tools.storage."""
        return self.tools.storage

    @memory.setter
    def memory(self, value: StorageConfig) -> None:
        """Backward-compatible setter."""
        self.tools.storage = value


"""NOVA AI configuration facade.

User configuration lives at ``~/.nova_ai/config.toml``.  ``load_config()``
detects hardware, fills sensible defaults, then overlays any user overrides
found in the TOML file.

This package replaced the original monolithic ``core/config.py`` (~2,400
lines). The public API is unchanged — everything re-exported below resolved
to ``nova_ai.core.config.<name>`` before the split, and still does. The
implementation lives in focused submodules:

- ``hardware``    — GPU/CPU/RAM detection, engine recommendation
- ``models``      — default-model tier tables, ``recommend_model``
- ``sections``    — all config-section dataclasses (EngineConfig ... NovaConfig)
- ``validation``  — ``validate_config_key``
- ``loader``      — TOML overlay/migrations and ``load_config``
- ``tomlgen``     — default TOML rendering for ``nova init``

Tests patch module attributes (``config.shutil``, ``config.platform``,
``config._run_cmd``, ``config.load_config``, ``config.DEFAULT_CONFIG_DIR``).
To keep those working, the facade re-exports the *submodules themselves* as
attributes (``shutil``, ``platform``, ... come along via
``sys.modules`` aliasing) and aliases ``load_config`` so
``monkeypatch.setattr("nova_ai.core.config.load_config", ...)`` keeps
affecting every ``from nova_ai.core.config import load_config`` call made
after the patch.
"""

from __future__ import annotations

import platform as _platform  # noqa: F401  (tests patch config.platform.system)
import shutil as _shutil  # noqa: F401  (tests patch config.shutil.which)
import subprocess as _subprocess  # noqa: F401

# Tests patch ``config.shutil.which`` / ``config.platform.system`` /
# ``config._run_cmd`` by string path (``patch("nova_ai.core.config._run_cmd",
# ...)``). For that to reach the functions that *use* them, the facade
# attributes must be the same objects the hardware code reads at call time.
# The hardware helpers live in ``config.hardware`` and reference those names
# through *that* module's globals, so point the submodules' globals back at
# the facade attributes: patching ``nova_ai.core.config.<name>`` mutates the
# shared module object and the detection helpers see the patch.
from nova_ai.core.config import hardware as _hardware_mod  # noqa: E402
from nova_ai.core.config.hardware import (  # noqa: F401  (public re-exports)
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_PATH,
    GpuInfo,
    HardwareInfo,
    _available_memory_gb,
    _ensure_config_dir,
    detect_hardware,
    recommend_engine,
)
from nova_ai.core.config.loader import (  # noqa: F401  (public re-exports)
    _apply_toml_section,
    _migrate_toml_data,
    _parse_mining_section,
    load_config,
)
from nova_ai.core.config.models import (  # noqa: F401  (public re-exports)
    _LEMONADE_DEFAULT_MODEL,
    _MODEL_TIER_FALLBACK,
    _MODEL_TIERS,
    estimated_download_gb,
    recommend_model,
)
from nova_ai.core.config.sections import (  # noqa: F401  (public re-exports)
    A2AConfig,
    ACEOptimizerConfig,
    AgentConfig,
    AgentLearningConfig,
    AgentManagerConfig,
    AnalyticsConfig,
    AppleFmEngineConfig,
    BlueBubblesChannelConfig,
    BrowserConfig,
    CapabilitiesConfig,
    ChannelConfig,
    ConsolidationConfig,
    DiscordChannelConfig,
    DSPyOptimizerConfig,
    EmailChannelConfig,
    EngineConfig,
    ExoEngineConfig,
    FeishuChannelConfig,
    FleetConfig,
    GemmaCppEngineConfig,
    GEPAOptimizerConfig,
    GoogleChatChannelConfig,
    GRPOConfig,
    IntelligenceConfig,
    IntelligenceLearningConfig,
    IRCChannelConfig,
    LearningConfig,
    LemonadeEngineConfig,
    LlamaCppEngineConfig,
    LMStudioEngineConfig,
    MatrixChannelConfig,
    MattermostChannelConfig,
    MCPConfig,
    MemoryConfig,
    MemoryFilesConfig,
    MetricsConfig,
    MLXEngineConfig,
    NexaEngineConfig,
    NovaConfig,
    OllamaEngineConfig,
    OperatorsConfig,
    OptimizeConfig,
    ProactiveConfig,
    ProvingConfig,
    RoutingLearningConfig,
    SandboxConfig,
    SchedulerConfig,
    SecurityConfig,
    ServerConfig,
    SessionConfig,
    SFTConfig,
    SGLangEngineConfig,
    SignalChannelConfig,
    SkillForgeConfig,
    SkillsConfig,
    SkillsLearningConfig,
    SkillSourceConfig,
    SlackChannelConfig,
    SpecSearchCompositeRewardConfig,
    SpecSearchLearningConfig,
    SpeechConfig,
    StorageConfig,
    SystemPromptConfig,
    TeamsChannelConfig,
    TelegramChannelConfig,
    TelemetryConfig,
    ToolsConfig,
    TracesConfig,
    TrainingConfig,
    UzuEngineConfig,
    VLLMEngineConfig,
    WebChatChannelConfig,
    WebhookChannelConfig,
    WhatsAppBaileysChannelConfig,
    WhatsAppChannelConfig,
    WorkflowConfig,
    apply_security_profile,
)
from nova_ai.core.config.tomlgen import (  # noqa: F401  (public re-exports)
    generate_default_toml,
    generate_minimal_toml,
)
from nova_ai.core.config.validation import (  # noqa: F401  (public re-export)
    validate_config_key,
)

# Re-exported for backward compatibility (they used to live here before the
# split; several modules import them from this namespace).
from nova_ai.core.paths import (  # noqa: F401
    ConfigurationError,
    get_cache_dir,
    get_config_dir,
    get_config_path,
    get_data_dir,
)

_detect_amd_gpu = _hardware_mod._detect_amd_gpu
_detect_apple_gpu = _hardware_mod._detect_apple_gpu
_detect_cpu_brand = _hardware_mod._detect_cpu_brand
_detect_nvidia_gpu = _hardware_mod._detect_nvidia_gpu
_total_ram_gb = _hardware_mod._total_ram_gb

# ``config._run_cmd`` is the single patch point: the hardware helpers call
# ``_facade()._run_cmd(...)`` at runtime, so a test patch of this attribute
# (or of ``shutil.which`` / ``platform.system`` via the aliased modules
# below) reaches every detection function.
_run_cmd = _hardware_mod._run_cmd

# Tests patch ``config.shutil.which`` / ``config.platform.system`` by string
# path (``patch("nova_ai.core.config.shutil.which")``). For that to reach the
# functions that *use* those modules, the facade attributes must alias the
# same module objects the hardware code imports — so publish them under
# their original public names.
shutil = _shutil
platform = _platform
subprocess = _subprocess

__all__ = [
    "A2AConfig",
    "AgentConfig",
    "AgentManagerConfig",
    "OperatorsConfig",
    "AgentLearningConfig",
    "BlueBubblesChannelConfig",
    "BrowserConfig",
    "CapabilitiesConfig",
    "ChannelConfig",
    "ConfigurationError",
    "DEFAULT_CONFIG_DIR",
    "DEFAULT_CONFIG_PATH",
    "DiscordChannelConfig",
    "get_cache_dir",
    "get_config_dir",
    "get_config_path",
    "get_data_dir",
    "EmailChannelConfig",
    "EngineConfig",
    "FeishuChannelConfig",
    "GoogleChatChannelConfig",
    "GpuInfo",
    "HardwareInfo",
    "IRCChannelConfig",
    "IntelligenceConfig",
    "IntelligenceLearningConfig",
    "NovaConfig",
    "LearningConfig",
    "LMStudioEngineConfig",
    "LlamaCppEngineConfig",
    "MCPConfig",
    "MLXEngineConfig",
    "MatrixChannelConfig",
    "MattermostChannelConfig",
    "MemoryConfig",
    "MetricsConfig",
    "OllamaEngineConfig",
    "OptimizeConfig",
    "RoutingLearningConfig",
    "SGLangEngineConfig",
    "SandboxConfig",
    "SchedulerConfig",
    "SecurityConfig",
    "ServerConfig",
    "SessionConfig",
    "SignalChannelConfig",
    "SlackChannelConfig",
    "SpeechConfig",
    "StorageConfig",
    "TeamsChannelConfig",
    "TelegramChannelConfig",
    "TelemetryConfig",
    "ToolsConfig",
    "TracesConfig",
    "VLLMEngineConfig",
    "WebChatChannelConfig",
    "WebhookChannelConfig",
    "WhatsAppBaileysChannelConfig",
    "WhatsAppChannelConfig",
    "WorkflowConfig",
    "detect_hardware",
    "generate_default_toml",
    "generate_minimal_toml",
    "load_config",
    "recommend_engine",
    "recommend_model",
    "validate_config_key",
]

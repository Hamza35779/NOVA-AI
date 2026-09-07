"""TOML loading: overlay, migration, mining parsing, and ``load_config``.

Split out of the original monolithic ``core/config.py``. Re-exported by the
``nova_ai.core.config`` facade.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nova_ai.core.config.hardware import (
    _ensure_config_dir,
    detect_hardware,
    recommend_engine,
)
from nova_ai.core.config.sections import NovaConfig, apply_security_profile
from nova_ai.core.paths import get_config_path

if TYPE_CHECKING:
    from nova_ai.mining._stubs import MiningConfig

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

# ---------------------------------------------------------------------------
# TOML loading
# ---------------------------------------------------------------------------


def _apply_toml_section(target: Any, section: dict[str, Any]) -> None:
    """Overlay TOML key/value pairs onto a dataclass instance.

    Recursively handles nested dicts when the target attribute is itself
    a dataclass.  Normalises TOML arrays to comma-separated strings — both
    for dataclass fields annotated as ``str`` and for backward-compat
    property setters that expect string input.
    """
    for key, value in section.items():
        if hasattr(target, key):
            if isinstance(value, dict):
                nested = getattr(target, key)
                if hasattr(nested, "__dataclass_fields__"):
                    _apply_toml_section(nested, value)
                else:
                    setattr(target, key, value)
            else:
                # Normalise TOML arrays → comma-separated string.
                # Covers both real dataclass fields and backward-compat
                # property setters (e.g. reward_weights, default_tools).
                if isinstance(value, list):
                    is_str_field = False
                    if hasattr(target, "__dataclass_fields__"):
                        field_obj = target.__dataclass_fields__.get(key)
                        if field_obj is not None and field_obj.type in ("str", str):
                            is_str_field = True
                        elif field_obj is None:
                            # Property, not a real field — normalise to string
                            is_str_field = True
                    if is_str_field:
                        value = ",".join(str(v) for v in value)
                setattr(target, key, value)


def _migrate_toml_data(data: dict[str, Any], cfg: NovaConfig) -> None:
    """Migrate old-format TOML keys to new structure in-place.

    Handles cross-section moves that can't be solved by backward-compat
    properties alone (e.g. ``agent.temperature`` → ``intelligence.temperature``).
    """
    # agent.temperature / agent.max_tokens → intelligence.*
    if "agent" in data:
        agent_data = data["agent"]
        intel_data = data.setdefault("intelligence", {})
        for moved_key in ("temperature", "max_tokens"):
            if moved_key in agent_data:
                intel_data.setdefault(moved_key, agent_data.pop(moved_key))

    # context_injection from memory / tools.storage → agent.context_from_memory
    for src_section in ("memory",):
        src = data.get(src_section, {})
        if isinstance(src, dict) and "context_injection" in src:
            data.setdefault("agent", {}).setdefault(
                "context_from_memory",
                src.pop("context_injection"),
            )

    if "tools" in data:
        tools_data = data["tools"]
        if isinstance(tools_data, dict):
            storage_sub = tools_data.get("storage", {})
            if isinstance(storage_sub, dict) and "context_injection" in storage_sub:
                data.setdefault("agent", {}).setdefault(
                    "context_from_memory",
                    storage_sub.pop("context_injection"),
                )


def _parse_mining_section(data: dict) -> MiningConfig | None:
    """Parse the ``[mining]`` TOML section into a ``MiningConfig``.

    Returns None if the section is absent. Resolves the ``submit_target``
    string into a ``SoloTarget`` or ``PoolTarget`` tagged union.
    """
    if "mining" not in data:
        return None

    # Lazy runtime import to break the import cycle: ``mining/_stubs.py``
    # imports ``HardwareInfo`` from this module at its top level. By the
    # time ``_parse_mining_section`` is called, ``core.config`` is already
    # fully initialized in ``sys.modules``, so the cycle is harmless.
    from nova_ai.mining._stubs import MiningConfig, PoolTarget, SoloTarget

    section = data["mining"]
    extra = section.get("extra", {}) or {}

    target_str = section.get("submit_target", "solo")
    submit_target: Any
    if target_str == "solo":
        submit_target = SoloTarget(
            pearld_rpc_url=extra.get("pearld_rpc_url", "http://localhost:44107")
        )
    elif isinstance(target_str, str) and target_str.startswith("pool:"):
        submit_target = PoolTarget(url=target_str[len("pool:") :])
    else:
        raise ValueError(
            f"[mining].submit_target must be 'solo' or 'pool:<url>', got {target_str!r}"
        )

    return MiningConfig(
        provider=section["provider"],
        wallet_address=section["wallet_address"],
        submit_target=submit_target,
        fee_bps=int(section.get("fee_bps", 0)),
        fee_payout_address=section.get("fee_payout_address") or None,
        extra={k: v for k, v in extra.items()},
    )


@functools.lru_cache(maxsize=1)
def load_config(path: Path | None = None) -> NovaConfig:
    """Detect hardware, build defaults, overlay TOML overrides.

    Parameters
    ----------
    path:
        Explicit config file. If not set, uses ``NOVA_AI_CONFIG`` when set,
        otherwise ``~/.nova_ai/config.toml``.
    """
    _ensure_config_dir()
    hw = detect_hardware()
    cfg = NovaConfig(hardware=hw)
    cfg.engine.default = recommend_engine(hw)

    if path is not None:
        config_path = Path(path)
    elif os.environ.get("NOVA_AI_CONFIG"):
        config_path = Path(os.environ["NOVA_AI_CONFIG"]).expanduser().resolve()
    else:
        config_path = get_config_path()
    if config_path.exists():
        with open(config_path, "rb") as fh:
            data = tomllib.load(fh)

        # Run backward-compat migrations before applying
        _migrate_toml_data(data, cfg)

        # All top-level sections — recursive _apply_toml_section handles
        # nested sub-configs (engine.ollama, learning.routing, channel.*, etc.)
        top_sections = (
            "engine",
            "intelligence",
            "learning",
            "agent",
            "server",
            "telemetry",
            "analytics",
            "traces",
            "security",
            "channel",
            "tools",
            "sandbox",
            "scheduler",
            "workflow",
            "sessions",
            "a2a",
            "operators",
            "speech",
            "optimize",
            "agent_manager",
            "digest",
            "proactive",
            "memory_files",
            "system_prompt",
            "compression",
            "skills",
        )
        for section_name in top_sections:
            if section_name in data:
                _apply_toml_section(
                    getattr(cfg, section_name),
                    data[section_name],
                )

        # Memory: accept [memory] (old) → maps to tools.storage
        if "memory" in data:
            _apply_toml_section(cfg.tools.storage, data["memory"])

        # Top-level install provenance (installed_at, installer_version)
        for key in ("installed_at", "installer_version"):
            if key in data:
                setattr(cfg, key, data[key])

        # Expand security profile (user TOML overrides take precedence)
        _user_security_keys = set(data.get("security", {}).keys())
        apply_security_profile(cfg.security, cfg.server, overrides=_user_security_keys)

        # Mining: dedicated parser for tagged-union submit_target
        cfg.mining = _parse_mining_section(data)

    # Apply profile even without a config file (in case defaults set one)
    if not config_path.exists() and cfg.security.profile:
        apply_security_profile(cfg.security, cfg.server)

    return cfg

"""Config-key validation.

Split out of the original monolithic ``core/config.py``. Re-exported by the
``nova_ai.core.config`` facade.
"""

from __future__ import annotations

from typing import Any

from nova_ai.core.config.sections import NovaConfig

# ---------------------------------------------------------------------------
# Config key validation
# ---------------------------------------------------------------------------

# Sections that users may set via ``nova config set``.
# ``hardware`` is auto-detected and not user-settable.
_SETTABLE_SECTIONS = frozenset(NovaConfig.__dataclass_fields__.keys()) - {
    "hardware",
    "mining",
}


def validate_config_key(dotted_key: str) -> type:
    """Validate a dotted config key and return the leaf field's Python type.

    Raises :class:`ValueError` when the key does not map to a known field.
    The function walks the ``NovaConfig`` dataclass hierarchy using
    ``dataclasses.fields()``.

    Examples::

        validate_config_key("engine.ollama.host")      # -> str
        validate_config_key("intelligence.temperature") # -> float
    """
    from dataclasses import fields as dc_fields

    parts = dotted_key.split(".")
    if len(parts) < 2:
        raise ValueError(
            f"Config key must have at least two segments (e.g. engine.default), "
            f"got: {dotted_key!r}"
        )

    if parts[0] not in _SETTABLE_SECTIONS:
        raise ValueError(
            f"Unknown config key: {dotted_key!r} "
            f"(valid top-level sections: {sorted(_SETTABLE_SECTIONS)})"
        )

    # Walk the dataclass tree
    current_cls: Any = NovaConfig
    for i, part in enumerate(parts):
        field_map = {f.name: f for f in dc_fields(current_cls)}
        if part not in field_map:
            path_so_far = ".".join(parts[: i + 1])
            raise ValueError(
                f"Unknown config key: {dotted_key!r} "
                f"(no field {part!r} at {path_so_far}; "
                f"valid fields: {sorted(field_map.keys())})"
            )
        fld = field_map[part]
        # Resolve the type — unwrap Optional, etc.
        fld_type: Any = fld.type
        if isinstance(fld_type, str):
            # Resolve forward references without executing arbitrary
            # expressions (unlike ``eval``). Resolution runs per-field
            # against the *submodule* that owns the annotation; names that
            # only exist under TYPE_CHECKING (e.g. ``MiningConfig``) raise
            # NameError and fall back to the raw string annotation.
            import typing

            import nova_ai.core.config.sections as _sections_mod

            try:
                fld_type = typing.get_type_hints(
                    current_cls, globalns=vars(_sections_mod)
                )[part]
            except NameError:
                # Whole-class resolution can fail on a TYPE_CHECKING-only
                # annotation elsewhere in the class; retry this field alone
                # via a minimal probe class.
                _probe = type("_FieldProbe", (), {"__annotations__": {"v": fld.type}})
                try:
                    fld_type = typing.get_type_hints(
                        _probe, globalns=vars(_sections_mod)
                    )["v"]
                except NameError:
                    fld_type = fld.type

        if i == len(parts) - 1:
            # Leaf — return the primitive type
            return fld_type
        else:
            # Must be a nested dataclass
            if not (
                isinstance(fld_type, type)
                and hasattr(fld_type, "__dataclass_fields__")
            ):
                path_so_far = ".".join(parts[: i + 1])
                shown = getattr(fld_type, "__name__", fld_type)
                raise ValueError(
                    f"Unknown config key: {dotted_key!r} "
                    f"({path_so_far} is a leaf of type {shown}, "
                    f"not a section)"
                )
            current_cls = fld_type

    # Should not reach here, but satisfy type checker
    raise ValueError(f"Unknown config key: {dotted_key!r}")

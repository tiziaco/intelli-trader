"""Reconstruction-safe tagged-union codec for the frozen policy value objects (D-03, D-05).

This module is the structured serializer/deserializer for the six sizing/SLTP policies
declared in ``core/sizing.py``. It carries two contracts:

- **D-03 — it is the reconstruction-safe counterpart to ``Strategy.to_dict()``.**
  ``to_dict()`` is a ONE-WAY observability snapshot: it renders policies through ``repr()``
  (``"FractionOfCash(Decimal('0.95'))"``). Rebuilding a policy from that form would require
  interpreting the stored text as Python source — and a ``kind`` tag arrives from an external
  ``STRATEGY_COMMAND`` payload or a ``config_json`` row, so treating any part of a blob as
  source text would turn operator-supplied config into arbitrary code execution (T-10-01 /
  T-10-02). This codec exists precisely to make that unnecessary: a policy self-describes as
  ``{"kind": "FractionOfCash", "fraction": "0.95", "step_size": null}`` and is rebuilt by a
  plain dict lookup in the injected registry — which IS the access-control allowlist. Class
  resolution never consults the import system and never interprets a blob field.

- **D-03 — it is a money boundary.** Every ``Decimal`` field crosses JSON as a STRING and
  re-enters the Decimal domain via ``to_money`` (the ``Decimal(str(x))`` path, money.py D-04).
  A binary float must never back a money value; JSON has no Decimal token, so a float on the
  wire is refused rather than silently rounded. Non-finite Decimals (NaN/Infinity) have no
  safe JSON round-trip and are refused on encode.

**D-05 — placement.** The codec lives in ``core/`` next to the value objects it serializes.
It imports stdlib + intra-core ONLY: nothing from ``order_handler``, ``strategy_handler``,
``storage``, or (at module level) ``config``. The ``TrailType`` enum needed to resolve
``PercentFromFill.trail_type`` is imported FUNCTION-LOCALLY, mirroring what
``sizing.py::__post_init__`` already does — a module-level import would invert the
core->config dependency direction and break the GATE-01 import-inertness gate.

**Registry derivation.** The kind->class map is DERIVED from ``get_args(SizingPolicy)`` and
``get_args(SLTPPolicy)`` rather than hand-listed, so a new union member cannot be silently
omitted (``PercentFromDecision`` was already missed once, by the D-03 decision text itself).
An app-supplied ``overlay`` merges over the derived default so the owner's private-repo IP
policies register without ``itrader`` ever importing them.

**Validation comes for free.** ``decode_policy`` constructs the class normally, so each
policy's ``__post_init__`` re-validates on the way back; the codec deliberately does NOT
duplicate those validators (they would drift).
"""

import dataclasses
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from enum import Enum
from types import NoneType, UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from itrader.core.money import to_money
from itrader.core.sizing import SizingPolicy, SLTPPolicy

__all__ = [
    "PolicyCodecError",
    "PolicyRegistry",
    "UnknownPolicyKindError",
    "decode_policy",
    "default_policy_registry",
    "encode_policy",
]

# The kind->class map. The registry IS the allowlist for decode (T-10-01).
PolicyRegistry = dict[str, type]

_KIND_KEY = "kind"

# Declared types that cross JSON unchanged. Identity-based membership: ``bool`` is a
# subclass of ``int`` but the annotation objects are distinct, so each maps to itself.
_PASSTHROUGH: tuple[type, ...] = (bool, int, str)


class PolicyCodecError(ValueError):
    """A policy blob could not be encoded or decoded (D-03 fail-loud)."""


class UnknownPolicyKindError(PolicyCodecError):
    """The blob's ``kind`` tag is not registered — a loud reject, never a silent None."""


def _resolved_hints(cls: type) -> dict[str, Any]:
    """Resolve ``cls``'s field annotations (D-03).

    Uses ``get_type_hints``, NOT ``dataclasses.fields()[i].type``:
    ``PercentFromFill.trail_type`` is the QUOTED forward reference ``"TrailType | None"``,
    so ``field.type`` hands back that raw string and is unusable for coercion.

    ``get_type_hints`` alone raises ``NameError`` on ``PercentFromFill`` because
    ``TrailType`` is deliberately not importable at ``core/sizing.py`` module level (the
    config-enum exception). Passing it through an explicit ``localns`` — sourced from a
    FUNCTION-LOCAL import, exactly as ``sizing.py::__post_init__`` does — resolves the ref
    while preserving the core->config direction.

    NOT memoized, deliberately. ``strategy_handler/base.py::_declared_hints`` memoizes the
    same idiom with ``functools.cache``, but its docstring justifies that by HOT-path
    pressure (``to_dict`` re-walked the MRO per signal snapshot). This codec is a COLD path
    — it runs at rehydrate, runtime ``add``, and ``reconfigure``, never per bar — so the
    justification does not transfer, and the memoization-decorator surface is a governed
    inventory pinned to exactly three documented sites
    (``docs/CACHE-CLASSIFICATION.md`` + ``tests/integration/test_cache_classification.py``).
    Adding a fourth cache here would buy nothing measurable and would additionally retain a
    strong reference to every app-supplied overlay class. If this ever becomes hot, register
    the site in the doc inventory rather than reaching for an ad-hoc dict (which would slip
    past the gate's field scan).
    """
    from itrader.config import TrailType

    return get_type_hints(cls, localns={"TrailType": TrailType})


def _unwrap_optional(declared: Any) -> tuple[Any, bool]:
    """Split ``X | None`` into ``(X, True)``; a non-union declared type is ``(X, False)``.

    Only a single non-None arm is supported — a genuine multi-arm union has no unambiguous
    coercion and is refused rather than guessed at.
    """
    origin = get_origin(declared)
    if origin is not UnionType and origin is not Union:
        return declared, False

    arms = get_args(declared)
    non_none = [arm for arm in arms if arm is not NoneType]
    if len(non_none) != 1:
        raise PolicyCodecError(
            f"unsupported union type {declared!r}: expected exactly one non-None arm, "
            f"got {len(non_none)}"
        )
    return non_none[0], len(non_none) != len(arms)


def _encode_decimal(owner: str, field: str, value: Any) -> str:
    """Serialize a Decimal to its string wire form (D-03 money boundary)."""
    if not isinstance(value, Decimal):
        raise PolicyCodecError(
            f"{owner}.{field} is declared Decimal but holds {type(value).__name__}: {value!r}"
        )
    if not value.is_finite():
        raise PolicyCodecError(
            f"{owner}.{field} is not finite ({value!r}): a NaN/Infinity Decimal has no safe "
            f"JSON round-trip"
        )
    return str(value)


def _decode_decimal(owner: str, field: str, raw: Any) -> Decimal:
    """Re-enter the Decimal domain from the string wire form (D-03 money boundary)."""
    if isinstance(raw, float):
        raise PolicyCodecError(
            f"{owner}.{field}: a JSON float cannot back a money value (float for money is a "
            f"correctness defect) — encode Decimals as strings"
        )
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise PolicyCodecError(
            f"{owner}.{field}: expected a Decimal string, got {type(raw).__name__}: {raw!r}"
        )
    try:
        value = to_money(raw)
    except InvalidOperation as exc:
        raise PolicyCodecError(f"{owner}.{field}: not a valid Decimal: {raw!r}") from exc
    if not value.is_finite():
        raise PolicyCodecError(f"{owner}.{field}: refusing a non-finite Decimal: {raw!r}")
    return value


def _encode_value(owner: str, field: str, declared: Any, value: Any) -> Any:
    """Coerce one field OUT, dispatching on its resolved declared type."""
    inner, optional = _unwrap_optional(declared)

    if value is None:
        if not optional:
            raise PolicyCodecError(f"{owner}.{field} is not optional but holds None")
        return None

    if inner is Decimal:
        return _encode_decimal(owner, field, value)
    if isinstance(inner, type) and issubclass(inner, Enum):
        return value.value
    if inner in _PASSTHROUGH:
        return value

    # Fail loud: a silent pass-through would smuggle an uncoerced value into a frozen
    # policy (T-10-03).
    raise PolicyCodecError(
        f"{owner}.{field}: unsupported declared type {inner!r} — the codec coerces "
        f"Decimal, Enum, bool, int, str (optionally None-unioned)"
    )


def _decode_value(owner: str, field: str, declared: Any, raw: Any) -> Any:
    """Coerce one field IN, dispatching on its resolved declared type."""
    inner, optional = _unwrap_optional(declared)

    if raw is None:
        if not optional:
            raise PolicyCodecError(f"{owner}.{field} is not optional but the blob holds null")
        return None

    if inner is Decimal:
        return _decode_decimal(owner, field, raw)
    if isinstance(inner, type) and issubclass(inner, Enum):
        try:
            return inner(raw)
        except ValueError as exc:
            raise PolicyCodecError(
                f"{owner}.{field}: {raw!r} is not a valid {inner.__name__}"
            ) from exc
    if inner in _PASSTHROUGH:
        if not isinstance(raw, inner):
            raise PolicyCodecError(
                f"{owner}.{field}: expected {inner.__name__}, got "
                f"{type(raw).__name__}: {raw!r}"
            )
        return raw

    raise PolicyCodecError(
        f"{owner}.{field}: unsupported declared type {inner!r} — the codec coerces "
        f"Decimal, Enum, bool, int, str (optionally None-unioned)"
    )


def default_policy_registry(overlay: PolicyRegistry | None = None) -> PolicyRegistry:
    """Build the kind->class map, DERIVED from the two union aliases (D-03).

    Deriving from ``get_args`` is the point: hand-listing is how ``PercentFromDecision`` got
    omitted from the D-03 decision text. A new union member registers itself.

    ``overlay`` merges OVER the derived default, so an app can register private-repo IP
    policies without ``itrader`` importing them. A fresh dict is returned on every call —
    callers cannot mutate the shared default.
    """
    registry: PolicyRegistry = {
        cls.__name__: cls for cls in (*get_args(SizingPolicy), *get_args(SLTPPolicy))
    }
    if overlay:
        registry.update(overlay)
    return registry


def encode_policy(policy: Any) -> dict[str, Any]:
    """Serialize a frozen policy to a self-describing, JSON-native blob (D-03).

    Emits ``{"kind": <class name>, ...one key per dataclass field...}``. Decimals become
    strings, Enums become their ``.value`` — so ``json.dumps`` needs no ``default=`` hook.
    """
    cls = type(policy)
    if not dataclasses.is_dataclass(cls):
        raise PolicyCodecError(
            f"not a dataclass policy: {cls.__name__} — the codec introspects dataclass fields"
        )

    hints = _resolved_hints(cls)
    blob: dict[str, Any] = {_KIND_KEY: cls.__name__}
    for field in dataclasses.fields(cls):
        declared = hints.get(field.name)
        if declared is None:
            raise PolicyCodecError(f"{cls.__name__}.{field.name}: no resolvable annotation")
        blob[field.name] = _encode_value(
            cls.__name__, field.name, declared, getattr(policy, field.name)
        )
    return blob


def decode_policy(blob: Mapping[str, Any], registry: PolicyRegistry) -> Any:
    """Reconstruct a frozen policy from a tagged blob (D-03).

    The ``kind`` tag is resolved by a plain dict lookup in ``registry`` and nothing else —
    the registry IS the allowlist (T-10-01). No part of ``blob`` is ever interpreted as
    source text, and the import system is never consulted.

    The class is constructed normally, so its ``__post_init__`` re-validates the decoded
    values for free — an out-of-range blob raises rather than rebuilding an invalid policy.
    """
    kind = blob.get(_KIND_KEY)
    if not isinstance(kind, str):
        raise PolicyCodecError(
            f"policy blob is missing a string {_KIND_KEY!r} tag: got {kind!r}"
        )

    cls = registry.get(kind)
    if cls is None:
        raise UnknownPolicyKindError(
            f"unknown policy kind {kind!r}; registered kinds: {sorted(registry)}"
        )
    if not dataclasses.is_dataclass(cls):
        raise PolicyCodecError(f"registered kind {kind!r} is not a dataclass: {cls!r}")

    field_names = {field.name for field in dataclasses.fields(cls)}
    unknown = set(blob) - field_names - {_KIND_KEY}
    if unknown:
        raise PolicyCodecError(f"{kind}: unknown field(s) in blob: {sorted(unknown)}")

    hints = _resolved_hints(cls)
    kwargs: dict[str, Any] = {}
    for field in dataclasses.fields(cls):
        if field.name not in blob:
            has_default = (
                field.default is not dataclasses.MISSING
                or field.default_factory is not dataclasses.MISSING
            )
            if not has_default:
                raise PolicyCodecError(f"{kind}: blob is missing required field {field.name!r}")
            continue
        declared = hints.get(field.name)
        if declared is None:
            raise PolicyCodecError(f"{kind}.{field.name}: no resolvable annotation")
        kwargs[field.name] = _decode_value(kind, field.name, declared, blob[field.name])

    return cls(**kwargs)

"""Unit tests for the D-03 tagged-union policy codec (D-03 / D-05).

The codec is the reconstruction-safe counterpart to ``Strategy.to_dict()``'s one-way
``repr()`` snapshot: every downstream P10 capability (D-01 rehydrate, D-04 ``config_json``,
D-09 runtime ``add``) needs a policy blob that reconstructs WITHOUT string evaluation.

What is pinned here:

* **Round-trip for all SIX policies** — ``decode(encode(p)) == p``. The frozen dataclasses
  compare by value, so ``==`` IS the assertion.
* **The registry is DERIVED from the two union aliases** (``get_args(SizingPolicy)`` /
  ``get_args(SLTPPolicy)``), never hand-listed — ``PercentFromDecision`` was already omitted
  once, by the CONTEXT's own D-03 list.
* **The money boundary (D-03)** — every Decimal crosses JSON as a STRING and re-enters via
  ``Decimal(str)``; the blob is ``json.dumps``-able with no ``default=`` hook.
* **The ``trail_type`` trap** — a quoted forward-ref Enum inside an Optional union must
  round-trip as the enum MEMBER, not a bare string.
* **D-05 direction** — ``TrailType`` is imported from ``itrader.config`` in THIS TEST ONLY.
  ``core/sizing.py`` deliberately lazy-imports it inside ``__post_init__`` to avoid inverting
  the core->config dependency; the codec preserves that direction.

4-space indentation (``tests/`` follows the module it tests; ``core/`` is 4-space). NO
``__init__.py`` in this dir — the ``unit`` marker is auto-applied by ``tests/conftest.py``
from the folder location.
"""

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import get_args

import pytest

from itrader.config import TrailType
from itrader.core.policy_codec import (
    PolicyCodecError,
    UnknownPolicyKindError,
    decode_policy,
    default_policy_registry,
    encode_policy,
)
from itrader.core.sizing import (
    FixedQuantity,
    FractionOfCash,
    LeveredFraction,
    PercentFromDecision,
    PercentFromFill,
    RiskPercent,
    SizingPolicy,
    SLTPPolicy,
)

# One instance of each of the six union members. Every Decimal enters via the
# string path (Pitfall 1) — never ``Decimal(0.95)``.
_POLICIES = [
    FractionOfCash(fraction=Decimal("0.95")),
    FractionOfCash(fraction=Decimal("0.5"), step_size=Decimal("0.001")),
    FixedQuantity(qty=Decimal("1.5")),
    RiskPercent(risk_pct=Decimal("0.02"), step_size=Decimal("0.0001")),
    # LeveredFraction guards ``> 0``, NOT the (0, 1] unit interval — f > 1 is
    # structurally expressible (a Kelly fraction).
    LeveredFraction(fraction=Decimal("2.5")),
    PercentFromFill(sl_pct=Decimal("0.02"), tp_pct=Decimal("0.05")),
    PercentFromFill(
        sl_pct=Decimal("0.02"),
        tp_pct=Decimal("0.05"),
        trail_type=TrailType.PERCENT,
        trail_value=Decimal("0.01"),
    ),
    PercentFromDecision(sl_pct=Decimal("0.03"), tp_pct=Decimal("0.06")),
]

_POLICY_IDS = [
    "FractionOfCash",
    "FractionOfCash-step",
    "FixedQuantity",
    "RiskPercent",
    "LeveredFraction",
    "PercentFromFill",
    "PercentFromFill-trailing",
    "PercentFromDecision",
]


@dataclass(frozen=True, slots=True)
class _CustomIpPolicy:
    """Stand-in for an owner private-repo IP policy (D-03 injectable registry).

    ``itrader`` must never import the owner's concrete policies, so the overlay is the
    only registration seam.
    """

    edge: Decimal
    step_size: Decimal | None = None


@dataclass(frozen=True, slots=True)
class _NonFiniteCarrier:
    """A validation-free Decimal carrier for the encode-side non-finite backstop.

    Deliberately NOT one of the six shipped policies: every shipped policy's
    ``__post_init__`` runs an ordering comparison against a NaN, which raises
    ``InvalidOperation`` at CONSTRUCTION — so a real policy can never carry a NaN
    into ``encode_policy``. This carrier is the only way to reach the codec's own
    non-finite guard, which protects app-supplied overlay policies that (like this
    one) do not validate finiteness themselves.
    """

    amount: Decimal


@pytest.mark.parametrize("policy", _POLICIES, ids=_POLICY_IDS)
def test_round_trip_all_six_policies(policy: object) -> None:
    """D-03: ``decode(encode(p)) == p`` for every SizingPolicy + SLTPPolicy member."""
    registry = default_policy_registry()
    assert decode_policy(encode_policy(policy), registry) == policy


def test_decimal_fields_cross_json_as_strings() -> None:
    """D-03 money boundary: Decimals serialize to str, and the blob is plain-JSON safe."""
    policy = FractionOfCash(fraction=Decimal("0.95"), step_size=Decimal("0.001"))
    blob = encode_policy(policy)

    # The exact wire form — a string, not a float/int/Decimal.
    assert blob["fraction"] == "0.95"
    assert isinstance(blob["fraction"], str)
    assert isinstance(blob["step_size"], str)

    for name, value in blob.items():
        assert not isinstance(value, (float, Decimal)), f"{name} must not be float/Decimal"

    # No ``default=`` hook needed — the blob is already JSON-native.
    text = json.dumps(blob)
    assert decode_policy(json.loads(text), default_policy_registry()) == policy


def test_decimal_round_trips_through_json_for_every_policy() -> None:
    """D-03: a full json.dumps -> json.loads cycle preserves Decimal precision exactly."""
    registry = default_policy_registry()
    for policy in _POLICIES:
        blob = encode_policy(policy)
        assert decode_policy(json.loads(json.dumps(blob)), registry) == policy


def test_trail_type_enum_in_optional_union_round_trips() -> None:
    """D-03: the quoted forward-ref Enum inside an Optional union survives the trip.

    The encoded form carries the enum's ``.value``; the decoded field is the enum MEMBER
    again, never a bare string.
    """
    policy = PercentFromFill(
        sl_pct=Decimal("0.02"),
        tp_pct=Decimal("0.05"),
        trail_type=TrailType.PERCENT,
        trail_value=Decimal("0.01"),
    )
    blob = encode_policy(policy)

    assert blob["trail_type"] == TrailType.PERCENT.value
    assert blob["trail_value"] == "0.01"

    decoded = decode_policy(blob, default_policy_registry())
    assert decoded == policy
    assert decoded.trail_type is TrailType.PERCENT
    assert isinstance(decoded.trail_value, Decimal)


def test_registry_is_derived_from_both_union_aliases() -> None:
    """D-03: the kind->class map derives from get_args, so a member cannot be omitted."""
    registry = default_policy_registry()
    members = (*get_args(SizingPolicy), *get_args(SLTPPolicy))

    assert set(registry) == {cls.__name__ for cls in members}
    for cls in members:
        assert registry[cls.__name__] is cls

    # The six shipped policies, named explicitly — a regression guard against the
    # union shrinking silently.
    assert set(registry) == {
        "FractionOfCash",
        "FixedQuantity",
        "RiskPercent",
        "LeveredFraction",
        "PercentFromFill",
        "PercentFromDecision",
    }


def test_unknown_kind_is_a_loud_reject() -> None:
    """D-03: an unknown kind tag raises UnknownPolicyKindError naming the offender."""
    with pytest.raises(UnknownPolicyKindError, match="NoSuchPolicy"):
        decode_policy({"kind": "NoSuchPolicy"}, default_policy_registry())


def test_post_init_revalidates_on_decode() -> None:
    """D-03: an out-of-range encoded blob raises rather than rebuilding an invalid policy.

    ``FractionOfCash.fraction`` must lie in (0, 1]; a tampered ``"1.5"`` must not
    reconstruct.
    """
    blob = encode_policy(FractionOfCash(fraction=Decimal("0.95")))
    blob["fraction"] = "1.5"

    with pytest.raises(Exception) as exc_info:
        decode_policy(blob, default_policy_registry())
    assert "fraction" in str(exc_info.value)


def test_overlay_registry_registers_a_custom_ip_policy() -> None:
    """D-03: an app-supplied overlay merges OVER the derived default and round-trips."""
    registry = default_policy_registry(overlay={"_CustomIpPolicy": _CustomIpPolicy})

    # The derived defaults survive the merge.
    assert registry["FractionOfCash"] is FractionOfCash
    assert registry["_CustomIpPolicy"] is _CustomIpPolicy

    policy = _CustomIpPolicy(edge=Decimal("0.42"), step_size=Decimal("0.01"))
    blob = encode_policy(policy)
    assert blob["kind"] == "_CustomIpPolicy"
    assert blob["edge"] == "0.42"
    assert decode_policy(blob, registry) == policy

    # The default registry is NOT mutated by the overlay.
    assert "_CustomIpPolicy" not in default_policy_registry()


def test_encoding_a_non_finite_decimal_raises() -> None:
    """D-03 backstop: a NaN/Infinity Decimal has no safe JSON round-trip — refuse it."""
    for bad in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
        with pytest.raises(PolicyCodecError):
            encode_policy(_NonFiniteCarrier(amount=bad))

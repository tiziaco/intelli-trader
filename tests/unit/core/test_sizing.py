"""M5-06 vocabulary tests: SizingPolicy / SLTPPolicy kinds, TradingDirection, SignalIntent.

These lock the typed event-carried sizing vocabulary (Plan 07-01, Task 1):

1. Policy kinds (``FractionOfCash``, ``FixedQuantity``, ``RiskPercent``) and
   SLTP kinds (``PercentFromFill``, ``PercentFromDecision``) are frozen/slots
   dataclasses validated at construction (D-06 fail-loud): invalid params
   raise ``SizingPolicyViolation`` naming the field and value.
2. ``TradingDirection`` parses case-insensitively via ``_missing_`` (the
   OrderType house pattern) and raises a clear ``ValueError`` on unknowns.
3. ``SignalIntent`` (D-12 strategy-return contract) is frozen/slots/kw_only
   with ``exit_fraction`` defaulting to ``Decimal("1")`` (D-07).
4. Pitfall 1: every policy Decimal literal here uses the string path
   (``Decimal("0.95")``, never ``Decimal(0.95)``).
"""

import dataclasses
from decimal import Decimal

import pytest

from itrader.core.enums import OrderType, Side
from itrader.core.exceptions import SizingPolicyViolation
from itrader.core.sizing import (
    FixedQuantity,
    FractionOfCash,
    PercentFromDecision,
    PercentFromFill,
    RiskPercent,
    SignalIntent,
    SizingPolicy,
    SLTPPolicy,
    TradingDirection,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# FractionOfCash — fraction in (0, 1] (D-02/D-06)
# ---------------------------------------------------------------------------


def test_fraction_of_cash_constructs():
    # D-02: the golden policy literal is Decimal("0.95") by string construction.
    policy = FractionOfCash(fraction=Decimal("0.95"))
    assert policy.fraction == Decimal("0.95")
    assert policy.step_size is None


def test_fraction_of_cash_full_fraction_one_allowed():
    # Boundary: fraction == 1 is inside (0, 1].
    assert FractionOfCash(fraction=Decimal("1")).fraction == Decimal("1")


def test_fraction_of_cash_above_one_raises():
    # D-06 fail-loud: fraction outside (0, 1] raises at construction.
    with pytest.raises(SizingPolicyViolation, match="fraction"):
        FractionOfCash(fraction=Decimal("1.5"))


def test_fraction_of_cash_zero_raises():
    with pytest.raises(SizingPolicyViolation, match="fraction"):
        FractionOfCash(fraction=Decimal("0"))


def test_fraction_of_cash_negative_raises():
    with pytest.raises(SizingPolicyViolation, match="fraction"):
        FractionOfCash(fraction=Decimal("-0.5"))


# ---------------------------------------------------------------------------
# FixedQuantity — qty > 0
# ---------------------------------------------------------------------------


def test_fixed_quantity_constructs():
    assert FixedQuantity(qty=Decimal("2")).qty == Decimal("2")


def test_fixed_quantity_zero_raises():
    with pytest.raises(SizingPolicyViolation, match="qty"):
        FixedQuantity(qty=Decimal("0"))


def test_fixed_quantity_negative_raises():
    with pytest.raises(SizingPolicyViolation, match="qty"):
        FixedQuantity(qty=Decimal("-1"))


# ---------------------------------------------------------------------------
# RiskPercent — risk_pct > 0 (Van Tharp input)
# ---------------------------------------------------------------------------


def test_risk_percent_constructs():
    assert RiskPercent(risk_pct=Decimal("0.02")).risk_pct == Decimal("0.02")


def test_risk_percent_zero_raises():
    with pytest.raises(SizingPolicyViolation, match="risk_pct"):
        RiskPercent(risk_pct=Decimal("0"))


def test_risk_percent_negative_raises():
    with pytest.raises(SizingPolicyViolation, match="risk_pct"):
        RiskPercent(risk_pct=Decimal("-0.02"))


# ---------------------------------------------------------------------------
# step_size — optional, > 0 when set (D-05; quantities only, never prices)
# ---------------------------------------------------------------------------


def test_step_size_none_passes_all_three_kinds():
    # D-05: step_size is optional — None means "no exchange step constraint".
    assert FractionOfCash(fraction=Decimal("0.5")).step_size is None
    assert FixedQuantity(qty=Decimal("1")).step_size is None
    assert RiskPercent(risk_pct=Decimal("0.01")).step_size is None


def test_step_size_positive_passes_all_three_kinds():
    step = Decimal("0.001")
    assert FractionOfCash(fraction=Decimal("0.5"), step_size=step).step_size == step
    assert FixedQuantity(qty=Decimal("1"), step_size=step).step_size == step
    assert RiskPercent(risk_pct=Decimal("0.01"), step_size=step).step_size == step


def test_step_size_zero_raises_all_three_kinds():
    # D-05/D-06: step_size == 0 would make quantize meaningless — fail loud.
    with pytest.raises(SizingPolicyViolation, match="step_size"):
        FractionOfCash(fraction=Decimal("0.5"), step_size=Decimal("0"))
    with pytest.raises(SizingPolicyViolation, match="step_size"):
        FixedQuantity(qty=Decimal("1"), step_size=Decimal("0"))
    with pytest.raises(SizingPolicyViolation, match="step_size"):
        RiskPercent(risk_pct=Decimal("0.01"), step_size=Decimal("0"))


def test_step_size_negative_raises():
    with pytest.raises(SizingPolicyViolation, match="step_size"):
        FixedQuantity(qty=Decimal("1"), step_size=Decimal("-0.001"))


# ---------------------------------------------------------------------------
# SLTP kinds — sl_pct/tp_pct > 0 (D-13)
# ---------------------------------------------------------------------------


def test_percent_from_fill_constructs():
    sltp = PercentFromFill(sl_pct=Decimal("0.05"), tp_pct=Decimal("0.10"))
    assert sltp.sl_pct == Decimal("0.05")
    assert sltp.tp_pct == Decimal("0.10")


def test_percent_from_decision_constructs():
    sltp = PercentFromDecision(sl_pct=Decimal("0.03"), tp_pct=Decimal("0.06"))
    assert sltp.sl_pct == Decimal("0.03")
    assert sltp.tp_pct == Decimal("0.06")


def test_percent_from_fill_nonpositive_pct_raises():
    with pytest.raises(SizingPolicyViolation, match="sl_pct"):
        PercentFromFill(sl_pct=Decimal("0"), tp_pct=Decimal("0.10"))
    with pytest.raises(SizingPolicyViolation, match="tp_pct"):
        PercentFromFill(sl_pct=Decimal("0.05"), tp_pct=Decimal("-0.10"))


def test_percent_from_decision_nonpositive_pct_raises():
    with pytest.raises(SizingPolicyViolation, match="sl_pct"):
        PercentFromDecision(sl_pct=Decimal("-0.01"), tp_pct=Decimal("0.06"))
    with pytest.raises(SizingPolicyViolation, match="tp_pct"):
        PercentFromDecision(sl_pct=Decimal("0.03"), tp_pct=Decimal("0"))


# ---------------------------------------------------------------------------
# TradingDirection — case-insensitive boundary parse (D-08 seam)
# ---------------------------------------------------------------------------


def test_trading_direction_members():
    assert TradingDirection.LONG_ONLY.value == "LONG_ONLY"
    assert TradingDirection.LONG_SHORT.value == "LONG_SHORT"
    assert TradingDirection.SHORT_ONLY.value == "SHORT_ONLY"


def test_trading_direction_case_insensitive_parse():
    # The OrderType _missing_ house pattern: any casing parses.
    assert TradingDirection("long_only") is TradingDirection.LONG_ONLY
    assert TradingDirection("LONG_only") is TradingDirection.LONG_ONLY
    assert TradingDirection("Long_Short") is TradingDirection.LONG_SHORT
    assert TradingDirection("short_only") is TradingDirection.SHORT_ONLY


def test_trading_direction_unknown_raises_with_value_in_message():
    with pytest.raises(ValueError, match="sideways"):
        TradingDirection("sideways")


# ---------------------------------------------------------------------------
# SignalIntent — D-12 strategy-return contract
# ---------------------------------------------------------------------------


def test_signal_intent_minimal_construction_defaults():
    intent = SignalIntent(
        ticker="BTCUSD", action=Side.BUY, order_type=OrderType.MARKET
    )
    assert intent.ticker == "BTCUSD"
    assert intent.action is Side.BUY
    # D-01: order_type is required (never None); entry_price defaults to None.
    assert intent.order_type is OrderType.MARKET
    assert intent.entry_price is None
    assert intent.stop_loss is None
    assert intent.take_profit is None
    # D-07: exit_fraction defaults to Decimal("1") — full exit is the default.
    assert intent.exit_fraction == Decimal("1")
    assert str(intent.exit_fraction) == "1"
    assert intent.quantity is None


def test_signal_intent_exit_fraction_partial_allowed():
    intent = SignalIntent(
        ticker="BTCUSD", action=Side.SELL, order_type=OrderType.MARKET,
        exit_fraction=Decimal("0.5")
    )
    assert intent.exit_fraction == Decimal("0.5")


def test_signal_intent_exit_fraction_above_one_raises():
    with pytest.raises(SizingPolicyViolation, match="exit_fraction"):
        SignalIntent(ticker="BTCUSD", action=Side.SELL,
                     order_type=OrderType.MARKET, exit_fraction=Decimal("1.5"))


def test_signal_intent_exit_fraction_zero_raises():
    with pytest.raises(SizingPolicyViolation, match="exit_fraction"):
        SignalIntent(ticker="BTCUSD", action=Side.SELL,
                     order_type=OrderType.MARKET, exit_fraction=Decimal("0"))


# ---------------------------------------------------------------------------
# Frozen/slots discipline — mutation raises, no attribute smuggling
# ---------------------------------------------------------------------------


def test_policy_dataclasses_are_frozen():
    policy = FractionOfCash(fraction=Decimal("0.95"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.fraction = Decimal("0.5")  # type: ignore[misc]
    fixed = FixedQuantity(qty=Decimal("2"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        fixed.qty = Decimal("3")  # type: ignore[misc]
    risk = RiskPercent(risk_pct=Decimal("0.02"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        risk.risk_pct = Decimal("0.03")  # type: ignore[misc]
    sltp = PercentFromFill(sl_pct=Decimal("0.05"), tp_pct=Decimal("0.10"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        sltp.sl_pct = Decimal("0.01")  # type: ignore[misc]
    intent = SignalIntent(
        ticker="BTCUSD", action=Side.BUY, order_type=OrderType.MARKET
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        intent.ticker = "ETHUSD"  # type: ignore[misc]


def test_policy_dataclasses_use_slots():
    assert not hasattr(FractionOfCash(fraction=Decimal("0.95")), "__dict__")
    assert not hasattr(
        SignalIntent(
            ticker="BTCUSD", action=Side.BUY, order_type=OrderType.MARKET
        ),
        "__dict__",
    )


# ---------------------------------------------------------------------------
# Union aliases — the dispatchable vocabulary (D-01/D-02)
# ---------------------------------------------------------------------------


def test_sizing_policy_union_members():
    # The resolver match-dispatches on exactly these kinds (D-01).
    assert SizingPolicy == FractionOfCash | FixedQuantity | RiskPercent


def test_sltp_policy_union_members():
    assert SLTPPolicy == PercentFromFill | PercentFromDecision

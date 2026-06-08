"""Sizing resolver tests: the ONE engine resolver (Plan 07-01, Task 3, D-01).

These lock the resolver contract BEFORE plan 07-05 swaps it into
``OrderManager._resolve_signal_quantity``:

1. **Byte-exactness (Pitfall 1, T-07-02):** the FractionOfCash arm reproduces
   the legacy expression ``(Decimal("0.95") * available) / to_money(price)``
   (order_manager.py:628) repr-exact — asserted with ``str(result)``
   comparisons, not just ``==`` (equal Decimals can differ in exponent).
2. **Structural no-ops:** ``step_size=None`` performs no quantize;
   ``exit_fraction == 1`` returns ``net_quantity`` unchanged (no
   multiplication artifact) — the golden path stays byte-exact (D-07).
3. **D-06 fail-loud:** RiskPercent without a usable stop raises
   ``SizingPolicyViolation`` naming the violation.
4. **D-05:** ``step_size`` quantizes the resolved quantity ROUND_DOWN;
   the exit dust guard takes the full position when the remainder would
   drop below ``step_size``.
"""

import uuid
from decimal import ROUND_DOWN, Decimal

import pytest

from itrader.core.ids import PortfolioId
from itrader.core.exceptions import SizingPolicyViolation
from itrader.core.money import to_money
from itrader.core.sizing import FixedQuantity, FractionOfCash, RiskPercent
from itrader.order_handler.sizing_resolver import SizingResolver

pytestmark = pytest.mark.unit


class _StubReadModel:
    """Minimal read model for the resolver: available_cash + total_equity only."""

    def __init__(
        self,
        available: Decimal = Decimal("10000.00"),
        equity: Decimal = Decimal("50000"),
    ):
        self._available = available
        self._equity = equity

    def available_cash(self, portfolio_id: PortfolioId) -> Decimal:
        return self._available

    def total_equity(self, portfolio_id: PortfolioId) -> Decimal:
        return self._equity


_PID = PortfolioId(uuid.uuid4())


def _resolver(
    available: Decimal = Decimal("10000.00"), equity: Decimal = Decimal("50000")
) -> SizingResolver:
    return SizingResolver(_StubReadModel(available=available, equity=equity))


# ---------------------------------------------------------------------------
# FractionOfCash — byte-exact against the M1 seam (Pitfall 1, T-07-02)
# ---------------------------------------------------------------------------


def test_fraction_of_cash_reproduces_legacy_expression_repr_exact():
    # The golden arm: SAME operands, SAME order as order_manager.py:628 —
    # (Decimal("0.95") * available) / to_money(price). str() equality is the
    # byte-exactness bar (Pitfall 1: == would accept a different exponent).
    available = Decimal("10000.00")
    price = to_money(40.0)
    result = _resolver(available=available).resolve_entry(
        FractionOfCash(fraction=Decimal("0.95")), _PID, price, None
    )
    legacy = (Decimal("0.95") * available) / to_money(40.0)
    assert str(result) == str(legacy)


def test_fraction_of_cash_repr_exact_non_terminating_division():
    # A realistic non-terminating division: full 28-digit context precision
    # must survive untouched (D-01: no quantize on intermediates).
    available = Decimal("10000.00")
    price = to_money(41.0)
    result = _resolver(available=available).resolve_entry(
        FractionOfCash(fraction=Decimal("0.95")), _PID, price, None
    )
    legacy = (Decimal("0.95") * available) / to_money(41.0)
    assert str(result) == str(legacy)


def test_fraction_of_cash_step_size_none_is_structural_noop():
    # step_size=None: the resolved value is NOT touched (repr unchanged).
    available = Decimal("10000.00")
    price = to_money(41.0)
    result = _resolver(available=available).resolve_entry(
        FractionOfCash(fraction=Decimal("0.95"), step_size=None), _PID, price, None
    )
    untouched = (Decimal("0.95") * available) / to_money(41.0)
    assert str(result) == str(untouched)


def test_fraction_of_cash_step_size_quantizes_round_down():
    # D-05: step_size quantizes the resolved quantity ROUND_DOWN.
    available = Decimal("10000.00")
    price = to_money(41.0)
    result = _resolver(available=available).resolve_entry(
        FractionOfCash(fraction=Decimal("0.95"), step_size=Decimal("0.001")),
        _PID,
        price,
        None,
    )
    raw = (Decimal("0.95") * available) / to_money(41.0)
    expected = raw.quantize(Decimal("0.001"), rounding=ROUND_DOWN)
    assert str(result) == str(expected)
    # Spot-check the hand value: 9500.0000 / 41.0 = 231.7073170731... -> 231.707
    assert result == Decimal("231.707")


# ---------------------------------------------------------------------------
# FixedQuantity — returned as declared, cash-independent
# ---------------------------------------------------------------------------


def test_fixed_quantity_returns_qty_regardless_of_cash():
    result = _resolver(available=Decimal("1.00")).resolve_entry(
        FixedQuantity(qty=Decimal("2.5")), _PID, to_money(40000.0), None
    )
    assert result == Decimal("2.5")
    assert str(result) == "2.5"


def test_fixed_quantity_step_size_quantizes_round_down():
    result = _resolver().resolve_entry(
        FixedQuantity(qty=Decimal("2.5557"), step_size=Decimal("0.01")),
        _PID,
        to_money(100.0),
        None,
    )
    assert str(result) == "2.55"  # ROUND_DOWN, never up


# ---------------------------------------------------------------------------
# WR-02: step_size snaps to the step VALUE (multiples), not its Decimal exponent
# ---------------------------------------------------------------------------


def test_step_size_half_grid_snaps_to_multiples_of_half():
    # step=0.5: 2.3 must snap DOWN to 2.0 (a multiple of 0.5), NOT to the 0.1
    # grid the old exponent-based quantize would have produced (which left 2.3).
    result = _resolver().resolve_entry(
        FixedQuantity(qty=Decimal("2.3"), step_size=Decimal("0.5")),
        _PID,
        to_money(100.0),
        None,
    )
    assert result == Decimal("2.0")


def test_step_size_integer_step_snaps_to_multiples():
    # step=5: 13 must snap DOWN to 10 (a multiple of 5), NOT stay at 13 (the
    # integer grid the exponent of "5" — which is 0 — would have produced).
    result = _resolver().resolve_entry(
        FixedQuantity(qty=Decimal("13"), step_size=Decimal("5")),
        _PID,
        to_money(100.0),
        None,
    )
    assert result == Decimal("10")


def test_step_size_trailing_zero_repr_uses_step_value_not_exponent():
    # step="0.010" has exponent -3 but a VALUE of 0.01: 2.567 must snap to the
    # 0.01 grid (2.56), NOT the 0.001 grid the stored exponent would imply.
    result = _resolver().resolve_entry(
        FixedQuantity(qty=Decimal("2.567"), step_size=Decimal("0.010")),
        _PID,
        to_money(100.0),
        None,
    )
    assert result == Decimal("2.56")


def test_exit_step_size_half_grid_snaps_to_multiples_of_half():
    # resolve_exit must use the same step-value semantics: 7 * 0.333 = 2.331,
    # remainder 4.669 >= 0.5 -> quantize 2.331 DOWN to 2.0 (multiple of 0.5).
    result = _resolver().resolve_exit(
        Decimal("7"), Decimal("0.333"), Decimal("0.5")
    )
    assert result == Decimal("2.0")


# ---------------------------------------------------------------------------
# RiskPercent — Van Tharp: (equity * risk_pct) / |price - stop|
# ---------------------------------------------------------------------------


def test_risk_percent_van_tharp_sizing():
    # (50000 * 0.02) / |100 - 95| = 1000.00 / 5 = 200
    result = _resolver(equity=Decimal("50000")).resolve_entry(
        RiskPercent(risk_pct=Decimal("0.02")),
        _PID,
        Decimal("100"),
        Decimal("95"),
    )
    assert result == Decimal("200")


def test_risk_percent_short_side_stop_above_price():
    # abs() makes the distance side-agnostic: |100 - 105| = 5 -> same size.
    result = _resolver(equity=Decimal("50000")).resolve_entry(
        RiskPercent(risk_pct=Decimal("0.02")),
        _PID,
        Decimal("100"),
        Decimal("105"),
    )
    assert result == Decimal("200")


def test_risk_percent_missing_stop_raises():
    # D-06 fail-loud: RiskPercent without a stop cannot size.
    with pytest.raises(SizingPolicyViolation, match="RiskPercent requires stop_loss"):
        _resolver().resolve_entry(
            RiskPercent(risk_pct=Decimal("0.02")), _PID, Decimal("100"), None
        )


def test_risk_percent_stop_equal_to_price_raises():
    # Zero stop distance -> division by zero -> a policy violation, not a crash.
    with pytest.raises(SizingPolicyViolation, match="RiskPercent requires stop_loss"):
        _resolver().resolve_entry(
            RiskPercent(risk_pct=Decimal("0.02")), _PID, Decimal("100"), Decimal("100")
        )


# ---------------------------------------------------------------------------
# resolve_exit — D-07 structural no-op + dust guard
# ---------------------------------------------------------------------------


def test_exit_full_fraction_returns_net_quantity_unchanged():
    # D-07 golden path: exit_fraction == 1 skips the multiply ENTIRELY — the
    # returned value's repr is identical (no multiplication artifact).
    net = Decimal("1.23456789")
    result = _resolver().resolve_exit(net, Decimal("1"), None)
    assert str(result) == str(net)


def test_exit_full_fraction_no_exponent_artifact():
    # A trailing-zero quantity keeps its exponent: 2.50 stays "2.50",
    # never "2.500" or "2.5" (which a multiply by 1 could produce).
    net = Decimal("2.50")
    result = _resolver().resolve_exit(net, Decimal("1"), None)
    assert str(result) == "2.50"


def test_exit_partial_fraction_multiplies():
    net = Decimal("2.4")
    result = _resolver().resolve_exit(net, Decimal("0.5"), None)
    assert result == net * Decimal("0.5")
    assert str(result) == str(net * Decimal("0.5"))


def test_exit_remainder_below_step_takes_full_position():
    # Dust guard: post-exit remainder 0.00050 < step 0.001 -> exit takes all.
    net = Decimal("1.0")
    result = _resolver().resolve_exit(net, Decimal("0.9995"), Decimal("0.001"))
    assert str(result) == str(net)


def test_exit_partial_with_step_quantizes_round_down():
    # sized = 10 * 0.333 = 3.330; remainder 6.670 >= 0.01 -> quantize down.
    result = _resolver().resolve_exit(Decimal("10"), Decimal("0.333"), Decimal("0.01"))
    assert str(result) == "3.33"

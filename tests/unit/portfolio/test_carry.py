"""Borrow-interest days-basis / accrual formula (CARRY-01) — Phase 3 Plan 03-05.

CARRY-01: borrow-interest accrual derives its days-basis from the bar's BUSINESS
time (never wall clock — determinism), and the per-bar carry debit is computed in
Decimal end-to-end. The `borrow_interest` accrual itself is also exercised by
`tests/unit/portfolio/test_cash_manager.py`; this module is the dedicated home for
the days-basis / accrual-formula cases. Folder-derived `unit` marker only
(tests/conftest.py applies it; no decorator here).
"""

from datetime import datetime, timedelta
from decimal import Decimal

import uuid_utils.compat as uuid_compat

from itrader.config import PortfolioConfig, get_portfolio_preset
from itrader.outils.dict_merge import recursive_merge
from itrader.core.enums import CashOperationType
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.position import Position
from itrader.portfolio_handler.transaction import Transaction, TransactionType
from tests.support.venue_wiring import compute_account


def _margin_config(max_leverage: str = "10") -> PortfolioConfig:
    """enable_margin=True config — borrow-carry lives on the margin leaf, which
    01-03 selects at construction (not via post-construction update_config)."""
    return PortfolioConfig.model_validate(recursive_merge(
        get_portfolio_preset("default").model_dump(),
        {"trading_rules": {"enable_margin": True, "max_leverage": Decimal(max_leverage)}},
    ))


_TICKER = "SYNTH"
_PORTFOLIO_ID = "pf-carry"


class _StubInstrument:
    """Minimal Instrument stand-in exposing borrow_rate."""

    def __init__(self, borrow_rate: Decimal) -> None:
        self.borrow_rate = borrow_rate


class _StubUniverse:
    """Minimal Universe read-model: instrument(ticker) -> _StubInstrument."""

    def __init__(self, borrow_rate: Decimal) -> None:
        self._instrument = _StubInstrument(borrow_rate)

    def instrument(self, symbol: str) -> _StubInstrument:
        return self._instrument


def _portfolio(cash: Decimal = Decimal("100000")) -> Portfolio:
    return Portfolio(
        name="carry-pf", exchange="paper",
        cash=cash, time=datetime(2024, 1, 1), config=_margin_config(),
        account=compute_account(cash, enable_margin=True),
    )


def _open_short(portfolio: Portfolio, *, entry_date: datetime,
                size: Decimal, price: Decimal) -> Position:
    """Insert an OPEN short of |size| at `price`, entered at `entry_date`."""
    sell = Transaction(
        entry_date, TransactionType.SELL, _TICKER, price, size, 0,
        _PORTFOLIO_ID, id=1, fill_id=uuid_compat.uuid7(),
    )
    position = Position.open_position(sell)
    portfolio.position_manager._storage.set_position(_TICKER, position)
    return position


def test_days_basis_one_day_gap_accrues_one_day():
    """days basis == 1 (Decimal) for a one-day bar gap; carry = 1×close×|size|×rate/365."""
    pf = _portfolio()
    entry = datetime(2024, 1, 1)
    _open_short(pf, entry_date=entry, size=Decimal("2"), price=Decimal("100"))
    universe = _StubUniverse(Decimal("0.10"))

    bar_time = entry + timedelta(days=1)
    balance_before = pf.account.balance
    pf.update_market_value_of_portfolio({_TICKER: Decimal("100")}, bar_time, universe)

    # days == 1: 1 × 100 × 2 × 0.10 / 365
    expected = Decimal("1") * Decimal("100") * Decimal("2") * Decimal("0.10") / Decimal("365")
    assert pf.account.balance == balance_before - expected


def test_days_basis_three_day_gap_accrues_three_days():
    """A 3-day gap → days == 3 (Decimal) → 3× the one-day carry."""
    pf = _portfolio()
    entry = datetime(2024, 1, 1)
    _open_short(pf, entry_date=entry, size=Decimal("2"), price=Decimal("100"))
    universe = _StubUniverse(Decimal("0.10"))

    bar_time = entry + timedelta(days=3)
    balance_before = pf.account.balance
    pf.update_market_value_of_portfolio({_TICKER: Decimal("100")}, bar_time, universe)

    expected = Decimal("3") * Decimal("100") * Decimal("2") * Decimal("0.10") / Decimal("365")
    assert pf.account.balance == balance_before - expected


def test_borrow_interest_op_uses_bar_business_time_not_wall_clock():
    """The BORROW_INTEREST op timestamp is the bar business time (determinism)."""
    pf = _portfolio()
    entry = datetime(2024, 1, 1)
    _open_short(pf, entry_date=entry, size=Decimal("2"), price=Decimal("100"))
    universe = _StubUniverse(Decimal("0.10"))

    bar_time = entry + timedelta(days=1)
    pf.update_market_value_of_portfolio({_TICKER: Decimal("100")}, bar_time, universe)

    ops = pf.account.get_cash_operations(
        operation_type=CashOperationType.BORROW_INTEREST
    )
    assert len(ops) == 1
    assert ops[0].timestamp == bar_time


def test_borrow_interest_determinism_double_run_identical():
    """Two identical runs produce byte-identical carry amounts AND timestamps."""
    def run():
        pf = _portfolio()
        entry = datetime(2024, 1, 1)
        _open_short(pf, entry_date=entry, size=Decimal("2"), price=Decimal("100"))
        universe = _StubUniverse(Decimal("0.10"))
        bar_time = entry + timedelta(days=1)
        pf.update_market_value_of_portfolio({_TICKER: Decimal("100")}, bar_time, universe)
        op = pf.account.get_cash_operations(
            operation_type=CashOperationType.BORROW_INTEREST
        )[0]
        return op.amount, op.timestamp, pf.account.balance

    assert run() == run()


def test_short_absent_from_prices_defers_carry_and_does_not_advance_clock():
    """CR-01: a short whose ticker is absent from a bar's `prices` must NOT
    accrue carry on its stale mark AND must NOT advance its accrual clock — the
    next priced bar then accrues the FULL elapsed interval at the correct price.

    Fails before the fix: the absent-ticker bar would book carry on the stale
    opening price (100) for days 1, consuming the clock, so the day-2 priced bar
    would only accrue a single day at 120 instead of the full two-day interval.
    """
    pf = _portfolio()
    entry = datetime(2024, 1, 1)
    _open_short(pf, entry_date=entry, size=Decimal("2"), price=Decimal("100"))
    universe = _StubUniverse(Decimal("0.10"))

    balance_before = pf.account.balance

    # Day 1: a bar that does NOT carry _TICKER's price (sparse/gap bar). The
    # short's current_price stays the stale opening mark (100). No carry must
    # accrue and the clock must NOT advance.
    bar_day1 = entry + timedelta(days=1)
    pf.update_market_value_of_portfolio({"OTHER": Decimal("999")}, bar_day1, universe)

    # No BORROW_INTEREST op booked on the absent-ticker bar.
    ops_after_day1 = pf.account.get_cash_operations(
        operation_type=CashOperationType.BORROW_INTEREST
    )
    assert ops_after_day1 == []
    assert pf.account.balance == balance_before

    # Day 2: a priced bar at the CORRECT mark (120). Because the clock never
    # advanced past the entry, the full TWO-day interval accrues here at 120.
    bar_day2 = entry + timedelta(days=2)
    pf.update_market_value_of_portfolio({_TICKER: Decimal("120")}, bar_day2, universe)

    ops_after_day2 = pf.account.get_cash_operations(
        operation_type=CashOperationType.BORROW_INTEREST
    )
    assert len(ops_after_day2) == 1
    # Full 2-day interval at the correct price 120 (not 1 day, not on stale 100).
    expected = Decimal("2") * Decimal("120") * Decimal("2") * Decimal("0.10") / Decimal("365")
    assert ops_after_day2[0].amount == expected
    assert ops_after_day2[0].timestamp == bar_day2
    assert pf.account.balance == balance_before - expected


def test_zero_current_price_skips_carry():
    """WR-03: a non-positive current_price never produces a financing debit.

    A short marked to 0 (degenerate/unset mark) present in `prices` must be
    skipped by the explicit `current_price <= 0` guard rather than booking a
    zero/wrong carry op.
    """
    pf = _portfolio()
    entry = datetime(2024, 1, 1)
    _open_short(pf, entry_date=entry, size=Decimal("2"), price=Decimal("100"))
    universe = _StubUniverse(Decimal("0.10"))

    balance_before = pf.account.balance
    bar_time = entry + timedelta(days=1)
    # Mark the short to zero this tick (ticker IS present, so it is re-marked).
    pf.update_market_value_of_portfolio({_TICKER: Decimal("0")}, bar_time, universe)

    ops = pf.account.get_cash_operations(
        operation_type=CashOperationType.BORROW_INTEREST
    )
    assert ops == []
    assert pf.account.balance == balance_before

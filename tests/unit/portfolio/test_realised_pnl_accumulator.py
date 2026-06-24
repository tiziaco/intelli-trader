"""Equivalence drift-lock for the PERF-02 running realised-PnL accumulator (D-03).

PERF-02 (Phase 3) replaced the per-bar dual open+closed re-sum in
``PositionManager.get_total_realized_pnl`` with an O(1) running accumulator
(``_realised_pnl_accumulator``) fed the realised increment from the Portfolio close
funnel (both settle arms — see ``03-INVARIANT-AUDIT.md``).

This test is the dedicated equivalence regression test (D-03): it drives a non-trivial
mix (open / scale-in / partial close / full close) through ``Portfolio.process_transaction``
— the ONLY path that feeds the accumulator (a bare ``PositionManager`` bypasses the
funnel) — and asserts after every closing fill that the accumulator equals an independent
oracle ``_resum_realised`` reproducing the PRIOR dual-loop full re-sum exactly. Value-equality
``==`` is criterion #2's contract (D-05): same ``Decimal('0.00')`` seed, no mid-sum quantize,
so the running total is byte-identical to the prior re-sum, not merely numerically equal.

The byte-exact SMA_MACD oracle + the determinism double-run are the run-path drift locks; this
test is the unit-level drift lock. No hot-path runtime re-sum guard is added (D-03) — that would
re-pay the O(positions) cost this phase removes.
"""

from datetime import datetime
from decimal import Decimal

import uuid_utils.compat as uuid_compat
import pytest

from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.position.position_manager import PositionManager
from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader import idgen


@pytest.fixture
def portfolio():
    """A fresh simulated portfolio funded with $150000 (mirrors test_portfolio.py)."""
    return Portfolio(1, "test_pf", "simulated", 150000, datetime.now())


def _resum_realised(pm: PositionManager) -> Decimal:
    """Independent oracle: reproduce the PRIOR dual open+closed full re-sum exactly.

    Seeds Decimal('0.00') and sums position.realised_pnl over the open positions then the
    closed positions — the exact loop get_total_realized_pnl ran before PERF-02 (D-03/D-05).
    """
    total = Decimal('0.00')
    for position in pm.get_all_positions().values():
        total += position.realised_pnl
    for position in pm.get_closed_positions():
        total += position.realised_pnl
    return total


def _buy(ticker: str, price: float, qty: float) -> Transaction:
    return Transaction(
        datetime.now(), TransactionType.BUY, ticker, price, qty, 0, None,
        idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )


def _sell(ticker: str, price: float, qty: float) -> Transaction:
    return Transaction(
        datetime.now(), TransactionType.SELL, ticker, price, qty, 0, None,
        idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )


def test_empty_portfolio_accumulator_is_zero(portfolio):
    """A fresh portfolio's accumulator seeds Decimal('0.00') — matches the prior empty re-sum (D-05)."""
    pm = portfolio.position_manager
    assert pm._realised_pnl_accumulator == Decimal('0.00')
    assert pm._realised_pnl_accumulator == _resum_realised(pm)


def test_accumulator_equals_full_resum_across_open_scalein_partial_full(portfolio):
    """D-03 drift lock: accumulator == fresh full re-sum through the Portfolio funnel.

    Drives open -> scale-in -> partial close -> full close via process_transaction (the
    only path that feeds the accumulator) and asserts value-equality (==) against the
    independent dual-loop oracle after every closing fill, plus on the (zero-increment)
    open/scale-in fills.
    """
    pm = portfolio.position_manager

    # OPEN: buy 2 BTC @ $38000 (realised_pnl unchanged -> increment 0).
    portfolio.process_transaction(_buy("BTCUSDT", 38000, 2))
    assert pm._realised_pnl_accumulator == _resum_realised(pm)

    # SCALE-IN: buy 1 BTC @ $40000 (same-side add -> realised_pnl unchanged -> increment 0).
    portfolio.process_transaction(_buy("BTCUSDT", 40000, 1))
    assert pm._realised_pnl_accumulator == _resum_realised(pm)

    # PARTIAL CLOSE: sell 1 BTC @ $45000 (position still open; open list carries realised).
    portfolio.process_transaction(_sell("BTCUSDT", 45000, 1))
    assert len(portfolio.positions) == 1
    assert pm._realised_pnl_accumulator == _resum_realised(pm)

    # FULL CLOSE: sell the remaining 2 BTC @ $46000 (moves the position to _closed_positions).
    portfolio.process_transaction(_sell("BTCUSDT", 46000, 2))
    assert len(portfolio.positions) == 0
    assert len(portfolio.closed_positions) == 1
    assert pm._realised_pnl_accumulator == _resum_realised(pm)

    # Final sanity: the public read-property routes through the accumulator and equals the oracle.
    assert portfolio.total_realised_pnl == _resum_realised(pm)

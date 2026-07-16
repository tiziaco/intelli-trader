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

from datetime import datetime, timezone
from decimal import Decimal

import uuid_utils.compat as uuid_compat
import pytest

from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.position.position_manager import PositionManager
from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader.config import PortfolioConfig, get_portfolio_preset
from itrader.outils.dict_merge import recursive_merge
from itrader import idgen


def _margin_config(max_leverage: str = "10") -> PortfolioConfig:
    """enable_margin=True config — 01-03 selects the account leaf at construction,
    so margin must be set in the constructor config (update_config no longer
    rebuilds the leaf)."""
    return PortfolioConfig.model_validate(recursive_merge(
        get_portfolio_preset("default").model_dump(),
        {"trading_rules": {"enable_margin": True, "max_leverage": Decimal(max_leverage)}},
    ))


# IN-01: a fixed business timestamp (not wall-clock datetime.now()) for the
# determinism convention — the project threads business time, never wall clock.
# tz-aware UTC for timezone consistency. The timestamp does not affect
# realised_pnl, so this is convention-alignment, not a correctness change.
_FIXED_TIME = datetime(2024, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def portfolio():
    """A fresh simulated portfolio funded with $150000 (mirrors test_portfolio.py)."""
    # IN-02: Decimal cash (money is Decimal end-to-end); IN-01: fixed timestamp.
    return Portfolio("test_pf", "simulated", Decimal("150000"), _FIXED_TIME)


@pytest.fixture
def margin_portfolio():
    """A $150000 portfolio with enable_margin=True (lock-and-settle on, WR-02)."""
    return Portfolio(
        "margin_pf", "simulated", Decimal("150000"), _FIXED_TIME,
        config=_margin_config(),
    )


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


def _buy(ticker: str, price, qty, leverage=None) -> Transaction:
    # IN-01: fixed business timestamp; IN-02: Decimal money inputs at call sites.
    txn = Transaction(
        _FIXED_TIME, TransactionType.BUY, ticker, price, qty, Decimal("0"), None,
        idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )
    if leverage is not None:
        txn.leverage = Decimal(str(leverage))
    return txn


def _sell(ticker: str, price, qty, leverage=None) -> Transaction:
    # IN-01: fixed business timestamp; IN-02: Decimal money inputs at call sites.
    txn = Transaction(
        _FIXED_TIME, TransactionType.SELL, ticker, price, qty, Decimal("0"), None,
        idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )
    if leverage is not None:
        txn.leverage = Decimal(str(leverage))
    return txn


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
    portfolio.process_transaction(_buy("BTCUSDT", Decimal("38000"), Decimal("2")))
    assert pm._realised_pnl_accumulator == _resum_realised(pm)

    # SCALE-IN: buy 1 BTC @ $40000 (same-side add -> realised_pnl unchanged -> increment 0).
    portfolio.process_transaction(_buy("BTCUSDT", Decimal("40000"), Decimal("1")))
    assert pm._realised_pnl_accumulator == _resum_realised(pm)

    # PARTIAL CLOSE: sell 1 BTC @ $45000 (position still open; open list carries realised).
    portfolio.process_transaction(_sell("BTCUSDT", Decimal("45000"), Decimal("1")))
    assert len(portfolio.positions) == 1
    assert pm._realised_pnl_accumulator == _resum_realised(pm)

    # FULL CLOSE: sell the remaining 2 BTC @ $46000 (moves the position to _closed_positions).
    portfolio.process_transaction(_sell("BTCUSDT", Decimal("46000"), Decimal("2")))
    assert len(portfolio.positions) == 0
    assert len(portfolio.closed_positions) == 1
    assert pm._realised_pnl_accumulator == _resum_realised(pm)

    # Final sanity: the public read-property routes through the accumulator and equals the oracle.
    assert portfolio.total_realised_pnl == _resum_realised(pm)


def test_accumulator_equals_resum_margin_open_partial_full(margin_portfolio):
    """WR-02: margin settle arm equivalence — the more complex partial/full-close
    economics on _process_transaction_margin has its own apply_realised_increment
    wiring. Drive open -> partial close -> full close on a levered position and
    assert the accumulator equals the dual-loop re-sum after every closing fill.
    """
    pf = margin_portfolio
    pm = pf.position_manager

    # OPEN: long 4 BTC @ 50000, L=5 -> lock = 200000/5 = 40000 (within 150000 bp).
    pf.process_transaction(_buy("BTCUSDT", Decimal("50000"), Decimal("4"), leverage=5))
    assert pm._realised_pnl_accumulator == _resum_realised(pm)

    # PARTIAL CLOSE: sell 1 BTC @ 55000 (position still open; realised changes).
    pf.process_transaction(_sell("BTCUSDT", Decimal("55000"), Decimal("1"), leverage=5))
    assert len(pf.positions) == 1
    assert pm._realised_pnl_accumulator == _resum_realised(pm)

    # FULL CLOSE: sell the remaining 3 BTC @ 60000 (moves to closed list).
    pf.process_transaction(_sell("BTCUSDT", Decimal("60000"), Decimal("3"), leverage=5))
    assert len(pf.positions) == 0
    assert len(pf.closed_positions) == 1
    assert pm._realised_pnl_accumulator == _resum_realised(pm)
    assert pf.total_realised_pnl == _resum_realised(pm)


def test_accumulator_equals_resum_short_lifecycle_spot(portfolio):
    """WR-02: SHORT lifecycle equivalence — the SHORT realised_pnl property takes a
    different branch (position.py). Sell to open, buy to cover through the spot
    funnel; assert the accumulator equals the re-sum after the covering close.
    """
    pm = portfolio.position_manager

    # OPEN SHORT: sell 2 BTC @ 45000 (realised unchanged on open -> increment 0).
    portfolio.process_transaction(_sell("BTCUSDT", Decimal("45000"), Decimal("2")))
    assert len(portfolio.positions) == 1
    assert portfolio.positions["BTCUSDT"].side.name == "SHORT"
    assert pm._realised_pnl_accumulator == _resum_realised(pm)

    # PARTIAL COVER: buy 1 BTC @ 42000 (short still open; realised changes).
    portfolio.process_transaction(_buy("BTCUSDT", Decimal("42000"), Decimal("1")))
    assert len(portfolio.positions) == 1
    assert pm._realised_pnl_accumulator == _resum_realised(pm)

    # FULL COVER: buy the remaining 1 BTC @ 40000 (covers to flat).
    portfolio.process_transaction(_buy("BTCUSDT", Decimal("40000"), Decimal("1")))
    assert len(portfolio.positions) == 0
    assert len(portfolio.closed_positions) == 1
    assert pm._realised_pnl_accumulator == _resum_realised(pm)
    assert portfolio.total_realised_pnl == _resum_realised(pm)


def test_accumulator_equals_resum_two_tickers_interleaved(portfolio):
    """WR-02: multi-ticker equivalence — a per-ticker desync would not show on a
    single-ticker re-sum. Interleave two tickers and assert the accumulator equals
    the cross-ticker re-sum after each close.
    """
    pm = portfolio.position_manager

    # Open BTC and ETH.
    portfolio.process_transaction(_buy("BTCUSDT", Decimal("38000"), Decimal("1")))
    portfolio.process_transaction(_buy("ETHUSDT", Decimal("2000"), Decimal("10")))
    assert pm._realised_pnl_accumulator == _resum_realised(pm)

    # Close BTC fully (ETH still open — the re-sum must count BTC's closed realised
    # plus ETH's open realised; a per-ticker desync would diverge here).
    portfolio.process_transaction(_sell("BTCUSDT", Decimal("42000"), Decimal("1")))
    assert len(portfolio.positions) == 1
    assert pm._realised_pnl_accumulator == _resum_realised(pm)

    # Close ETH fully.
    portfolio.process_transaction(_sell("ETHUSDT", Decimal("2500"), Decimal("10")))
    assert len(portfolio.positions) == 0
    assert len(portfolio.closed_positions) == 2
    assert pm._realised_pnl_accumulator == _resum_realised(pm)
    assert portfolio.total_realised_pnl == _resum_realised(pm)

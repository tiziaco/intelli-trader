"""
Test suite for PositionManager class.
Tests position lifecycle, calculations, risk management, and thread safety.
"""

import threading
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
import uuid_utils.compat as uuid_compat

from itrader.portfolio_handler.position.position_manager import (
    PositionManager,
    PositionMetrics,
)
from itrader.portfolio_handler.position import Position
from itrader.portfolio_handler.transaction import Transaction
from itrader.core.enums import PositionSide, TransactionType, PositionEvent
from itrader.core.exceptions import (
    InvalidTransactionError,
    PositionCalculationError,
)
from itrader import idgen


class MockPortfolio:
    """Mock portfolio for testing."""

    def __init__(self):
        self.portfolio_id = idgen.generate_portfolio_id()


@pytest.fixture
def env():
    """A PositionManager on a mock portfolio + sample BUY/SELL transactions."""
    portfolio = MockPortfolio()
    position_manager = PositionManager(portfolio)

    buy_transaction = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker="BTCUSDT",
        price=50000.0, quantity=1.0, commission=25.0,
        portfolio_id=portfolio.portfolio_id, id=idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )
    sell_transaction = Transaction(
        time=datetime.now(), type=TransactionType.SELL, ticker="BTCUSDT",
        price=52000.0, quantity=0.5, commission=13.0,
        portfolio_id=portfolio.portfolio_id, id=idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )
    return SimpleNamespace(
        portfolio=portfolio,
        position_manager=position_manager,
        buy_transaction=buy_transaction,
        sell_transaction=sell_transaction,
    )


def test_position_manager_initialization(env):
    """Test PositionManager initialization."""
    pm = env.position_manager
    assert len(pm.get_all_positions()) == 0
    assert len(pm.get_closed_positions()) == 0
    assert pm.max_total_positions == 100
    assert pm.max_position_value == Decimal("1000000.00")


def test_create_new_position_buy(env):
    """Test creating a new position with BUY transaction."""
    pm = env.position_manager
    position = pm.process_position_update(env.buy_transaction)

    assert position is not None
    assert position.ticker == "BTCUSDT"
    assert position.side == PositionSide.LONG
    assert position.net_quantity == 1.0
    assert position.avg_price == 50025.0  # Price + commission per unit

    assert len(pm.get_all_positions()) == 1
    assert "BTCUSDT" in pm.get_all_positions()


def test_create_new_position_sell(env):
    """Test creating a new position with SELL transaction."""
    sell_first_transaction = Transaction(
        time=datetime.now(), type=TransactionType.SELL, ticker="ETHUSDT",
        price=3000.0, quantity=2.0, commission=15.0,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )

    position = env.position_manager.process_position_update(sell_first_transaction)

    assert position is not None
    assert position.ticker == "ETHUSDT"
    assert position.side == PositionSide.SHORT
    assert position.net_quantity == 2.0


def test_update_existing_position(env):
    """Test updating an existing position."""
    pm = env.position_manager
    initial_position = pm.process_position_update(env.buy_transaction)
    initial_quantity = initial_position.net_quantity

    buy_more_transaction = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker="BTCUSDT",
        price=51000.0, quantity=0.5, commission=12.5,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )

    updated_position = pm.process_position_update(buy_more_transaction)

    # Should be the same position object
    assert initial_position.id == updated_position.id
    # net_quantity is Decimal end-to-end (M2a); add Decimal, not float.
    assert updated_position.net_quantity == initial_quantity + Decimal("0.5")

    assert len(pm.get_all_positions()) == 1


def test_close_position_exact_match(env):
    """Test closing a position with exact quantity match."""
    pm = env.position_manager
    pm.process_position_update(env.buy_transaction)

    close_transaction = Transaction(
        time=datetime.now(), type=TransactionType.SELL, ticker="BTCUSDT",
        price=52000.0, quantity=1.0, commission=26.0,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )

    position = pm.process_position_update(close_transaction)

    assert not position.is_open
    assert len(pm.get_all_positions()) == 0
    assert len(pm.get_closed_positions()) == 1


def test_partial_position_close(env):
    """Test partial position closing."""
    pm = env.position_manager
    pm.process_position_update(env.buy_transaction)

    position = pm.process_position_update(env.sell_transaction)

    assert position.is_open
    assert position.net_quantity == 0.5  # 1.0 - 0.5
    assert len(pm.get_all_positions()) == 1
    assert len(pm.get_closed_positions()) == 0


def test_position_value_limits(env):
    """Test position value limits validation."""
    small_transaction = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker="SMALLCOIN",
        price=1.0, quantity=5.0, commission=0.0,  # Value 5.0 < minimum 10.0
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )

    with pytest.raises(InvalidTransactionError) as exc_info:
        env.position_manager.process_position_update(small_transaction)

    assert "below minimum" in str(exc_info.value)


def test_maximum_positions_limit(env):
    """Test maximum positions limit."""
    pm = env.position_manager
    pm.max_total_positions = 2

    for i in range(2):
        transaction = Transaction(
            time=datetime.now(), type=TransactionType.BUY, ticker=f"COIN{i}USDT",
            price=1000.0, quantity=1.0, commission=5.0,
            portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
        )
        pm.process_position_update(transaction)

    excess_transaction = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker="COIN3USDT",
        price=1000.0, quantity=1.0, commission=5.0,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )

    with pytest.raises(InvalidTransactionError) as exc_info:
        pm.process_position_update(excess_transaction)

    assert "Maximum" in str(exc_info.value)


def test_update_market_values(env):
    """Test updating position market values."""
    pm = env.position_manager
    pm.process_position_update(env.buy_transaction)

    new_prices = {"BTCUSDT": 55000.0}
    timestamp = datetime.now()

    pm.update_position_market_values(new_prices, timestamp)

    updated_position = pm.get_position("BTCUSDT")
    assert updated_position.current_price == 55000.0
    assert updated_position.current_time == timestamp


def test_get_position_methods(env):
    """Test various position retrieval methods."""
    pm = env.position_manager
    pm.process_position_update(env.buy_transaction)

    eth_transaction = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker="ETHUSDT",
        price=3000.0, quantity=2.0, commission=15.0,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )
    pm.process_position_update(eth_transaction)

    btc_position = pm.get_position("BTCUSDT")
    assert btc_position is not None
    assert btc_position.ticker == "BTCUSDT"

    all_positions = pm.get_all_positions()
    assert len(all_positions) == 2
    assert "BTCUSDT" in all_positions
    assert "ETHUSDT" in all_positions

    assert pm.get_position_count() == 2


def test_total_calculations(env):
    """Test total market value and P&L calculations."""
    pm = env.position_manager
    pm.process_position_update(env.buy_transaction)

    new_prices = {"BTCUSDT": 52000.0}
    pm.update_position_market_values(new_prices, datetime.now())

    total_market_value = pm.get_total_market_value()
    total_unrealized_pnl = pm.get_total_unrealized_pnl()

    assert total_market_value > 0
    assert total_unrealized_pnl > 0  # Price increased


def test_position_metrics_calculation(env):
    """Test position metrics calculation."""
    pm = env.position_manager
    position = pm.process_position_update(env.buy_transaction)
    position_id = position.id

    close_transaction = Transaction(
        time=datetime.now() + timedelta(days=1), type=TransactionType.SELL,
        ticker="BTCUSDT", price=52000.0, quantity=1.0, commission=26.0,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )

    pm.process_position_update(close_transaction)

    metrics = pm.calculate_position_metrics(position_id)

    assert metrics is not None
    assert metrics.position_id == position_id
    assert metrics.ticker == "BTCUSDT"
    assert metrics.holding_period_days == 1
    assert metrics.total_pnl > 0  # Should be profitable


def test_portfolio_concentration(env):
    """Test portfolio concentration calculation."""
    pm = env.position_manager
    btc_transaction = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker="BTCUSDT",
        price=50000.0, quantity=1.0, commission=25.0,  # Value: 50,000
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )
    eth_transaction = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker="ETHUSDT",
        price=3000.0, quantity=5.0, commission=15.0,  # Value: 15,000
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )

    pm.process_position_update(btc_transaction)
    pm.process_position_update(eth_transaction)

    concentration = pm.get_portfolio_concentration()

    assert len(concentration) == 2
    assert "BTCUSDT" in concentration
    assert "ETHUSDT" in concentration

    # BTC should have higher concentration
    assert concentration["BTCUSDT"] > concentration["ETHUSDT"]


def test_position_limits_validation(env):
    """Test position limits validation."""
    pm = env.position_manager
    assert pm.validate_position_limits(env.buy_transaction)

    large_transaction = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker="BTCUSDT",
        price=100000.0, quantity=15.0, commission=25.0,  # Value 1.5M > 1M limit
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )

    assert not pm.validate_position_limits(large_transaction)


def test_positions_summary(env):
    """Test comprehensive positions summary."""
    pm = env.position_manager
    pm.process_position_update(env.buy_transaction)

    short_transaction = Transaction(
        time=datetime.now(), type=TransactionType.SELL, ticker="ETHUSDT",
        price=3000.0, quantity=1.0, commission=15.0,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )
    pm.process_position_update(short_transaction)

    close_short = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker="ETHUSDT",
        price=2900.0, quantity=1.0, commission=14.5,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )
    pm.process_position_update(close_short)

    summary = pm.get_positions_summary()

    assert summary["active_positions"] == 1
    assert summary["closed_positions"] == 1
    assert "total_market_value" in summary
    assert "concentration" in summary
    assert "positions_by_side" in summary


def test_close_all_positions(env):
    """Test emergency close all positions."""
    pm = env.position_manager
    positions_data = [
        ("BTCUSDT", 50000.0, 1.0),
        ("ETHUSDT", 3000.0, 2.0),
        ("ADAUSDT", 1.0, 1000.0),
    ]

    for ticker, price, quantity in positions_data:
        transaction = Transaction(
            time=datetime.now(), type=TransactionType.BUY, ticker=ticker,
            price=price, quantity=quantity, commission=10.0,
            portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
        )
        pm.process_position_update(transaction)

    assert len(pm.get_all_positions()) == 3

    current_prices = {"BTCUSDT": 52000.0, "ETHUSDT": 3200.0, "ADAUSDT": 1.1}

    closed_positions = pm.close_all_positions(current_prices, datetime.now())

    assert len(closed_positions) == 3
    assert len(pm.get_all_positions()) == 0
    assert len(pm.get_closed_positions()) == 3


def test_concurrent_position_updates(env):
    """Test thread safety with concurrent position updates."""
    pm = env.position_manager
    results = []
    errors = []

    def update_position_thread(thread_id):
        try:
            transaction = Transaction(
                time=datetime.now(), type=TransactionType.BUY, ticker=f"COIN{thread_id}USDT",
                price=1000.0, quantity=1.0, commission=5.0,
                portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
            )
            results.append(pm.process_position_update(transaction))
        except Exception as e:
            errors.append(e)

    threads = []
    for i in range(10):
        thread = threading.Thread(target=update_position_thread, args=(i,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    assert len(errors) == 0, f"Concurrent update errors: {errors}"
    assert len(results) == 10
    assert len(pm.get_all_positions()) == 10


def test_concurrent_same_ticker_updates(env):
    """Test thread safety with concurrent updates to same ticker."""
    pm = env.position_manager
    results = []
    errors = []

    def update_same_ticker_thread(thread_id):
        try:
            transaction = Transaction(
                time=datetime.now(), type=TransactionType.BUY, ticker="TESTTICKER",
                price=1000.0 + thread_id, quantity=0.1, commission=1.0,
                portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
            )
            results.append(pm.process_position_update(transaction))
        except Exception as e:
            errors.append(e)

    threads = []
    for i in range(5):
        thread = threading.Thread(target=update_same_ticker_thread, args=(i,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    assert len(errors) == 0, f"Concurrent same ticker errors: {errors}"
    assert len(results) == 5

    # Should have only one position for the ticker
    assert len(pm.get_all_positions()) == 1

    # Position should have accumulated quantity
    position = pm.get_position("TESTTICKER")
    assert position.net_quantity == 0.5  # 5 * 0.1


def test_precision_calculations(env):
    """Test high precision calculations."""
    precise_transaction = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker="PRECISIONTEST",
        price=33333.33333333, quantity=0.33333333, commission=5.55555555,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )

    position = env.position_manager.process_position_update(precise_transaction)

    assert position is not None
    assert position.ticker == "PRECISIONTEST"

    # Values should be calculated with proper precision
    assert position.avg_price > 0
    assert position.net_quantity > 0


# ---------------------------------------------------------------------------
# One-leverage-per-position + aggregate notional (Plan 02-04 Task 2 — D-06/D-11)
# ---------------------------------------------------------------------------


def _levered_buy(ticker, price, quantity, commission, leverage, portfolio_id):
    """A BUY transaction carrying a signal leverage (margin-mode input)."""
    txn = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker=ticker,
        price=price, quantity=quantity, commission=commission,
        portfolio_id=portfolio_id, id=idgen.generate_transaction_id(),
        fill_id=uuid_compat.uuid7(),
    )
    txn.leverage = Decimal(str(leverage))
    return txn


def test_one_leverage_set_at_open(env):
    """D-06: a position opened with leverage L stores leverage == L."""
    pm = env.position_manager
    txn = _levered_buy("BTCUSDT", 50000.0, 1.0, 25.0, 5, env.portfolio.portfolio_id)

    position = pm.process_position_update(txn)

    assert position.leverage == Decimal("5")


def test_spot_position_defaults_to_leverage_one(env):
    """A position opened from a transaction WITHOUT a leverage attribute
    defaults to Decimal('1') (spot byte-exact — the spot path never sets it)."""
    pm = env.position_manager
    # env.buy_transaction carries no leverage attribute.
    position = pm.process_position_update(env.buy_transaction)

    assert position.leverage == Decimal("1")


def test_scale_in_margin_clamps_to_position_leverage(env):
    """D-06: a scale-in carrying a DIFFERENT signal leverage keeps the
    position at its open leverage (the position's L is unchanged — clamp)."""
    pm = env.position_manager
    open_txn = _levered_buy("BTCUSDT", 50000.0, 1.0, 25.0, 5, env.portfolio.portfolio_id)
    position = pm.process_position_update(open_txn)
    assert position.leverage == Decimal("5")

    # Scale in with a differing leverage (L=10) — must be clamped to 5.
    scale_in = _levered_buy("BTCUSDT", 51000.0, 0.5, 12.5, 10, env.portfolio.portfolio_id)
    updated = pm.process_position_update(scale_in)

    assert updated.id == position.id
    assert updated.leverage == Decimal("5")  # clamped, NOT 10
    assert updated.net_quantity == Decimal("1.5")


def test_aggregate_notional_matches_net_quantity_times_avg_price(env):
    """aggregate_notional = net_quantity × avg_price (direction-aware, mirrors
    the absolute market_value shape) — the basis for locked_margin = notional / L."""
    pm = env.position_manager
    position = pm.process_position_update(env.buy_transaction)

    expected = abs(position.net_quantity) * position.avg_price
    assert position.aggregate_notional == expected
    assert position.aggregate_notional > 0


def test_aggregate_notional_short_is_positive(env):
    """A SHORT position reports a POSITIVE aggregate notional (the margin basis
    is a magnitude, mirroring abs(market_value))."""
    pm = env.position_manager
    short_txn = Transaction(
        time=datetime.now(), type=TransactionType.SELL, ticker="ETHUSDT",
        price=3000.0, quantity=2.0, commission=15.0,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(),
        fill_id=uuid_compat.uuid7(),
    )

    position = pm.process_position_update(short_txn)

    assert position.side == PositionSide.SHORT
    assert position.aggregate_notional == abs(position.net_quantity) * position.avg_price
    assert position.aggregate_notional > 0


def test_position_manager_holds_no_cash_manager(env):
    """OQ2: PositionManager stays cash-agnostic — no CashManager reference."""
    pm = env.position_manager
    assert not hasattr(pm, "cash_manager")
    # The only injected seam is the state storage.
    assert pm._storage is not None


def test_partial_close_margin_keeps_position_leverage(env):
    """A partial close does not alter the position's one leverage (D-06): the
    margin release/settle pro-rata is driven from Portfolio.process_transaction
    in Task 3; the position simply preserves its open leverage through close."""
    pm = env.position_manager
    open_txn = _levered_buy("BTCUSDT", 50000.0, 1.0, 25.0, 4, env.portfolio.portfolio_id)
    position = pm.process_position_update(open_txn)

    partial_close = Transaction(
        time=datetime.now(), type=TransactionType.SELL, ticker="BTCUSDT",
        price=52000.0, quantity=0.5, commission=13.0,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(),
        fill_id=uuid_compat.uuid7(),
    )
    updated = pm.process_position_update(partial_close)

    assert updated.is_open
    assert updated.net_quantity == Decimal("0.5")
    assert updated.leverage == Decimal("4")


# ---------------------------------------------------------------------------
# Phase 3 Wave 0 stub (SHORT-03) — collectible RED placeholder.
# Seeded by Plan 03-02 so the Plan 03-04 `short_pnl` verify selector selects
# >=1 test BEFORE any production code is written (D-10). Asserts NOTHING yet —
# Plan 03-04 turns it green.
# ---------------------------------------------------------------------------


def test_short_pnl_realised_is_size_times_entry_minus_exit(env):
    """SHORT-03/D-08: a closed short computes first-class realised PnL via the
    existing PositionSide.SHORT branch: |size| × (entry − exit) net of
    commissions. CONFIRM-ONLY — no production change; position.py:182-190 is
    already first-class. Entry (avg_sold) 3000, exit (avg_bought) 2800, size 2:
    gross = (3000 − 2800) × 2 = 400; net = 400 − sell_comm − buy_comm."""
    pm = env.position_manager
    # Open the short: SELL 2 @ 3000 (avg_sold = 3000), commission 15.
    open_short = Transaction(
        time=datetime.now(), type=TransactionType.SELL, ticker="ETHUSDT",
        price=3000.0, quantity=2.0, commission=15.0,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(),
        fill_id=uuid_compat.uuid7(),
    )
    position = pm.process_position_update(open_short)
    assert position.side == PositionSide.SHORT

    # Cover the short: BUY 2 @ 2800 (avg_bought = 2800, price fell → profit).
    cover = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker="ETHUSDT",
        price=2800.0, quantity=2.0, commission=14.0,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(),
        fill_id=uuid_compat.uuid7(),
    )
    closed = pm.process_position_update(cover)

    # SHORT realised branch (position.py:186-190):
    #   (avg_sold − avg_bought) * buy_quantity
    #     − (buy_quantity / sell_quantity) * sell_commission
    #     − buy_commission
    gross = (Decimal("3000") - Decimal("2800")) * Decimal("2")  # |size|×(entry−exit)
    expected = (
        gross
        - (Decimal("2") / Decimal("2")) * Decimal("15.0")
        - Decimal("14.0")
    )
    assert closed.realised_pnl == expected
    assert gross == Decimal("400")  # |size| × (entry − exit), profit on a fall


def test_short_pnl_unrealised_is_avg_minus_current_times_net(env):
    """SHORT-03/D-08: an OPEN short marks unrealised PnL via the SHORT branch
    (avg_price − current_price) × net_quantity (position.py:203-204). Entry
    3000, mark 2800: a price FALL is a SHORT profit."""
    pm = env.position_manager
    short_txn = Transaction(
        time=datetime.now(), type=TransactionType.SELL, ticker="ETHUSDT",
        price=3000.0, quantity=2.0, commission=15.0,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(),
        fill_id=uuid_compat.uuid7(),
    )
    position = pm.process_position_update(short_txn)
    assert position.side == PositionSide.SHORT

    pm.update_position_market_values({"ETHUSDT": 2800.0}, datetime.now())
    marked = pm.get_position("ETHUSDT")

    expected = (marked.avg_price - marked.current_price) * marked.net_quantity
    assert marked.unrealised_pnl == expected
    # A price fall on a short is a profit.


# --- PERF-08 (Req 1 / D-04): single-pass fused valuation equivalence ---------


def _build_mixed_positions(env):
    """A representative multi-position set (mix of LONG/SHORT, varied prices),
    marked to current prices. Returns the PositionManager."""
    pm = env.position_manager

    # LONG BTC (from the env buy_transaction) — entry 50000, qty 1.0
    pm.process_position_update(env.buy_transaction)

    # LONG ETH — entry 3000, qty 2.0
    eth_long = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker="ETHUSDT",
        price=3000.0, quantity=2.0, commission=15.0,
        portfolio_id=env.portfolio.portfolio_id,
        id=idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )
    pm.process_position_update(eth_long)

    # SHORT SOL — entry 150, qty 10.0
    sol_short = Transaction(
        time=datetime.now(), type=TransactionType.SELL, ticker="SOLUSDT",
        price=150.0, quantity=10.0, commission=5.0,
        portfolio_id=env.portfolio.portfolio_id,
        id=idgen.generate_transaction_id(), fill_id=uuid_compat.uuid7(),
    )
    pm.process_position_update(sol_short)

    # Mark all three to varied current prices.
    pm.update_position_market_values(
        {"BTCUSDT": 52000.0, "ETHUSDT": 2800.0, "SOLUSDT": 160.0},
        datetime.now(),
    )
    return pm


def test_fusion_equivalence_market_value(env):
    """PERF-08/D-04: the fused get_total_market_value() equals a separate
    reference loop, Decimal byte-identical (same Decimal('0.00') seed + += order)."""
    pm = _build_mixed_positions(env)

    reference = Decimal('0.00')
    for position in pm._storage.get_positions().values():
        reference += position.market_value

    fused = pm.get_total_market_value()
    assert fused == reference
    assert str(fused) == str(reference)  # byte-identical Decimal repr


def test_fusion_equivalence_unrealized(env):
    """PERF-08/D-04: the fused get_total_unrealized_pnl() equals the reference
    sum of position.unrealised_pnl, byte-identical."""
    pm = _build_mixed_positions(env)

    reference = Decimal('0.00')
    for position in pm._storage.get_positions().values():
        reference += position.unrealised_pnl

    fused = pm.get_total_unrealized_pnl()
    assert fused == reference
    assert str(fused) == str(reference)


def test_fusion_margin_basis(env):
    """PERF-08/D-04: the fused pass's locked-margin basis equals the reference
    sum of position.aggregate_notional, byte-identical."""
    pm = _build_mixed_positions(env)

    reference = Decimal('0.00')
    for position in pm._storage.get_positions().values():
        reference += position.aggregate_notional

    _mv, _pnl, basis = pm._fused_valuation()
    assert basis == reference
    assert str(basis) == str(reference)


def test_fusion_empty_portfolio(env):
    """PERF-08: with no positions both accessors return Decimal('0.00') and the
    fused basis is Decimal('0.00')."""
    pm = env.position_manager
    assert pm.get_total_market_value() == Decimal('0.00')
    assert pm.get_total_unrealized_pnl() == Decimal('0.00')
    mv, pnl, basis = pm._fused_valuation()
    assert mv == Decimal('0.00')
    assert pnl == Decimal('0.00')
    assert basis == Decimal('0.00')
    assert marked.unrealised_pnl > 0

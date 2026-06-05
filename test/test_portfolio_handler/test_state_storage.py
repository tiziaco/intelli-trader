"""M2-08 tests: unified PortfolioStateStorage seam (ABC + in-memory backend + factory).

Phase 3 (M2b) Plan 03-07, Task 1. These assert the storage-seam behavior the wave
delivers, generalizing the proven ``order_handler/storage/`` pattern to portfolio state:

  * ``PortfolioStateStorageFactory.create("backtest"|"test")`` returns the in-memory backend.
  * ``create("live")`` raises (D-sql deferred); ``create("bogus")`` raises ``ValueError``.
  * The backend round-trips all four managers' containers: open/closed positions,
    pending/history transactions, reserved cash + cash operations, metrics snapshots.
  * After routing, the four managers hold NO state containers of their own — they read
    and write through the injected seam (asserted via container identity).

NOTE (03-08): this file MOVES with the test tree into ``tests/unit/test_portfolio_handler/``
during the 03-08 type-split — 03-08 reconciles it there without duplication.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from itrader.portfolio_handler.storage import (
    PortfolioStateStorage,
    InMemoryPortfolioStateStorage,
    PortfolioStateStorageFactory,
)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def test_factory_backtest_returns_in_memory():
    """M2-08: create('backtest') returns the in-memory backend (mirrors order seam)."""
    backend = PortfolioStateStorageFactory.create("backtest")
    assert isinstance(backend, InMemoryPortfolioStateStorage)
    assert isinstance(backend, PortfolioStateStorage)


def test_factory_test_environment_returns_in_memory():
    """M2-08: create('test') also returns the in-memory backend."""
    backend = PortfolioStateStorageFactory.create("test")
    assert isinstance(backend, InMemoryPortfolioStateStorage)


def test_factory_is_case_insensitive():
    """M2-08: the environment string is lower-cased before dispatch."""
    backend = PortfolioStateStorageFactory.create("BACKTEST")
    assert isinstance(backend, InMemoryPortfolioStateStorage)


def test_factory_live_raises():
    """M2-08: live backend is deferred to D-sql — must raise, not return a stub."""
    with pytest.raises((NotImplementedError, ValueError)):
        PortfolioStateStorageFactory.create("live")


def test_factory_unknown_environment_raises_value_error():
    """M2-08: an unsupported environment raises ValueError with the supported list."""
    with pytest.raises(ValueError) as exc:
        PortfolioStateStorageFactory.create("bogus")
    assert "backtest" in str(exc.value)


# ---------------------------------------------------------------------------
# Round-trip through the backend
# ---------------------------------------------------------------------------

def test_positions_round_trip():
    """M2-08: open and closed positions round-trip through the seam."""
    backend = InMemoryPortfolioStateStorage()
    sentinel_open = object()
    sentinel_closed = object()

    backend.set_position("BTCUSDT", sentinel_open)
    assert backend.get_position("BTCUSDT") is sentinel_open
    assert backend.get_positions() == {"BTCUSDT": sentinel_open}

    backend.remove_position("BTCUSDT")
    assert backend.get_position("BTCUSDT") is None

    backend.add_closed_position(sentinel_closed)
    assert backend.get_closed_positions() == [sentinel_closed]


def test_transactions_round_trip():
    """M2-08: pending and history transactions round-trip through the seam."""
    backend = InMemoryPortfolioStateStorage()
    ctx = object()
    txn = object()

    backend.set_pending_transaction("txn-1", ctx)
    assert backend.get_pending_transactions() == {"txn-1": ctx}
    backend.remove_pending_transaction("txn-1")
    assert backend.get_pending_transactions() == {}

    backend.add_transaction(txn)
    assert backend.get_transaction_history() == [txn]


def test_cash_ops_and_reserved_round_trip():
    """M2-08: reserved cash (working state) + cash operations (history) round-trip."""
    backend = InMemoryPortfolioStateStorage()

    assert backend.get_reserved_cash() == Decimal("0.00")
    backend.set_reserved_cash(Decimal("123.45"))
    assert backend.get_reserved_cash() == Decimal("123.45")

    op = object()
    backend.add_cash_operation(op)
    assert backend.get_cash_operations() == [op]


def test_snapshots_round_trip():
    """M2-08: metrics snapshots (append-only history) round-trip through the seam."""
    backend = InMemoryPortfolioStateStorage()
    snap = object()
    backend.add_snapshot(snap)
    assert backend.get_snapshots() == [snap]


def test_snapshots_replaceable_for_size_trim():
    """M2-08: snapshot list is replaceable so the manager can trim to max_snapshots."""
    backend = InMemoryPortfolioStateStorage()
    for i in range(5):
        backend.add_snapshot(i)
    backend.set_snapshots([3, 4])
    assert backend.get_snapshots() == [3, 4]


# ---------------------------------------------------------------------------
# Managers no longer own their containers — they route through the seam
# ---------------------------------------------------------------------------

@pytest.fixture
def portfolio():
    from itrader.portfolio_handler.portfolio import Portfolio
    return Portfolio(
        user_id=1,
        name="Seam Test",
        exchange="binance",
        cash=Decimal("100000.00"),
        time=datetime(2020, 1, 1),
    )


def test_portfolio_injects_state_storage(portfolio):
    """M2-08: Portfolio owns a single injected PortfolioStateStorage seam."""
    assert isinstance(portfolio.state_storage, PortfolioStateStorage)


def test_managers_share_the_injected_seam(portfolio):
    """M2-08: all four managers read/write the SAME injected backend (no private copies)."""
    seam = portfolio.state_storage
    # Positions written through the position manager are visible in the seam.
    seam.set_position("ETHUSDT", "marker")
    assert portfolio.position_manager.get_position("ETHUSDT") == "marker"


def test_position_manager_has_no_owned_containers(portfolio):
    """M2-08: PositionManager no longer owns _positions / _closed_positions."""
    pm = portfolio.position_manager
    assert not hasattr(pm, "_positions")
    assert not hasattr(pm, "_closed_positions")


def test_transaction_manager_has_no_owned_containers(portfolio):
    """M2-08: TransactionManager no longer owns _pending_transactions / _transaction_history."""
    tm = portfolio.transaction_manager
    assert not hasattr(tm, "_pending_transactions")
    assert not hasattr(tm, "_transaction_history")


def test_cash_manager_has_no_owned_containers(portfolio):
    """M2-08: CashManager no longer owns _reserved_cash / _cash_operations."""
    cm = portfolio.cash_manager
    assert not hasattr(cm, "_reserved_cash")
    assert not hasattr(cm, "_cash_operations")


def test_metrics_manager_has_no_owned_containers(portfolio):
    """M2-08: MetricsManager no longer owns _snapshots."""
    mm = portfolio.metrics_manager
    assert not hasattr(mm, "_snapshots")


def test_reserved_cash_routes_through_seam(portfolio):
    """M2-08: reserving cash is observable through the injected seam."""
    portfolio.cash_manager.reserve_cash(Decimal("500.00"), "test reserve", "ref-1")
    assert portfolio.state_storage.get_reserved_cash() == Decimal("500.00")
    assert portfolio.cash_manager.reserved_balance == Decimal("500.00")

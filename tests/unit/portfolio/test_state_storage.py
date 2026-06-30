"""M2-08 tests: unified PortfolioStateStorage seam (ABC + in-memory backend + factory).

Phase 3 (M2b) Plan 03-07, Task 1. These assert the storage-seam behavior the wave
delivers, generalizing the proven ``order_handler/storage/`` pattern to portfolio state:

  * ``PortfolioStateStorageFactory.create("backtest"|"test")`` returns the in-memory backend.
  * ``create("live")`` with no portfolio_id and ``create("bogus")`` raise ``ConfigurationError``
    (WR-04 — typed exception parity with the sibling Order/Signal factories).
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

from itrader.core.exceptions import ConfigurationError
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
    """M2-08 / WR-04: live arm with no portfolio_id raises the typed ConfigurationError."""
    with pytest.raises(ConfigurationError):
        PortfolioStateStorageFactory.create("live")


def test_factory_unknown_environment_raises_configuration_error():
    """M2-08 / WR-04: an unsupported environment raises ConfigurationError with the supported list.

    Now a typed ``ConfigurationError`` (matching the sibling Order/Signal factories) rather
    than a bare ``ValueError`` — see CLAUDE.md error-handling convention.
    """
    with pytest.raises(ConfigurationError) as exc:
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
    """M2-08/05-05: transaction history round-trips through the seam.

    The pending-transaction working state died with the saga machinery
    (Plan 05-05 D-11) — only the append-only history remains.
    """
    backend = InMemoryPortfolioStateStorage()
    txn = object()

    backend.add_transaction(txn)
    assert backend.get_transaction_history() == [txn]

    # No pending-transaction surface survives anywhere on the backend.
    assert not [a for a in dir(backend) if "pending" in a.lower()]


def test_cash_ops_and_reserved_round_trip():
    """M2-08/05-03: per-reference reservations + cash operations round-trip."""
    backend = InMemoryPortfolioStateStorage()

    assert backend.get_reserved_cash() == Decimal("0.00")
    backend.add_reservation("ref-a", Decimal("123.45"))
    backend.add_reservation("ref-b", Decimal("0.55"))
    assert backend.get_reserved_cash() == Decimal("124.00")

    assert backend.pop_reservation("ref-a") == Decimal("123.45")
    assert backend.pop_reservation("ref-a") is None  # idempotent
    assert backend.get_reserved_cash() == Decimal("0.55")

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
# PERF-01 / D-01 / D-03: copy-free getters (object-identity regression locks)
# ---------------------------------------------------------------------------
# Each getter now returns the LIVE internal container (no per-tick .copy())
# under the D-19 single-writer contract. The deterministic proof is object
# identity: two calls return the SAME object — which would be False if the
# getter still copied. No wall-clock benchmark (D-01 rejects benchmarks).


def test_get_positions_returns_live_container_no_copy():
    """D-03: get_positions() returns the live dict (identity) — no .copy()."""
    backend = InMemoryPortfolioStateStorage()
    backend.set_position("BTCUSD", object())
    assert backend.get_positions() is backend.get_positions()


def test_get_closed_positions_returns_live_container_no_copy():
    """D-03: get_closed_positions() returns the live list (identity) — no .copy()."""
    backend = InMemoryPortfolioStateStorage()
    backend.add_closed_position(object())
    assert backend.get_closed_positions() is backend.get_closed_positions()


def test_get_transaction_history_returns_live_container_no_copy():
    """D-03: get_transaction_history() returns the live list (identity) — no .copy()."""
    backend = InMemoryPortfolioStateStorage()
    backend.add_transaction(object())
    assert backend.get_transaction_history() is backend.get_transaction_history()


def test_get_cash_operations_returns_live_container_no_copy():
    """D-03: get_cash_operations() returns the live list (identity) — no .copy()."""
    backend = InMemoryPortfolioStateStorage()
    backend.add_cash_operation(object())
    assert backend.get_cash_operations() is backend.get_cash_operations()


def test_get_snapshots_returns_value_equal_copy():
    """D-03: get_snapshots() is the ONE accessor that copies — it returns a NEW
    materialized list each call (value-equal, NOT object-identical), diverging
    from the four sibling "return the live container" accessors.

    Rationale (D-03): snapshots are stored in a bounded ``deque(maxlen)`` that
    auto-evicts on append; handing out the live deque is a mutation-during-
    iteration hazard, and the ``List[Any]`` ABC contract (a deque raises on
    slices) requires a list. So this accessor returns ``list(self._snapshots)``.
    """
    backend = InMemoryPortfolioStateStorage()
    snap = object()
    backend.add_snapshot(snap)
    # Value-equal contents...
    assert backend.get_snapshots() == [snap]
    # ...but a fresh object each call (the intentional copy, not the live deque).
    assert backend.get_snapshots() is not backend.get_snapshots()


def test_snapshots_bounded_deque_retains_last_n():
    """D-03 (T5): a run exceeding max_snapshots retains exactly the last
    max_snapshots; the oldest are auto-evicted by the deque maxlen (the per-bar
    trim block in MetricsManager is gone — the maxlen IS the trim)."""
    max_snapshots = 3
    k = 4  # push max_snapshots + k beyond the bound
    backend = InMemoryPortfolioStateStorage(max_snapshots=max_snapshots)
    for i in range(max_snapshots + k):
        backend.add_snapshot(i)
    # Exactly max_snapshots retained, oldest evicted.
    assert backend.snapshot_count() == max_snapshots
    snaps = backend.get_snapshots()
    assert len(snaps) == max_snapshots
    # The newest is the last pushed; the oldest retained is the (k+1)-th pushed.
    assert backend.get_latest_snapshot() == max_snapshots + k - 1
    assert snaps[0] == k
    assert snaps == [k, k + 1, k + 2]


def test_snapshot_count_and_latest():
    """D-06: count-only / last-only accessors replace the per-tick whole-list copy.

    Empty state: snapshot_count() == 0, get_latest_snapshot() is None.
    Two-element state: snapshot_count() == 2, get_latest_snapshot() is the last.
    """
    backend = InMemoryPortfolioStateStorage()
    assert backend.snapshot_count() == 0
    assert backend.get_latest_snapshot() is None

    s1, s2 = object(), object()
    backend.add_snapshot(s1)
    backend.add_snapshot(s2)
    assert backend.snapshot_count() == 2
    assert backend.get_latest_snapshot() is s2  # last-only, no whole-list copy


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
    cm = portfolio.account
    assert not hasattr(cm, "_reserved_cash")
    assert not hasattr(cm, "_cash_operations")


def test_metrics_manager_has_no_owned_containers(portfolio):
    """M2-08: MetricsManager no longer owns _snapshots."""
    mm = portfolio.metrics_manager
    assert not hasattr(mm, "_snapshots")


def test_reserved_cash_routes_through_seam(portfolio):
    """M2-08: reserving cash is observable through the injected seam."""
    portfolio.account.reserve("ref-1", Decimal("500.00"))
    assert portfolio.state_storage.get_reserved_cash() == Decimal("500.00")
    assert portfolio.account.reserved_balance == Decimal("500.00")

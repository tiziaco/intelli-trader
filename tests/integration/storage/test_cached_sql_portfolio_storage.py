"""RETAIN-01/02/03 — ``CachedSqlPortfolioStateStorage`` write-through + read-through + rehydrate.

The live-only decorator wrapper (D-04) composes the untouched Phase-3
``SqlPortfolioStateStorage`` (system of record, bound ``portfolio_id``) with an in-memory
``InMemoryPortfolioStateStorage`` working set. This suite proves the five Phase-4 contracts:

* **Store-first write-through (Pitfall 8 / T-04-08)** — a mutating call persists to Postgres
  FIRST (visible to a fresh store bound to the same portfolio) then mirrors into the cache.
* **Read-through history split (D-02)** — closed positions / transaction history are NOT
  resident in the working set; they are served via read-through to the store.
* **Open-only rehydration (D-03)** — ``rehydrate()`` reloads open positions + reservations +
  locked margin + the account-state scalars, and NEVER replays closed positions /
  transactions / cash-ops into the working set.
* **Crash-after-emit accumulator equality (D-03 / A2)** — ``save_account_state`` persists the
  two purge-derived accumulators synchronously; after a crash a fresh wrapper's
  ``load_account_state()`` equals the persisted scalars and the open set rehydrates.
* **Cross-portfolio isolation (Pitfall 1 / V4 / T-04-03)** — a wrapper bound to A never sees
  anything written under B, on any read or rehydration.

Money lives on Postgres-native ``Numeric`` (exact Decimal), so the whole suite runs on the
``pg_backend`` (Postgres) arm and SKIPS cleanly without Docker (D-11). Each test binds a fresh
``uuid7`` portfolio so rows never leak across tests sharing the session container. 4-space
indentation; NO ``__init__.py`` in this dir (package-less ``tests`` convention).
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import uuid_utils.compat as uc
from sqlalchemy import text

from itrader.core.enums import CashOperationType, PositionSide, TransactionType
from itrader.core.ids import PositionId, TransactionId
from itrader.portfolio_handler.cash.cash_manager import CashOperation
from itrader.portfolio_handler.position.position import Position
from itrader.portfolio_handler.storage.cached_sql_storage import (
    CachedSqlPortfolioStateStorage,
)
from itrader.portfolio_handler.storage.sql_storage import SqlPortfolioStateStorage
from itrader.portfolio_handler.transaction.transaction import Transaction

_T0 = datetime(2021, 6, 1, tzinfo=timezone.utc)
_T1 = datetime(2021, 6, 5, tzinfo=timezone.utc)
_T2 = datetime(2021, 6, 9, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- fixtures
# The seven portfolio tables the ``wrapper`` fixture builds via ``create_all`` on the shared
# session container (child tables irrelevant — CASCADE handles any FK).
_PORTFOLIO_TABLES = (
    "cash_operations",
    "cash_reservations",
    "equity_snapshots",
    "locked_margin",
    "positions",
    "transactions",
    "portfolio_account_state",
)


@pytest.fixture(autouse=True)
def _drop_operational_portfolio_tables(pg_backend):
    """Keep the shared session Postgres container pristine for sibling storage tests.

    The ``wrapper`` fixture builds the seven portfolio tables via ``create_all`` on the
    session-scoped container. This file sorts alphabetically BEFORE ``test_migrations.py``,
    whose ``alembic upgrade head`` would raise ``ProgrammingError`` on the pre-existing
    tables. Drop them in teardown (CASCADE covers any FK) so the container is left clean —
    the same pristine-container discipline ``test_migrations`` follows with its
    ``downgrade base``. Teardown runs before ``pg_backend`` disposes (LIFO), so the engine is
    still live.
    """
    yield
    with pg_backend.engine.begin() as conn:
        for table in _PORTFOLIO_TABLES:
            conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))


@pytest.fixture
def portfolio_id():
    """A fresh UUIDv7 portfolio id per test (no cross-test row leakage)."""
    return uc.uuid7()


@pytest.fixture
def wrapper(pg_backend, portfolio_id):
    """A ``CachedSqlPortfolioStateStorage`` wrapping a PG-backed store bound to ``portfolio_id``.

    Constructing the ``SqlPortfolioStateStorage`` registers the seven portfolio tables on
    ``pg_backend.metadata`` and creates them (idempotent). The explicit
    ``metadata.create_all`` makes the schema-provisioning step visible (D-09 — tests use
    create_all, never Alembic). ``pg_backend`` owns engine disposal (WR-03).
    """
    store = SqlPortfolioStateStorage(pg_backend, portfolio_id)
    pg_backend.metadata.create_all(pg_backend.engine)
    return CachedSqlPortfolioStateStorage(store)


# --------------------------------------------------------------------------- builders
def _open_long(portfolio_id):
    """A fully-populated OPEN long position."""
    position = Position(
        entry_date=_T0,
        ticker="BTCUSD",
        side=PositionSide.LONG,
        price=Decimal("30000.12345678"),
        buy_quantity=Decimal("1.5"),
        sell_quantity=Decimal("0"),
        avg_bought=Decimal("29500.55"),
        avg_sold=Decimal("0"),
        buy_commission=Decimal("12.34"),
        sell_commission=Decimal("0"),
        is_open=True,
        portfolio_id=portfolio_id,
        leverage=Decimal("2"),
    )
    position.update_current_price_time(Decimal("31000.99"), _T1)
    position._last_accrual_time = _T1
    return position


def _closed_short(portfolio_id):
    """A CLOSED short position (exit_date set, is_open=False)."""
    position = Position(
        entry_date=_T0,
        ticker="ETHUSD",
        side=PositionSide.SHORT,
        price=Decimal("2000.50"),
        buy_quantity=Decimal("0"),
        sell_quantity=Decimal("3"),
        avg_bought=Decimal("0"),
        avg_sold=Decimal("2050.25"),
        buy_commission=Decimal("0"),
        sell_commission=Decimal("5.55"),
        is_open=True,
        portfolio_id=portfolio_id,
        leverage=Decimal("3"),
    )
    position.close_position(Decimal("1980.10"), _T2)
    return position


def _transaction(portfolio_id):
    return Transaction(
        _T0,
        TransactionType.BUY,
        "BTCUSD",
        Decimal("30000.12345678"),
        Decimal("1.5"),
        Decimal("12.34"),
        portfolio_id,
        TransactionId(uc.uuid7()),
        fill_id=uc.uuid7(),
        position_id=PositionId(uc.uuid7()),
        leverage=Decimal("2"),
    )


def _cash_operation():
    return CashOperation(
        operation_id=uc.uuid7(),
        operation_type=CashOperationType.RESERVATION,
        amount=Decimal("1234.567890123"),
        timestamp=_T0,
        description="reserve order ORDER-1",
        fee=Decimal("0.50"),
        reference_id="ORDER-1",
        balance_before=Decimal("10000.00"),
        balance_after=Decimal("8765.432109877"),
    )


# --------------------------------------------------------------------------- write-through
def test_write_through_store_first(wrapper, pg_backend, portfolio_id):
    """A mutating call persists to Postgres FIRST, then mirrors into the cache (Pitfall 8)."""
    position = _open_long(portfolio_id)
    wrapper.set_position("BTCUSD", position)
    wrapper.add_reservation("ORDER-1", Decimal("500.00"))

    # Persisted in Postgres: a FRESH store bound to the same portfolio reads it back.
    fresh = SqlPortfolioStateStorage(pg_backend, portfolio_id)
    assert fresh.get_position("BTCUSD") is not None
    assert fresh.get_reserved_cash() == Decimal("500.00")

    # Resident in the working set (cache mirror).
    assert wrapper._cache.get_position("BTCUSD") is not None
    assert wrapper._cache._reservations["ORDER-1"] == Decimal("500.00")

    # The wrapper's own current-state reads (cache-only) agree.
    assert set(wrapper.get_positions()) == {"BTCUSD"}
    assert wrapper.get_reserved_cash() == Decimal("500.00")


# --------------------------------------------------------------------------- read-through
def test_read_through_history(wrapper, portfolio_id):
    """Closed positions / transactions are NOT resident; they read through to the store (D-02)."""
    closed = _closed_short(portfolio_id)
    transaction = _transaction(portfolio_id)
    wrapper.add_closed_position(closed)
    wrapper.add_transaction(transaction)

    # History is NOT mirrored into the working set.
    assert wrapper._cache.get_closed_positions() == []
    assert wrapper._cache.get_transaction_history() == []

    # ...but is served via read-through to the store.
    closed_positions = wrapper.get_closed_positions()
    history = wrapper.get_transaction_history()
    assert len(closed_positions) == 1
    assert closed_positions[0].ticker == "ETHUSD"
    assert len(history) == 1
    assert history[0] == transaction


# --------------------------------------------------------------------------- rehydration
def test_rehydrate_open_only(wrapper, pg_backend, portfolio_id):
    """``rehydrate()`` loads open state only — never closed / transactions / cash-ops (D-03)."""
    wrapper.set_position("BTCUSD", _open_long(portfolio_id))
    wrapper.add_closed_position(_closed_short(portfolio_id))
    wrapper.add_transaction(_transaction(portfolio_id))
    wrapper.add_reservation("ORDER-1", Decimal("500.00"))
    wrapper.add_locked_margin("POS-1", Decimal("250.00"))
    wrapper.add_cash_operation(_cash_operation())

    # A fresh wrapper (cold cache) rehydrates from the store.
    fresh = CachedSqlPortfolioStateStorage(
        SqlPortfolioStateStorage(pg_backend, portfolio_id)
    )
    fresh.rehydrate()

    # Open working state IS loaded.
    assert set(fresh._cache.get_positions()) == {"BTCUSD"}
    assert fresh._cache._reservations["ORDER-1"] == Decimal("500.00")
    assert fresh._cache._locked_margin["POS-1"] == Decimal("250.00")

    # History / audit is NEVER loaded into the working set.
    assert fresh._cache.get_closed_positions() == []
    assert fresh._cache.get_transaction_history() == []
    assert fresh._cache.get_cash_operations() == []

    # History is still reachable via read-through (it lives in the store).
    assert len(fresh.get_closed_positions()) == 1
    assert len(fresh.get_transaction_history()) == 1


# --------------------------------------------------------------------------- crash / accumulators
def test_crash_restart_accumulators(wrapper, pg_backend, portfolio_id):
    """``save_account_state`` survives a crash: a fresh wrapper reloads the scalars + open set."""
    wrapper.set_position("BTCUSD", _open_long(portfolio_id))
    wrapper.save_account_state(
        cash_balance=Decimal("8765.432109877"),
        realized_pnl=Decimal("123.450000001"),
        total_equity=Decimal("9999.99"),
        peak_equity=Decimal("10500.00"),
        open_positions_count=1,
        updated_time=_T1,
    )

    # Crash: drop the wrapper (and its warm cache) entirely.
    del wrapper

    fresh = CachedSqlPortfolioStateStorage(
        SqlPortfolioStateStorage(pg_backend, portfolio_id)
    )
    fresh.rehydrate()

    state = fresh.load_account_state()
    assert state is not None
    assert state["cash_balance"] == Decimal("8765.432109877")
    assert state["realized_pnl"] == Decimal("123.450000001")
    assert state["total_equity"] == Decimal("9999.99")
    assert state["peak_equity"] == Decimal("10500.00")
    assert state["open_positions_count"] == 1
    assert state["updated_time"] == _T1

    # The pre-crash open set is restored, byte-exact money.
    positions = fresh.get_positions()
    assert set(positions) == {"BTCUSD"}
    assert positions["BTCUSD"].current_price == Decimal("31000.99")


# --------------------------------------------------------------------------- isolation
def test_cross_portfolio_isolation(pg_backend, portfolio_id):
    """A wrapper bound to A never sees anything written under B (Pitfall 1 / V4 / T-04-03)."""
    other_id = uc.uuid7()
    wrapper_a = CachedSqlPortfolioStateStorage(
        SqlPortfolioStateStorage(pg_backend, portfolio_id)
    )
    wrapper_b = CachedSqlPortfolioStateStorage(
        SqlPortfolioStateStorage(pg_backend, other_id)
    )

    # Write the full surface under portfolio A.
    wrapper_a.set_position("BTCUSD", _open_long(portfolio_id))
    wrapper_a.add_reservation("ORDER-A", Decimal("500.00"))
    wrapper_a.add_locked_margin("POS-A", Decimal("250.00"))
    wrapper_a.save_account_state(
        cash_balance=Decimal("8765.43"),
        realized_pnl=Decimal("123.45"),
        total_equity=Decimal("9999.99"),
        peak_equity=Decimal("10500.00"),
        open_positions_count=1,
        updated_time=_T1,
    )

    # Portfolio B (a different bound id over the SAME backend) rehydrates and sees NONE of it.
    wrapper_b.rehydrate()
    assert wrapper_b.get_positions() == {}
    assert wrapper_b.get_reserved_cash() == Decimal("0")
    assert wrapper_b.get_locked_margin() == Decimal("0")
    assert wrapper_b.get_locked_margin_for("POS-A") == Decimal("0")
    assert wrapper_b.load_account_state() is None

    # And A still sees its own state (scoping is a filter, not a global wipe).
    wrapper_a.rehydrate()
    assert set(wrapper_a.get_positions()) == {"BTCUSD"}
    assert wrapper_a.get_reserved_cash() == Decimal("500.00")
    assert wrapper_a.get_locked_margin_for("POS-A") == Decimal("250.00")
    state_a = wrapper_a.load_account_state()
    assert state_a is not None
    assert state_a["cash_balance"] == Decimal("8765.43")

"""OPS-02 + OPS-04 — ``SqlPortfolioStateStorage`` six-table round-trip on Postgres.

The portfolio-state operational backend proves the four object-specific contracts the
plan calls out (research §Round-Trip Test Pattern + Pitfalls 1/2/3/7):

* **Six-collection round-trip** — positions (open + closed), transactions, cash
  reservations, locked margin, cash operations, equity snapshots.
* **Position PROJECTION equality (Pitfall 3)** — ``Position`` is a plain ``object`` with
  identity-only ``__eq__``, so the round-trip is asserted on ``to_dict()`` + ``id`` +
  ``leverage`` + ``_last_accrual_time``, NEVER ``obj2 == obj``.
* **Field-wise ``==`` (Pitfall 3)** — ``Transaction`` (msgspec), ``CashOperation`` /
  ``PortfolioSnapshot`` (@dataclass) round-trip ``obj2 == obj`` directly.
* **Bound-portfolio isolation (Pitfall 1, T-03-08)** — a backend bound to portfolio A
  returns NOTHING written under portfolio B; the bound ``portfolio_id`` is the boundary.
* **Exact-Decimal money (OPS-04, Pitfall 2)** — reservation / locked-margin amounts +
  position / transaction / snapshot money round-trip as exact ``Decimal`` at FULL precision.
  Money lives on Postgres-native ``Numeric``; SQLite would decay it to float, so the whole
  suite runs on the ``pg_backend`` (Postgres) arm only and SKIPS cleanly without Docker.
* **Stable append-only ordering (Pitfall 7)** — snapshots return in the per-portfolio
  ``seq`` insertion order even when timestamps tie.

The ``pg_backend`` fixture (Plan 03-01 conftest) disposes the shared engine in its
``finally`` (WR-03 / Pitfall 4); the tests never dispose it themselves. Each test binds a
FRESH ``uuid7`` portfolio so rows never leak across tests that share the session container.
4-space indentation; NO ``__init__.py`` in this dir (package-less ``tests`` convention).
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import uuid_utils.compat as uc

from itrader.core.enums import CashOperationType, PositionSide, TransactionType
from itrader.core.ids import PositionId, TransactionId
from itrader.portfolio_handler.account import CashOperation
from itrader.portfolio_handler.metrics.metrics_manager import PortfolioSnapshot
from itrader.portfolio_handler.position.position import Position
from itrader.portfolio_handler.storage.sql_storage import SqlPortfolioStateStorage
from itrader.portfolio_handler.transaction.transaction import Transaction

_T0 = datetime(2021, 6, 1, tzinfo=timezone.utc)
_T1 = datetime(2021, 6, 5, tzinfo=timezone.utc)
_T2 = datetime(2021, 6, 9, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- fixtures
@pytest.fixture
def portfolio_id():
    """A fresh UUIDv7 portfolio id per test (no cross-test row leakage)."""
    return uc.uuid7()


@pytest.fixture
def storage(pg_backend, portfolio_id):
    """A ``SqlPortfolioStateStorage`` bound to ``portfolio_id`` over the PG backend.

    The ``pg_backend`` fixture owns engine disposal (WR-03), so this fixture does NOT
    dispose — calling ``storage.dispose()`` would flush the shared pool early.
    """
    return SqlPortfolioStateStorage(pg_backend, portfolio_id)


# --------------------------------------------------------------------------- builders
def _open_long(portfolio_id):
    """A fully-populated OPEN long position with distinct current_time / accrual marker."""
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
    # Advance the live price/time so both current_time and the price round-trip distinctly.
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


def _snapshot(total_equity):
    return PortfolioSnapshot(
        timestamp=_T0,
        total_equity=Decimal(total_equity),
        cash_balance=Decimal("5000.00"),
        positions_value=Decimal("5000.12"),
        unrealized_pnl=Decimal("12.34"),
        realized_pnl=Decimal("0"),
        total_pnl=Decimal("12.34"),
        open_positions_count=1,
        portfolio_return=Decimal("0.0012"),
        benchmark_return=None,
    )


def _assert_position_projection_equal(got, expected):
    """Pitfall 3 — Position has identity-only ``__eq__``; assert on a projection."""
    assert got.to_dict() == expected.to_dict()
    assert got.id == expected.id
    assert got.leverage == expected.leverage
    assert got._last_accrual_time == expected._last_accrual_time


# --------------------------------------------------------------------------- positions
def test_open_position_round_trip_projection(storage, portfolio_id):
    position = _open_long(portfolio_id)
    storage.set_position("BTCUSD", position)

    got = storage.get_position("BTCUSD")
    assert got is not None
    _assert_position_projection_equal(got, position)

    # get_positions() keys by ticker.
    positions = storage.get_positions()
    assert set(positions) == {"BTCUSD"}
    _assert_position_projection_equal(positions["BTCUSD"], position)


def test_open_position_money_exact_decimal(storage, portfolio_id):
    position = _open_long(portfolio_id)
    storage.set_position("BTCUSD", position)
    got = storage.get_position("BTCUSD")

    # OPS-04 — money round-trips as exact Decimal at full precision (Postgres Numeric).
    assert isinstance(got.current_price, Decimal)
    assert got.current_price == position.current_price
    assert got.avg_bought == position.avg_bought
    assert got.buy_quantity == position.buy_quantity
    assert got.buy_commission == position.buy_commission
    assert got.leverage == position.leverage


def test_set_position_replaces_open_row(storage, portfolio_id):
    position = _open_long(portfolio_id)
    storage.set_position("BTCUSD", position)
    # Mutate + re-set: still exactly one open row for the ticker (dict-assignment parity).
    position.update_current_price_time(Decimal("32000.00"), _T2)
    storage.set_position("BTCUSD", position)

    positions = storage.get_positions()
    assert list(positions) == ["BTCUSD"]
    assert positions["BTCUSD"].current_price == Decimal("32000.00")


def test_remove_position(storage, portfolio_id):
    position = _open_long(portfolio_id)
    storage.set_position("BTCUSD", position)
    storage.remove_position("BTCUSD")
    assert storage.get_position("BTCUSD") is None
    assert storage.get_positions() == {}


def test_closed_position_round_trip(storage, portfolio_id):
    closed = _closed_short(portfolio_id)
    storage.add_closed_position(closed)

    closed_positions = storage.get_closed_positions()
    assert len(closed_positions) == 1
    _assert_position_projection_equal(closed_positions[0], closed)
    # A closed position is NOT visible through the open-position accessors.
    assert storage.get_positions() == {}
    assert storage.get_position("ETHUSD") is None


# --------------------------------------------------------------------------- transactions
def test_transaction_round_trip_field_equal(storage, portfolio_id):
    transaction = _transaction(portfolio_id)
    storage.add_transaction(transaction)

    history = storage.get_transaction_history()
    assert len(history) == 1
    # Transaction is a msgspec.Struct — direct field-wise ``==``.
    assert history[0] == transaction
    assert isinstance(history[0].price, Decimal)
    assert history[0].price == transaction.price


def test_transaction_history_stable_order(storage, portfolio_id):
    first = _transaction(portfolio_id)
    second = _transaction(portfolio_id)
    storage.add_transaction(first)
    storage.add_transaction(second)
    history = storage.get_transaction_history()
    assert {t.id for t in history} == {first.id, second.id}


# --------------------------------------------------------------------------- cash reservations
def test_reservation_money_exact_full_precision(storage):
    amount = Decimal("1234.567890123456789")
    storage.add_reservation("ORDER-1", amount)

    reserved = storage.get_reserved_cash()
    assert isinstance(reserved, Decimal)
    assert reserved == amount  # full precision, no quantize (OPS-04)

    popped = storage.pop_reservation("ORDER-1")
    assert popped == amount and isinstance(popped, Decimal)
    # Idempotent release: popping again returns None, balance back to zero.
    assert storage.pop_reservation("ORDER-1") is None
    assert storage.get_reserved_cash() == Decimal("0")


def test_reservation_upsert_replaces(storage):
    storage.add_reservation("ORDER-1", Decimal("100.00"))
    storage.add_reservation("ORDER-1", Decimal("250.50"))
    assert storage.get_reserved_cash() == Decimal("250.50")


# --------------------------------------------------------------------------- locked margin
def test_locked_margin_money_exact_full_precision(storage):
    amount = Decimal("987.654321098765432")
    storage.add_locked_margin("POS-1", amount)

    assert storage.get_locked_margin() == amount
    assert storage.get_locked_margin_for("POS-1") == amount
    assert storage.get_locked_margin_for("POS-MISSING") == Decimal("0")

    popped = storage.pop_locked_margin("POS-1")
    assert popped == amount and isinstance(popped, Decimal)
    assert storage.pop_locked_margin("POS-1") is None
    assert storage.get_locked_margin() == Decimal("0")


# --------------------------------------------------------------------------- cash operations
def test_cash_operation_round_trip_field_equal(storage):
    operation = _cash_operation()
    storage.add_cash_operation(operation)

    operations = storage.get_cash_operations()
    assert len(operations) == 1
    # CashOperation is a @dataclass — field-wise ``==`` (injected portfolio_id is not a field).
    assert operations[0] == operation
    assert isinstance(operations[0].amount, Decimal)
    assert operations[0].amount == operation.amount


# --------------------------------------------------------------------------- snapshots
def test_snapshot_round_trip_field_equal(storage):
    snapshot = _snapshot("10000.12")
    storage.add_snapshot(snapshot)

    snapshots = storage.get_snapshots()
    assert len(snapshots) == 1
    assert snapshots[0] == snapshot  # @dataclass field-wise ==
    assert isinstance(snapshots[0].total_equity, Decimal)


def test_snapshot_stable_seq_order_on_tied_timestamps(storage):
    # All three share _T0 — only the explicit per-portfolio seq disambiguates order (Pitfall 7).
    equities = ["100.00", "200.00", "300.00"]
    for equity in equities:
        storage.add_snapshot(_snapshot(equity))

    snapshots = storage.get_snapshots()
    assert [str(s.total_equity) for s in snapshots] == equities
    assert storage.snapshot_count() == 3

    latest = storage.get_latest_snapshot()
    assert latest is not None
    assert latest.total_equity == Decimal("300.00")


def test_set_snapshots_replaces_and_renumbers(storage):
    storage.add_snapshot(_snapshot("100.00"))
    storage.add_snapshot(_snapshot("200.00"))
    replacement = [_snapshot("900.00"), _snapshot("950.00")]
    storage.set_snapshots(replacement)

    snapshots = storage.get_snapshots()
    assert [str(s.total_equity) for s in snapshots] == ["900.00", "950.00"]
    assert storage.snapshot_count() == 2


def test_empty_snapshots_accessors(storage):
    assert storage.get_snapshots() == []
    assert storage.snapshot_count() == 0
    assert storage.get_latest_snapshot() is None


# --------------------------------------------------------------------------- isolation
def test_cross_portfolio_isolation(pg_backend, portfolio_id):
    """Pitfall 1 / T-03-08 — a backend bound to A sees nothing written under B."""
    other_id = uc.uuid7()
    storage_a = SqlPortfolioStateStorage(pg_backend, portfolio_id)
    storage_b = SqlPortfolioStateStorage(pg_backend, other_id)

    # Write the full surface under portfolio A.
    storage_a.set_position("BTCUSD", _open_long(portfolio_id))
    storage_a.add_closed_position(_closed_short(portfolio_id))
    storage_a.add_transaction(_transaction(portfolio_id))
    storage_a.add_reservation("ORDER-A", Decimal("500.00"))
    storage_a.add_locked_margin("POS-A", Decimal("250.00"))
    storage_a.add_cash_operation(_cash_operation())
    storage_a.add_snapshot(_snapshot("10000.00"))

    # Portfolio B (bound to a different id over the SAME backend/DB) sees NONE of it.
    assert storage_b.get_positions() == {}
    assert storage_b.get_position("BTCUSD") is None
    assert storage_b.get_closed_positions() == []
    assert storage_b.get_transaction_history() == []
    assert storage_b.get_reserved_cash() == Decimal("0")
    assert storage_b.get_locked_margin() == Decimal("0")
    assert storage_b.get_locked_margin_for("POS-A") == Decimal("0")
    assert storage_b.get_cash_operations() == []
    assert storage_b.get_snapshots() == []
    assert storage_b.snapshot_count() == 0

    # And A still sees its own rows (scoping is a filter, not a global wipe).
    assert set(storage_a.get_positions()) == {"BTCUSD"}
    assert storage_a.get_reserved_cash() == Decimal("500.00")

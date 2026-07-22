"""OPS-01 / OPS-04 — ``SqlOrderStorage`` Postgres round-trip + bracket + money + determinism.

The order-mirror operational backend must persist an ``Order`` losslessly on Postgres and
read it back D-10 field-wise EQUAL (``obj2 == order``) — which, because ``Order.__eq__`` is a
field-wise dataclass comparison, transitively proves ``state_changes`` (the
``order_state_changes`` child table) and ``child_order_ids`` (rebuilt from the
``parent_order_id`` index, Pitfall 6) round-trip too. Money columns are Postgres-native
``Numeric`` and read back as exact ``Decimal`` (OPS-04, Pitfall 2 — SQLite ``Numeric`` decays
to float, so the money/round-trip arms are gated to the ``pg_backend`` Postgres fixture).

Threat coverage (03-02 register):
* T-03-05 (money precision loss) — exact-``Decimal`` money asserted on the Postgres arm.
* T-03-04 (bracket FK orphan/drift) — the parent persists before children; the parent reads
  back with ``child_order_ids`` populated via the self-referential FK query.
* T-03-06 (undisposed engine ResourceWarning) — the ``pg_backend`` fixture disposes (Pitfall 4).

The Postgres arm SKIPS (never hard-fails) when Docker is absent (D-11, inherited from
``pg_engine`` via ``pg_backend``); the determinism check is backend-free and always runs.
4-space indentation (matches ``tests/integration/*``); NO ``__init__.py`` in this dir.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import uuid_utils.compat as uc

from itrader.core.enums import OrderStatus, OrderTriggerSource, OrderType, Side
from itrader.core.ids import OrderId, PortfolioId, StrategyId
from itrader.order_handler.order import Order
from itrader.order_handler.storage.sql_storage import SqlOrderStorage
from itrader.storage import UtcIsoText
from tests.support.schema import provision_schema

# A business time (never wall clock) reused so derived created_at/updated_at are deterministic.
_BT = datetime(2020, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_storage(pg_backend) -> SqlOrderStorage:
    """Construct the schema-pure ``SqlOrderStorage`` and provision its schema (WR-03/D-14)."""
    storage = SqlOrderStorage(pg_backend)
    provision_schema(pg_backend)
    return storage


def _make_order(**overrides):
    """Build a fully-populated ``Order`` with unique UUIDv7 ids (overridable per field)."""
    base = dict(
        time=_BT,
        type=OrderType.LIMIT,
        status=OrderStatus.PENDING,
        ticker="BTCUSD",
        action=Side.BUY,
        price=Decimal("45000.12345678"),
        quantity=Decimal("0.5"),
        exchange="paper",
        strategy_id=StrategyId(uc.uuid7()),
        portfolio_id=PortfolioId(uc.uuid7()),
    )
    base.update(overrides)
    return Order(**base)


def test_order_round_trip_field_wise_equal(pg_backend):
    """OPS-01 — a full Order (incl. state_changes) round-trips D-10 field-wise EQUAL.

    ``Order`` is a field-wise dataclass, so ``obj2 == order`` also proves the
    ``order_state_changes`` child table and the (empty) ``child_order_ids`` round-trip.
    Runs on the Postgres arm only (money columns; Pitfall 2).
    """
    storage = _make_storage(pg_backend)
    order = _make_order()
    # Exercise the state-change child table (a clean transition; additional_data stays None).
    order.add_state_change(
        OrderStatus.PARTIALLY_FILLED, "partial fill", OrderTriggerSource.EXCHANGE
    )
    assert len(order.state_changes) == 1  # guard: the child table actually has a row to prove

    storage.add_order(order)
    got = storage.get_order_by_id(order.id)

    assert got is not None
    assert got == order  # D-10 field-wise equality (price, *_at, state_changes, child ids, …)


def test_bracket_children_rebuilt_from_parent_fk(pg_backend):
    """T-03-04 — a bracket parent reads back with child_order_ids populated by the FK query.

    The parent is inserted before the children (FK ordering, Pitfall 6); ``child_order_ids``
    is NOT a column (D-02) — it is rebuilt via ``SELECT id WHERE parent_order_id = :id``.
    """
    storage = _make_storage(pg_backend)
    parent = _make_order()
    child_one = _make_order(parent_order_id=parent.id, type=OrderType.STOP, action=Side.SELL)
    child_two = _make_order(parent_order_id=parent.id, type=OrderType.LIMIT, action=Side.SELL)

    storage.add_order(parent)  # parent FIRST — the self-ref FK target must exist
    storage.add_order(child_one)
    storage.add_order(child_two)

    got_parent = storage.get_order_by_id(parent.id)
    assert got_parent is not None
    assert set(got_parent.child_order_ids) == {child_one.id, child_two.id}

    # And a child reads back pointing at the parent (no orphan/drift).
    got_child = storage.get_order_by_id(child_one.id)
    assert got_child is not None
    assert got_child.parent_order_id == parent.id


def test_money_round_trips_exact_decimal(pg_backend):
    """OPS-04 / T-03-05 — order.price round-trips as an EXACT Decimal (Postgres-native Numeric)."""
    storage = _make_storage(pg_backend)
    order = _make_order(price=Decimal("31415.92653589"), quantity=Decimal("0.00000001"))
    storage.add_order(order)

    got = storage.get_order_by_id(order.id)
    assert got is not None
    assert got.price == order.price and isinstance(got.price, Decimal)
    assert got.quantity == order.quantity and isinstance(got.quantity, Decimal)
    assert got.leverage == order.leverage and isinstance(got.leverage, Decimal)


def test_uuid_id_round_trips_value_equal(pg_backend):
    """SPINE-03 — the UUIDv7 order id round-trips value-equal as a native uuid.UUID."""
    storage = _make_storage(pg_backend)
    order = _make_order()
    storage.add_order(order)

    got = storage.get_order_by_id(order.id)
    assert got is not None
    assert got.id == order.id and isinstance(got.id, uuid.UUID)
    assert isinstance(got.strategy_id, uuid.UUID)
    assert isinstance(got.portfolio_id, uuid.UUID)


def test_query_helpers_round_trip(pg_backend):
    """OPS-01 — status / active / ticker / history queries return the persisted order.

    Scoped to a unique portfolio_id so the session-shared Postgres DB stays test-isolated.
    """
    storage = _make_storage(pg_backend)
    pid = PortfolioId(uc.uuid7())
    order = _make_order(portfolio_id=pid)
    order.add_state_change(OrderStatus.CANCELLED, "operator cancel", OrderTriggerSource.USER)
    storage.add_order(order)

    by_status = storage.get_orders_by_status(OrderStatus.CANCELLED, portfolio_id=pid)
    assert [o.id for o in by_status] == [order.id]

    by_ticker = storage.get_orders_by_ticker("BTCUSD", portfolio_id=pid)
    assert [o.id for o in by_ticker] == [order.id]

    # Cancelled is terminal -> not active.
    assert storage.get_active_orders(portfolio_id=pid) == []

    counts = storage.count_orders_by_status(portfolio_id=pid)
    assert counts == {"CANCELLED": 1}

    history = storage.get_order_history(order.id)
    assert [h["to_status"] for h in history] == ["CANCELLED"]
    assert history[0]["triggered_by"] == "user"


def test_business_time_encoding_determinism():
    """T-03 determinism — two binds of the same business time produce identical UtcIsoText bytes.

    Backend-free (mirrors the spine determinism test): always runs, even Dockerless.
    """
    from sqlalchemy.dialects import sqlite

    first = UtcIsoText().process_bind_param(_BT, sqlite.dialect())
    second = UtcIsoText().process_bind_param(_BT, sqlite.dialect())

    assert first == second
    assert first == "2020-01-01T12:00:00+00:00"
